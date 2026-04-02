import os
import json
from datetime import datetime, timezone

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

    current_run_id = state.get_val("last_successful_run_id")

    if not current_run_id:
        state.log_error("PASS_2", "SYSTEM", "", "NoRunID", "Kein erfolgreicher Pass 1 gefunden.")
        return

    # Lese Folder-Aware Indexing Daten aus Sorting_Suggestions (Pass 3) ein
    # Schema: ["run_id", "file_id", "name", "mime_type", "current_location", "current_parent_id", "suggested_target_folder", "suggested_target_folder_id", "target_path", "rule_reason", "action_mode", "move_result"]
    sorting_data = {}
    sort_rows = sheet_mgr.read_all_rows("Sorting_Suggestions")
    for s_row in sort_rows:
        if len(s_row) >= 12 and s_row[0] == current_run_id:
            sorting_data[s_row[1]] = {
                "current_parent_id": s_row[5],
                "target_parent_id": s_row[7],
                "target_path": s_row[8],
                "folder_rule_reason": s_row[9],
                "sort_mode": s_row[10],
                "move_result": s_row[11]
            }

    records_to_index = []
    processed = 0
    errors = 0

    # Cap Pass 2 RAM load: Chunkweises Auslesen
    for chunk_rows in sheet_mgr.read_rows_chunked("Dedupe_Report", chunk_size=1000):
        for row in chunk_rows:
            if len(row) < 17 or row[0] == "run_utc": continue
            if row[1] != current_run_id: continue # Nur Dateien des letzten Laufs

            status = row[10]
            change_type = row[11]
            file_id = row[4]
            mime_type = row[5]

            # Validiere, welche Records wir überhaupt an das AI-OS im JSONL weiterleiten.
            # Wir lassen "DUPLICATE" und "SKIPPED_SIZE" weg.
            valid_statuses = ["ORIGINAL", "ORIGINAL_RESUMED", "UNCHANGED_CONTENT", "DELETED", "TRASHED", "REMOVED_OR_NO_ACCESS"]
            if not any(status.startswith(s) for s in valid_statuses):
                continue

            rec = FileRecord(
                run_utc=row[0],
                run_id=row[1],
                path_display=row[2],
                name=row[3],
                file_id=file_id,
                mime_type=mime_type,
                effective_mime_type=row[6],
                size_bytes=int(row[7]) if str(row[7]).isdigit() else 0,
                md5=row[8],
                sha256=row[9],
                status=status,
                change_type=change_type,
                duplicate_of=row[12],
                archive_result=row[13],
                suggested_name=row[14],
                web_link=row[15],
                notes=row[16]
            )

            # Folder-Aware Indexing anreichern
            s_data = sorting_data.get(file_id, {})
            if s_data:
                rec.current_parent_id = s_data.get("current_parent_id", "")
                rec.target_parent_id = s_data.get("target_parent_id", "")
                rec.target_path = s_data.get("target_path", "")
                rec.folder_rule = "Auto-Sort"
                rec.folder_rule_reason = s_data.get("folder_rule_reason", "")
                rec.sort_mode = s_data.get("sort_mode", "")
                rec.move_result = s_data.get("move_result", "")

            # ZWEI-PFADE ORCHESTRIERUNG FÜR PASS 2
            # Pfad A: OCR-pflichtige Originale
            if ENABLE_OCR and status in ["ORIGINAL", "ORIGINAL_RESUMED"] and change_type in ["NEW", "UPDATED"]:
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

            # Pfad B: Statusereignisse ohne OCR
            elif change_type in ["DELETED", "TRASHED", "REMOVED_OR_NO_ACCESS", "MOVED", "RENAMED", "MOVED_AND_RENAMED", "UNCHANGED_CONTENT_METADATA_ONLY"] or status == "UNCHANGED_CONTENT":
                # Kein OCR, wir signalisieren dem nachgelagerten System nur die Bestandsänderung
                rec.notes = "event_only_no_content_processing"

            records_to_index.append(rec)
            processed += 1

    if not records_to_index:
        state.log_run("PASS_2", "NO_FILES", 0, errors)
        return

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{date_str}_{PROJECT_SLUG}_delta.jsonl"

    try:
        with open(filename, "w", encoding="utf-8") as f:
            for r in records_to_index:
                j_dict = {
                    "run_utc": r.run_utc,
                    "run_id": r.run_id,
                    "path": r.path_display,
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
                    "current_parent_id": r.current_parent_id,
                    "current_path": r.current_path,
                    "target_parent_id": r.target_parent_id,
                    "target_path": r.target_path,
                    "folder_rule": r.folder_rule,
                    "folder_rule_reason": r.folder_rule_reason,
                    "sort_mode": r.sort_mode,
                    "move_result": r.move_result,
                    "ocr": {
                        "doc_type": r.ocr_doc_type,
                        "amount": r.ocr_amount,
                        "date": r.ocr_date,
                        "vendor": r.ocr_vendor,
                        "summary": r.ocr_summary,
                        "full_text": r.ocr_full_text
                    } if r.notes != "event_only_no_content_processing" else None,
                    "web_link": r.web_link,
                    "notes": r.notes
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
