import os
from datetime import datetime, timezone
import google.auth
from googleapiclient.discovery import build

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker

CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"

def run_apply_sort():
    print("Starte Apply Mode: Führe sichere Sortiervorschläge aus")
    if not CONTROL_SHEET_ID:
        raise ValueError("Missing CONTROL_SHEET_ID")

    credentials, _ = google.auth.default()
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)

    state.set_val("current_phase", "APPLY_SORT")

    # Lese die Sorting_Suggestions chunkweise ein
    current_run_id = state.get_val("last_successful_run_id")

    if not current_run_id:
        state.log_error("APPLY_SORT", "SYSTEM", "", "NoRunID", "Kein aktueller Run_ID gefunden.")
        return

    processed = 0
    errors = 0
    row_idx = 0 # Paging Pointer. Der erste Header (falls A1) hebt ihn auf 1, die erste Datenzeile auf 2.

    for chunk_rows in sheet_mgr.read_rows_chunked("Sorting_Suggestions", chunk_size=1000):
        for row in chunk_rows:
            row_idx += 1
            # Schema: run_id, file_id, name, mime_type, current_location, current_parent_id, suggested_target_folder, suggested_target_folder_id, target_path, rule_reason, action_mode, move_result
            if len(row) < 12 or row[0] == "run_id": continue
            if row[0] != current_run_id: continue

            file_id = row[1]
            current_name = row[2]
            target_folder_id = row[7]
            action_mode = row[10]
            move_result = row[11]

            if action_mode == "SAFE" and target_folder_id and move_result == "PENDING":
                try:
                    params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

                    file_meta = drive_service.files().get(
                        fileId=file_id, fields="parents", **params
                    ).execute()
                    previous_parents = ",".join(file_meta.get("parents", []))

                    drive_service.files().update(
                        fileId=file_id,
                        addParents=target_folder_id,
                        removeParents=previous_parents,
                        **params
                    ).execute()

                    processed += 1

                    # Update das Move Result im Sheet
                    sheet_mgr._execute_with_backoff(
                        sheets_service.spreadsheets().values().update(
                            spreadsheetId=CONTROL_SHEET_ID,
                            range=f"Sorting_Suggestions!L{row_idx}",
                            valueInputOption="RAW",
                            body={"values": [["SUCCESS"]]}
                        )
                    )

                except Exception as e:
                    errors += 1
                    state.log_error("APPLY_SORT", file_id, current_name, "MoveError", str(e))
                    sheet_mgr._execute_with_backoff(
                        sheets_service.spreadsheets().values().update(
                            spreadsheetId=CONTROL_SHEET_ID,
                            range=f"Sorting_Suggestions!L{row_idx}",
                            valueInputOption="RAW",
                            body={"values": [[f"FAILED: {str(e)[:50]}"]]}
                        )
                    )

    state.log_run("APPLY_SORT", "SUCCESS", processed, errors)
    state.set_val("current_phase", "IDLE")
    print(f"Apply Sort beendet. {processed} Dateien verschoben.")

if __name__ == "__main__":
    run_apply_sort()
