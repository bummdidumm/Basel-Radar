import os
from shared.oauth_user_credentials import get_user_credentials
from googleapiclient.discovery import build

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker

CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"


def run_apply_sort():
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
    log = get_logger("apply_sort", phase="APPLY_SORT")

    _lock_timeout = int(os.environ.get("APPLY_SORT_LOCK_TIMEOUT_SEC", "600"))
    if not state.acquire_job_lock("apply_sort", timeout_sec=_lock_timeout):
        log.warning("Apply Sort abgebrochen: anderer Prozess hält den Lock")
        return

    try:
        log.info("Apply Sort gestartet")
        state.set_val("current_phase", "APPLY_SORT")
        state.flush_state()
        current_run_id = state.get_val("last_successful_run_id")
        if not current_run_id:
            state.log_error("APPLY_SORT", "SYSTEM", "", "NoRunID", "Kein aktueller Run_ID gefunden.")
            return

        processed = 0
        errors = 0

        update_requests = []

        for row_idx, row in sheet_mgr.read_rows_chunked_with_row_numbers("Sorting_Suggestions", chunk_size=1000):
            if len(row) < len(sheet_mgr.headers["Sorting_Suggestions"]) or row[0] == "run_id" or row[0] != current_run_id:
                continue

            file_id = row[sheet_mgr.SORT_COL["file_id"]]
            current_name = row[sheet_mgr.SORT_COL["name"]]
            target_folder_id = row[sheet_mgr.SORT_COL["suggested_target_folder_id"]]
            action_mode = row[sheet_mgr.SORT_COL["action_mode"]]
            move_result = row[sheet_mgr.SORT_COL["move_result"]]

            if action_mode in ["SAFE", "SWEEP_TRASH"] and (target_folder_id or action_mode == "SWEEP_TRASH") and move_result == "PENDING":
                try:
                    params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

                    meta = drive_service.files().get(
                        fileId=file_id, fields="parents,trashed", **params
                    ).execute()
                    current_parents = meta.get("parents", [])
                    is_trashed = meta.get("trashed", False)

                    if action_mode == "SWEEP_TRASH":
                        if is_trashed:
                            result_val = "SUCCESS_ALREADY_TRASHED"
                        else:
                            def _trash(fid=file_id, p=params):
                                return drive_service.files().update(
                                    fileId=fid, body={"trashed": True}, **p
                                ).execute()
                            drive_mgr.execute_with_backoff(_trash)
                            result_val = "SUCCESS_TRASHED"
                    else:
                        if target_folder_id in current_parents:
                            result_val = "SUCCESS_ALREADY_IN_TARGET"
                        elif is_trashed:
                            result_val = "STALE_SOURCE_STATE"
                        else:
                            prev = ",".join(current_parents)
                            def _move_file(fid=file_id, tid=target_folder_id, rp=prev, p=params):
                                return drive_service.files().update(
                                    fileId=fid, addParents=tid, removeParents=rp, **p
                                ).execute()
                            drive_mgr.execute_with_backoff(_move_file)
                            result_val = "SUCCESS"

                    processed += 1
                except Exception as e:
                    errors += 1
                    state.log_error("APPLY_SORT", file_id, current_name, "MoveError", str(e))
                    result_val = f"FAILED: {str(e)[:80]}"

                update_requests.append({
                    "range": f"Sorting_Suggestions!M{row_idx}",
                    "values": [[result_val]]
                })

                # Flush periodically to not build up a massive array in memory,
                # but still benefit from batched update performance.
                if len(update_requests) >= 50:
                    sheet_mgr._execute_with_backoff(
                        sheets_service.spreadsheets().values().batchUpdate(
                            spreadsheetId=CONTROL_SHEET_ID,
                            body={"valueInputOption": "RAW", "data": update_requests}
                        )
                    )
                    update_requests = []

        if update_requests:
            sheet_mgr._execute_with_backoff(
                sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=CONTROL_SHEET_ID,
                    body={"valueInputOption": "RAW", "data": update_requests}
                )
            )

        state.log_run("APPLY_SORT", "SUCCESS", processed, errors)
        log.info("Apply Sort beendet", extra={"processed": processed, "errors": errors})

    finally:
        state.set_val("current_phase", "IDLE")
        try:
            state.flush_state()
        finally:
            state.release_job_lock("apply_sort")


if __name__ == "__main__":
    run_apply_sort()
