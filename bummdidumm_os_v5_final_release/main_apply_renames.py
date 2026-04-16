import os
from shared.oauth_user_credentials import get_user_credentials
from googleapiclient.discovery import build

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker

CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"

def run_apply_renames():
    if not CONTROL_SHEET_ID:
        raise ValueError("Missing CONTROL_SHEET_ID")

    credentials = get_user_credentials()
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    from shared.drive_helpers import DriveManager
    drive_mgr = DriveManager(drive_service, "")

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)
    from shared.log import get_logger
    log = get_logger("apply_renames", phase="APPLY_RENAMES")

    _lock_timeout = int(os.environ.get("APPLY_RENAMES_LOCK_TIMEOUT_SEC", "600"))
    if not state.acquire_job_lock("apply_renames", timeout_sec=_lock_timeout):
        log.warning("Apply Renames abgebrochen: anderer Prozess hält den Lock")
        return

    try:
        log.info("Rename Job gestartet")
        state.set_val("current_phase", "APPLY_RENAMES")
        state.flush_state()

        current_run_id = state.get_val("last_successful_run_id")

        if not current_run_id:
            state.log_error("RENAME", "SYSTEM", "", "NoRunID", "Kein aktueller Run_ID gefunden.")
            return

        processed = 0
        errors = 0
        update_requests = []

        rename_result_col = sheet_mgr.DEDUPE_COL.get("rename_result", 17)

        def _col_letter(n: int) -> str:
            """Convert 0-based column index to Sheets A1 column letter (handles AA, AB, …)."""
            res = ""
            while n >= 0:
                res = chr(ord("A") + (n % 26)) + res
                n = (n // 26) - 1
            return res

        col_letter = _col_letter(rename_result_col)

        for row_idx, row in sheet_mgr.read_rows_chunked_with_row_numbers("Dedupe_Report", chunk_size=1000):
            if len(row) < len(sheet_mgr.headers["Dedupe_Report"]) - 1 or row[0] == "run_utc":
                continue
            if row[sheet_mgr.DEDUPE_COL["run_id"]] != current_run_id:
                continue

            # RISK-3 fix: idempotency guard — skip rows already successfully renamed
            existing_rename_result = row[rename_result_col] if len(row) > rename_result_col else ""
            if existing_rename_result == "SUCCESS":
                continue

            file_id = row[sheet_mgr.DEDUPE_COL["file_id"]]
            current_name = row[sheet_mgr.DEDUPE_COL["name"]]
            suggested_name = row[sheet_mgr.DEDUPE_COL["suggested_name"]]

            if suggested_name and suggested_name != current_name:
                result_val = None
                try:
                    params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}
                    def _update_name():
                        return drive_service.files().update(
                            fileId=file_id,
                            body={"name": suggested_name},
                            **params
                        ).execute()
                    drive_mgr.execute_with_backoff(_update_name)
                    result_val = "SUCCESS"
                    processed += 1
                except Exception as e:
                    errors += 1
                    result_val = f"FAILED: {str(e)[:80]}"
                    state.log_error("RENAME", file_id, current_name, "UpdateError", str(e))

                update_requests.append({
                    "range": f"Dedupe_Report!{col_letter}{row_idx}",
                    "values": [[result_val]]
                })

                # Flush periodically to bound memory
                if len(update_requests) >= 50:
                    def _batch():
                        return sheets_service.spreadsheets().values().batchUpdate(
                            spreadsheetId=CONTROL_SHEET_ID,
                            body={"valueInputOption": "RAW", "data": update_requests}
                        ).execute()
                    sheet_mgr._execute_with_backoff(_batch())
                    update_requests = []

        if update_requests:
            def _batch_final():
                return sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=CONTROL_SHEET_ID,
                    body={"valueInputOption": "RAW", "data": update_requests}
                ).execute()
            sheet_mgr._execute_with_backoff(_batch_final())

        state.log_run("RENAME", "SUCCESS", processed, errors)

    finally:
        state.set_val("current_phase", "IDLE")
        state.flush_state()
        state.release_job_lock("apply_renames")

if __name__ == "__main__":
    run_apply_renames()
