import os
import json
import time
import tempfile
from typing import Optional, Tuple
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai.errors import APIError
from .models import ExtractedDocument


class GeminiOCR:
    def __init__(self, drive_service, enable_shared_drives: bool = True):
        self.drive = drive_service
        self.client = genai.Client() if "GEMINI_API_KEY" in os.environ else None
        self.enable_shared_drives = enable_shared_drives

    def _base_params(self) -> dict:
        return {"supportsAllDrives": True} if self.enable_shared_drives else {}

    def _download_for_ocr(self, file_id: str, mime_type: str) -> Tuple[Optional[str], str]:
        is_native = mime_type.startswith("application/vnd.google-apps")
        effective_mime = "application/pdf" if is_native and "document" in mime_type else mime_type

        try:
            if is_native:
                if "document" in mime_type:
                    request = self.drive.files().export_media(fileId=file_id, mimeType="application/pdf")
                else:
                    return None, mime_type
            else:
                request = self.drive.files().get_media(fileId=file_id, **self._base_params())

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                downloader = MediaIoBaseDownload(tmp, request, chunksize=8 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                tmp.flush()
                return tmp.name, effective_mime
        except Exception as e:
            print(f"Download for OCR failed: {e}")
            return None, mime_type

    @staticmethod
    def _is_retryable(api_err: APIError) -> bool:
        code = getattr(api_err, "code", None)
        msg = str(api_err).lower()
        return code == 429 or "resourceexhausted" in msg or "quota" in msg

    def extract_structured_data(self, file_id: str, mime_type: str) -> Tuple[Optional[dict], str]:
        if not self.client:
            return None, mime_type
        if not (mime_type.startswith("image/") or mime_type == "application/pdf" or "document" in mime_type):
            return None, mime_type

        tmp_path, effective_mime = self._download_for_ocr(file_id, mime_type)
        if not tmp_path:
            return None, effective_mime

        gemini_file = None
        try:
            gemini_file = self.client.files.upload(file=tmp_path, mime_type=effective_mime)
            prompt = "Bitte analysiere dieses Dokument und extrahiere die angeforderten strukturierten Daten."

            max_retries = 6
            for attempt in range(max_retries):
                try:
                    response = self.client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[gemini_file, prompt],
                        config={"response_mime_type": "application/json", "response_schema": ExtractedDocument}
                    )
                    if response.text:
                        return json.loads(response.text), effective_mime
                    return None, effective_mime
                except APIError as api_err:
                    if self._is_retryable(api_err):
                        sleep_time = min(120, (2 ** attempt) * 3)
                        print(f"Gemini Quota/Rate Limit ({getattr(api_err, 'code', 'unknown')}). Backoff {sleep_time}s (Versuch {attempt+1}/{max_retries})")
                        time.sleep(sleep_time)
                        continue
                    print(f"Gemini non-retryable API error for {file_id}: {api_err}")
                    raise

            print(f"Gemini OCR retries exhausted for file {file_id}.")
            return None, effective_mime

        except Exception as e:
            print(f"Gemini OCR Fehler für {file_id}: {e}")
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
                    print(f"Warning: Failed to delete Gemini temp file {gemini_file.name}: {e}")
