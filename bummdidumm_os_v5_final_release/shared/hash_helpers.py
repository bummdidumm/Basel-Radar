import hashlib
from typing import Optional, Tuple
from googleapiclient.http import MediaIoBaseDownload

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
    """Returns (SHA256, ExportSource) using true streaming downloads directly into memory."""
    is_native = mime_type.startswith("application/vnd.google-apps")
    export_source = "Native Drive" if is_native else "Binary File"

    try:
        if is_native:
            export_mime = "application/pdf"
            request = drive_service.files().export_media(fileId=file_id, mimeType=export_mime)
            export_source = "Exported as PDF"
        else:
            request = drive_service.files().get_media(fileId=file_id, **base_params)

        sink = HashingSink()
        downloader = MediaIoBaseDownload(sink, request, chunksize=8 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        return sink.sha.hexdigest(), export_source
    except Exception as e:
        import logging
        logging.getLogger("bummdidumm.hash").error("Hash error", extra={"file_id": file_id, "error": str(e)})
        return None, "Error"
