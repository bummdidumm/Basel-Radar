import os
import json
from datetime import datetime, timezone
from typing import List

import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker
from shared.gemini_helpers import GeminiOCR
from shared.models import FileRecord

CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
INDEX_FOLDER_ID = os.environ.get("INDEX_FOLDER_ID")
PROJECT_SLUG = os.environ.get("PROJECT_SLUG", "bummdidumm")

ENABLE_OCR = os.environ.get("ENABLE_OCR", "true").lower() == "true"
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"

def run_pass2():
    print("Starte Pass 2: OCR + Indexing")
    if not all([CONTROL_SHEET_ID, INDEX_FOLDER_ID]):
        raise ValueError("Missing CONTROL_SHEET_ID or INDEX_FOLDER_ID")

    credentials, _ = google.auth.default()
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)
    ocr = GeminiOCR(drive_service, ENABLE_SHARED_DRIVES)

    state.set_val("current_phase", "PASS2_OCR_INDEXING")

    # Lese den Report des aktuellen Laufs (Pass 1 muss fertig sein)
    # Dedupe_Report schema: run_utc, run_id, path, name, file_id, mime_type, effective_mime_type, size_bytes, md5, sha256, status...
    rows = sheet_mgr.read_all_rows("Dedupe_Report")

    current_run_id = state.get_val("last_successful_run_id")
    if not current_run_id:
        state.log_error("PASS_2", "SYSTEM", "", "NoRunID", "Kein erfolgreicher Pass 1 gefunden.")
        return

    records_to_index = []
    processed = 0
    errors = 0

    for row in rows:
        if len(row) < 17 or row[0] == "run_utc": continue
        if row[1] != current_run_id: continue # Nur Dateien des letzten Laufs
        if "ORIGINAL" not in row[10]: continue # Nur Originale verarbeiten

        file_id = row[4]
        mime_type = row[5]

        rec = FileRecord(
            file_id=file_id,
            name=row[3],
            path=row[2],
            mime_type=mime_type,
            effective_mime_type=row[6],
            size_bytes=int(row[7]) if row[7].isdigit() else 0,
            md5=row[8],
            sha256=row[9],
            status=row[10],
            change_type=row[11],
            duplicate_of=row[12],
            archive_result=row[13],
            suggested_name=row[14],
            web_link=row[15],
            notes=row[16],
            updated_at="",
            created_time=""
        )

        # OCR
        if ENABLE_OCR:
            ocr_data, effective_mime = ocr.extract_structured_data(file_id, mime_type)
            if ocr_data:
                rec.ocr_doc_type = ocr_data.get("doc_type", "")
                rec.ocr_amount = str(ocr_data.get("amount", ""))
                rec.ocr_date = ocr_data.get("date", "")
                rec.ocr_vendor = ocr_data.get("vendor", "")
                rec.ocr_summary = ocr_data.get("summary", "")
                rec.ocr_full_text = ocr_data.get("full_text", "")
                rec.effective_mime_type = effective_mime
            else:
                errors += 1
                state.log_error("PASS_2", file_id, rec.name, "OCRError", "Fehler bei der OCR-Extraktion")

        records_to_index.append(rec)
        processed += 1

    # JSONL Export
    if not records_to_index:
        state.log_run("PASS_2", "NO_FILES", 0, errors)
        return

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"index_{PROJECT_SLUG}_{date_str}.jsonl"

    try:
        with open(filename, "w", encoding="utf-8") as f:
            for r in records_to_index:
                # JSONL Mappings
                j_dict = {
                    "run_utc": state.get_val("last_run_utc"),
                    "run_id": current_run_id,
                    "path": r.path,
                    "name": r.name,
                    "file_id": r.file_id,
                    "mime_type": r.mime_type,
                    "effective_mime_type": r.effective_mime_type,
                    "size_bytes": r.size_bytes,
                    "md5": r.md5,
                    "sha256": r.sha256,
                    "status": r.status,
                    "change_type": r.change_type,
                    "duplicate_of": r.duplicate_of,
                    "archive_result": r.archive_result,
                    "suggested_name": r.suggested_name,
                    "ocr": {
                        "doc_type": r.ocr_doc_type,
                        "amount": r.ocr_amount,
                        "date": r.ocr_date,
                        "vendor": r.ocr_vendor,
                        "summary": r.ocr_summary,
                        "full_text": r.ocr_full_text
                    },
                    "web_link": r.web_link
                }
                f.write(json.dumps(j_dict, ensure_ascii=False) + "\n")

        media = MediaFileUpload(filename, mimetype="application/x-ndjson")
        params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

        drive_service.files().create(
            body={"name": filename, "parents": [INDEX_FOLDER_ID]},
            media_body=media,
            fields="id",
            **params
        ).execute()

        state.set_val("current_phase", "PASS2_DONE")
        state.log_run("PASS_2", "SUCCESS", processed, errors)

    except Exception as e:
        state.set_val("current_phase", "PASS2_FAILED")
        state.log_error("PASS_2", "SYSTEM", "ExportJSONL", "Fatal", str(e))
        state.log_run("PASS_2", "FAILED", processed, errors + 1)
        raise e
    finally:
        if os.path.exists(filename):
            os.remove(filename)

if __name__ == "__main__":
    run_pass2()
