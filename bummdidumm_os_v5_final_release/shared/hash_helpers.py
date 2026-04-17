import hashlib
import time
from typing import Optional, Tuple
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError
from shared.log import get_logger as _get_logger

_log = _get_logger("hash", phase="SHARED")

_RETRYABLE_HASH_STATUSES = (429, 500, 503)
_HASH_MAX_ATTEMPTS = 3


class HashingSink:
    """Mock file object to hash data directly from stream without writing to disk."""
    def __init__(self):
        self.sha = hashlib.sha256()
        self._pos = 0

    def write(self, data: bytes) -> int:
        self.sha.update(data)
        self._pos += len(data)
        return len(data)

    def tell(self) -> int:
        return self._pos

    def seek(self, pos: int, whence: int = 0):
        if pos == 0 and whence == 0:
            self.sha = hashlib.sha256()
            self._pos = 0
        else:
            raise NotImplementedError("HashingSink only supports seek(0, 0) for retries")

    def flush(self):
        pass

def calculate_sha256_streaming(drive_service, file_id: str, mime_type: str, base_params: dict) -> Tuple[Optional[str], str]:
    """Returns (SHA256, ExportSource) using true streaming downloads directly into memory.

    Retries up to _HASH_MAX_ATTEMPTS times on transient HTTP errors (429/500/503).
    A fresh HashingSink and request are created on each attempt to avoid partial-read
    corruption from the stateful MediaIoBaseDownload object.
    """
    is_native = mime_type.startswith("application/vnd.google-apps")
    export_source = "Exported as PDF" if is_native else "Binary File"

    for attempt in range(_HASH_MAX_ATTEMPTS):
        try:
            if is_native:
                request = drive_service.files().export_media(fileId=file_id, mimeType="application/pdf")
            else:
                request = drive_service.files().get_media(fileId=file_id, **base_params)

            sink = HashingSink()
            downloader = MediaIoBaseDownload(sink, request, chunksize=8 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()

            return sink.sha.hexdigest(), export_source

        except (HttpError, OSError, IOError) as e:
            is_http_err = isinstance(e, HttpError)
            status_code = getattr(getattr(e, 'resp', None), 'status', None) if is_http_err else None

            if is_http_err and status_code in _RETRYABLE_HASH_STATUSES and attempt < _HASH_MAX_ATTEMPTS - 1:
                sleep_sec = (2 ** attempt) + 1
                _log.warning(
                    "Hash download transient error — retrying",
                    extra={"file_id": file_id, "status_code": status_code, "attempt": attempt + 1, "sleep_sec": sleep_sec}
                )
                time.sleep(sleep_sec)
                continue

            _log.error(
                "Hash calculation error",
                extra={
                    "file_id": file_id,
                    "error": str(e),
                    "is_http_error": is_http_err,
                    "status_code": status_code,
                    "attempts": attempt + 1,
                }
            )
            return None, "Error"

    return None, "Error"
