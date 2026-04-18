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

    # BUG-K: errors tracks row-level failures caught by the inner except; _failed
    # tracks outer exceptions.  Both cause APPLY_SORT_FAILED in the finally block.
    errors = 0
    _failed = False
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
                result_val = None
                try:
                    params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

                    # Stale-suggestion guard: fetch current Drive state before any
                    # destructive action so we never blindly repeat a completed move
                    # or act on a suggestion whose source state no longer matches.
                    def _fetch_live():
                        return drive_service.files().get(
                            fileId=file_id, fields="id,parents,trashed", **params
                        ).execute()
                    live = drive_mgr.execute_with_backoff(_fetch_live)
                    live_parents = live.get("parents", [])
                    is_trashed = live.get("trashed", False)

                    if action_mode == "SWEEP_TRASH":
                        if is_trashed:
                            result_val = "SUCCESS_ALREADY_TRASHED"
                            processed += 1
                        else:
                            def _trash():
                                return drive_service.files().update(
                                    fileId=file_id,
                                    body={"trashed": True},
                                    **params
                                ).execute()
                            drive_mgr.execute_with_backoff(_trash)
                            result_val = "SUCCESS_TRASHED"
                            processed += 1
                    else:
                        if target_folder_id in live_parents:
                            result_val = "SUCCESS_ALREADY_IN_TARGET"
                            processed += 1
                        else:
                            expected_parent_id = (
                                row[sheet_mgr.SORT_COL["current_parent_id"]]
                                if len(row) > sheet_mgr.SORT_COL["current_parent_id"]
                                else ""
                            )
                            if expected_parent_id and expected_parent_id not in live_parents:
                                result_val = "STALE_SOURCE_STATE"
                                state.log_error(
                                    "APPLY_SORT", file_id, current_name, "StaleSuggestion",
                                    f"Expected parent {expected_parent_id!r} not in "
                                    f"current parents {live_parents}"
                                )
                            else:
                                def _move_file():
                                    meta = drive_service.files().get(
                                        fileId=file_id, fields="parents", **params
                                    ).execute()
                                    prev = ",".join(meta.get("parents", []))
                                    return drive_service.files().update(
                                        fileId=file_id,
                                        addParents=target_folder_id,
                                        removeParents=prev,
                                        **params
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

                # BUG-E fix: use sheet_mgr._execute_with_backoff for Sheets batch writes
                # so that transient Sheets 403 (rateLimitExceeded/userRateLimitExceeded/
                # quotaExceeded) is retried — drive_mgr.execute_with_backoff only retries
                # 429/500/503 and misses Sheets-specific 403 quota errors.
                if len(update_requests) >= 50:
                    _batch = update_requests
                    sheet_mgr._execute_with_backoff(
                        sheets_service.spreadsheets().values().batchUpdate(
                            spreadsheetId=CONTROL_SHEET_ID,
                            body={"valueInputOption": "RAW", "data": _batch}
                        )
                    )
                    update_requests = []

        if update_requests:
            _batch = update_requests
            sheet_mgr._execute_with_backoff(
                sheets_service.spreadsheets().values().batchUpdate(
                    spreadsheetId=CONTROL_SHEET_ID,
                    body={"valueInputOption": "RAW", "data": _batch}
                )
            )

        state.log_run("APPLY_SORT", "SUCCESS", processed, errors)
        log.info("Apply Sort beendet", extra={"processed": processed, "errors": errors})

    except Exception:
        _failed = True
        raise
    finally:
        state.set_val("current_phase", "APPLY_SORT_FAILED" if (_failed or errors > 0) else "IDLE")
        try:
            state.flush_state()
        finally:
            state.release_job_lock("apply_sort")


if __name__ == "__main__":
    run_apply_sort()
