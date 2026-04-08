import os
from shared.oauth_user_credentials import get_user_credentials
from googleapiclient.discovery import build

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker

CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"


def run_apply_sort():
    print("Starte Apply Mode: Führe sichere Sortiervorschläge aus")
    if not CONTROL_SHEET_ID:
        raise ValueError("Missing CONTROL_SHEET_ID")

    credentials = get_user_credentials()
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    from shared.drive_helpers import DriveManager
    drive_mgr = DriveManager(drive_service, "")

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)

    state.set_val("current_phase", "APPLY_SORT")
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

                if action_mode == "SWEEP_TRASH":
                    # Mark explicitly as trashed
                    def _trash():
                        return drive_service.files().update(
                            fileId=file_id,
                            body={"trashed": True},
                            **params
                        ).execute()
                    drive_mgr.execute_with_backoff(_trash)
                    result_val = "SUCCESS_TRASHED"
                else:
                    def _get_parents():
                        return drive_service.files().get(fileId=file_id, fields="parents", **params).execute()
                    file_meta = drive_mgr.execute_with_backoff(_get_parents)
                    previous_parents = ",".join(file_meta.get("parents", []))

                    def _update_parents():
                        return drive_service.files().update(
                            fileId=file_id,
                            addParents=target_folder_id,
                            removeParents=previous_parents,
                            **params
                        ).execute()
                    drive_mgr.execute_with_backoff(_update_parents)
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
    state.set_val("current_phase", "IDLE")
    print(f"Apply Sort beendet. {processed} Dateien verschoben.")


if __name__ == "__main__":
    run_apply_sort()
