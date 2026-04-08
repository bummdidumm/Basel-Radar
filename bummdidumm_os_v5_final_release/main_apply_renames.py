import os
from shared.oauth_user_credentials import get_user_credentials
from googleapiclient.discovery import build

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker

CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"

def run_apply_renames():
    print("Starte Rename Job: Wende vorgeschlagene Namen an")
    if not CONTROL_SHEET_ID:
        raise ValueError("Missing CONTROL_SHEET_ID")

    credentials = get_user_credentials()
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    from shared.drive_helpers import DriveManager
    drive_mgr = DriveManager(drive_service, "")

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)

    state.set_val("current_phase", "APPLY_RENAMES")

    current_run_id = state.get_val("last_successful_run_id")

    if not current_run_id:
        state.log_error("RENAME", "SYSTEM", "", "NoRunID", "Kein aktueller Run_ID gefunden.")
        return

    processed = 0
    errors = 0

    for chunk in sheet_mgr.read_rows_chunked("Dedupe_Report", chunk_size=1000):
        for row in chunk:
            if len(row) < len(sheet_mgr.headers["Dedupe_Report"]) or row[0] == "run_utc":
                continue
            if row[sheet_mgr.DEDUPE_COL["run_id"]] != current_run_id:
                continue

            file_id = row[sheet_mgr.DEDUPE_COL["file_id"]]
            current_name = row[sheet_mgr.DEDUPE_COL["name"]]
            suggested_name = row[sheet_mgr.DEDUPE_COL["suggested_name"]]

            if suggested_name and suggested_name != current_name:
                try:
                    params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}
                    def _update_name():
                        return drive_service.files().update(
                            fileId=file_id,
                            body={"name": suggested_name},
                            **params
                        ).execute()
                    drive_mgr.execute_with_backoff(_update_name)
                    processed += 1
                except Exception as e:
                    errors += 1
                    state.log_error("RENAME", file_id, current_name, "UpdateError", str(e))

    state.log_run("RENAME", "SUCCESS", processed, errors)
    state.set_val("current_phase", "IDLE")

if __name__ == "__main__":
    run_apply_renames()
