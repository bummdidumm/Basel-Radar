import hashlib
from typing import Optional, Tuple
from googleapiclient.http import MediaIoBaseDownload
import tempfile

def calculate_sha256_streaming(drive_service, file_id: str, mime_type: str, base_params: dict) -> Tuple[Optional[str], str]:
    """Returns (SHA256, ExportSource) using true streaming downloads."""
    is_native = mime_type.startswith("application/vnd.google-apps")
    export_source = "Native Drive" if is_native else "Binary File"

    try:
        if is_native:
            export_mime = "application/pdf"
            request = drive_service.files().export_media(fileId=file_id, mimeType=export_mime)
            export_source = "Exported as PDF"
        else:
            request = drive_service.files().get_media(fileId=file_id, **base_params)

        with tempfile.NamedTemporaryFile() as tmp:
            downloader = MediaIoBaseDownload(tmp, request, chunksize=8 * 1024 * 1024)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            tmp.flush()
            tmp.seek(0)

            sha = hashlib.sha256()
            while True:
                chunk = tmp.read(8 * 1024 * 1024)
                if not chunk:
                    break
                sha.update(chunk)
            return sha.hexdigest(), export_source
    except Exception as e:
        print(f"Hash error for {file_id}: {e}")
        return None, "Error"
