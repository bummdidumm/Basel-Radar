import os
import json
import time
import tempfile
from threading import Lock
from typing import Optional, Tuple
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai.errors import APIError
from .models import ExtractedDocument
from shared.log import get_logger as _get_logger
_log = _get_logger("gemini", phase="SHARED")

_gemini_call_times: list[float] = []
_gemini_lock = Lock()
_GEMINI_RPM_LIMIT = max(1, int(os.environ.get("GEMINI_RPM_LIMIT", "9")))
# Default 9 = safe buffer below gemini-2.5-flash Free Tier (10 RPM official limit)
# Adjust via env var if model or tier changes. Clamped to >= 1 so the
# rate-limit loop never attempts _gemini_call_times[0] on an empty list.


def _rate_limit_gemini() -> None:
    """Proactive RPM guard before generate_content calls."""
    while True:
        with _gemini_lock:
            now = time.monotonic()
            _gemini_call_times[:] = [t for t in _gemini_call_times if now - t < 60]

            if len(_gemini_call_times) < _GEMINI_RPM_LIMIT:
                _gemini_call_times.append(now)
                return

            sleep_time = max(0.0, 60 - (now - _gemini_call_times[0]) + 0.5)

        _log.info("Gemini RPM limit reached, sleeping %.1fs", sleep_time)
        time.sleep(sleep_time)

_OCR_WORTHY_MIMES = frozenset({
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/tiff",
    "image/bmp", "image/heic", "image/heif",
    "application/pdf",
    "application/vnd.google-apps.document",
})

_OCR_SYSTEM_PROMPT = (
    "Du bist ein Dokumenten-Analyse-Spezialist für einen persönlichen Wissens-Assistenten in der Schweiz.\n"
    "Extrahiere ausschliesslich Informationen die explizit im Dokument vorhanden sind.\n"
    "- Erfinde keine Werte. Falls ein Feld nicht vorhanden: null zurückgeben.\n"
    "- Behalte originale Schreibweise für Namen, Beträge und Daten bei.\n"
    "- Dokumente können auf Deutsch, Französisch, Englisch oder Italienisch sein.\n"
    "- Währungen: CHF (Schweizer Franken), EUR, USD.\n"
    "- Sensitivity high: Ausweise, Kontoauszüge, Verträge, medizinische Dokumente.\n"
)


class GeminiOCR:
    def __init__(self, drive_service, enable_shared_drives: bool = True):
        self.drive = drive_service
        self.client = genai.Client() if "GEMINI_API_KEY" in os.environ else None
        self.enable_shared_drives = enable_shared_drives

    @staticmethod
    def is_ocr_worthy(mime_type: str) -> bool:
        """True wenn MIME-Type OCR-relevant. Verhindert API-Calls für Code/JSON/CSV."""
        return mime_type in _OCR_WORTHY_MIMES or mime_type.startswith("image/")

    def _base_params(self) -> dict:
        return {"supportsAllDrives": True} if self.enable_shared_drives else {}

    def _download_for_ocr(self, file_id: str, mime_type: str) -> Tuple[Optional[str], str]:
        is_native = mime_type.startswith("application/vnd.google-apps")
        effective_mime = "application/pdf" if is_native and "document" in mime_type else mime_type

        tmp_name = None
        try:
            if is_native:
                if "document" in mime_type:
                    request = self.drive.files().export_media(fileId=file_id, mimeType="application/pdf")
                else:
                    return None, mime_type
            else:
                request = self.drive.files().get_media(fileId=file_id, **self._base_params())

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_name = tmp.name
                downloader = MediaIoBaseDownload(tmp, request, chunksize=8 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                tmp.flush()
            return tmp_name, effective_mime
        except Exception as e:
            _log.error("OCR Download fehlgeschlagen", extra={"error": str(e)})
            if tmp_name:
                try:
                    os.remove(tmp_name)
                except FileNotFoundError:
                    pass
            return None, mime_type

    @staticmethod
    def _is_retryable(api_err: APIError) -> bool:
        code = getattr(api_err, "code", None)
        msg = str(api_err).lower()
        return code in (429, 503) or "resourceexhausted" in msg or "quota" in msg or "overloaded" in msg

    def extract_structured_data(self, file_id: str, mime_type: str) -> Tuple[Optional[dict], str]:
        if not self.client:
            return None, mime_type
        if not self.is_ocr_worthy(mime_type):
            return None, mime_type

        tmp_path, effective_mime = self._download_for_ocr(file_id, mime_type)
        if not tmp_path:
            return None, effective_mime

        gemini_file = None
        try:
            gemini_file = self.client.files.upload(file=tmp_path, mime_type=effective_mime)
            prompt = "Analysiere dieses Dokument und extrahiere alle angeforderten strukturierten Felder."

            max_retries = 6
            for attempt in range(max_retries):
                try:
                    _rate_limit_gemini()
                    response = self.client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[gemini_file, prompt],
                        config={
                            "system_instruction": _OCR_SYSTEM_PROMPT,
                            "response_mime_type": "application/json",
                            "response_schema": ExtractedDocument,
                            "temperature": 0.1,
                        }
                    )
                    if response.text:
                        return json.loads(response.text), effective_mime
                    return None, effective_mime
                except APIError as api_err:
                    if self._is_retryable(api_err):
                        sleep_time = min(120, (2 ** attempt) * 3)
                        _log.warning("Gemini rate limit", extra={"code": getattr(api_err, "code", "unknown"), "sleep_sec": sleep_time, "attempt": attempt + 1})
                        time.sleep(sleep_time)
                        continue

                    _log.error("Gemini non-retryable error", extra={"file_id": file_id, "error": str(api_err)})
                    raise

            _log.error("Gemini OCR retries exhausted", extra={"file_id": file_id})
            return None, effective_mime

        except Exception as e:
            _log.error("Gemini OCR exception", extra={"file_id": file_id, "error": str(e)})
            return None, effective_mime
        finally:
            try:
                os.remove(tmp_path)
            except FileNotFoundError:
                pass
            if gemini_file:
                try:
                    self.client.files.delete(name=gemini_file.name)
                except Exception as e:
                    _log.warning("Gemini temp file cleanup fehlgeschlagen", extra={"name": gemini_file.name, "error": str(e)})
