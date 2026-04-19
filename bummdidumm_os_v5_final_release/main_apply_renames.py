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

    # BUG-K: errors tracks row-level failures caught by the inner except; _failed
    # tracks outer exceptions.  Both cause APPLY_RENAMES_FAILED in the finally block.
    errors = 0
    _failed = False
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

            # Skip already-handled rows (success or known stale/guard outcomes)
            existing_rename_result = row[rename_result_col] if len(row) > rename_result_col else ""
            if existing_rename_result in ("SUCCESS", "SUCCESS_ALREADY_RENAMED", "STALE_NAME_MISMATCH"):
                continue

            file_id = row[sheet_mgr.DEDUPE_COL["file_id"]]
            current_name = row[sheet_mgr.DEDUPE_COL["name"]]
            suggested_name = row[sheet_mgr.DEDUPE_COL["suggested_name"]]

            if suggested_name and suggested_name != current_name:
                result_val = None
                try:
                    params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

                    # Stale-suggestion guard: verify actual Drive name before renaming
                    # so we never blindly overwrite an external change.
                    live = drive_mgr.execute_with_backoff(
                        lambda: drive_service.files().get(
                            fileId=file_id, fields="id,name", **params
                        ).execute()
                    )
                    live_name = live.get("name", "")

                    if live_name == suggested_name:
                        result_val = "SUCCESS_ALREADY_RENAMED"
                        processed += 1
                    elif live_name != current_name:
                        result_val = "STALE_NAME_MISMATCH"
                        state.log_error(
                            "RENAME", file_id, current_name, "StaleSuggestion",
                            f"Expected name {current_name!r} but Drive has {live_name!r}"
                        )
                    else:
                        drive_mgr.execute_with_backoff(
                            lambda: drive_service.files().update(
                                fileId=file_id,
                                body={"name": suggested_name},
                                **params
                            ).execute()
                        )
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

                # BUG-E fix: batch Sheets writes use sheet_mgr._execute_with_backoff, which
                # retries 403 rateLimitExceeded/userRateLimitExceeded/quotaExceeded in
                # addition to 429/500/503 — drive_mgr.execute_with_backoff misses 403 quota.
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

        state.log_run("RENAME", "SUCCESS", processed, errors)

    except Exception:
        _failed = True
        raise
    finally:
        state.set_val("current_phase", "APPLY_RENAMES_FAILED" if (_failed or errors > 0) else "IDLE")
        try:
            state.flush_state()
        finally:
            state.release_job_lock("apply_renames")

if __name__ == "__main__":
    run_apply_renames()
