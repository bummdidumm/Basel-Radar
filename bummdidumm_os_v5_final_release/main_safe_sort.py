import os

import google.auth
from googleapiclient.discovery import build

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker
from shared.sorting_helpers import SortingRules

CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")


def run_safe_sort():
    print("Starte Safe Mode: Generiere Sortier-Vorschläge")
    if not CONTROL_SHEET_ID:
        raise ValueError("Missing CONTROL_SHEET_ID")

    credentials, _ = google.auth.default()
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)

    folder_registry_rows = sheet_mgr.read_all_rows("Folder_Registry", "A:E")
    folder_registry = {}
    for row in folder_registry_rows:
        if len(row) >= 5 and row[0] != "folder_key":
            folder_registry[row[0]] = {
                "folder_name": row[1],
                "folder_id": row[2],
                "parent_folder_id": row[3],
                "full_path": row[4],
            }

    if not folder_registry:
        state.log_error("SAFE_SORT", "SYSTEM", "", "NoRegistry", "Folder_Registry ist leer. Bitte zuerst 'Ordnerstruktur initialisieren' ausführen.")
        return

    sorter = SortingRules(folder_registry)
    current_run_id = state.get_val("last_successful_run_id")
    if not current_run_id:
        state.log_error("SAFE_SORT", "SYSTEM", "", "NoRunID", "Kein erfolgreicher Pass 1 gefunden.")
        return

    known = state.load_known_hashes()
    suggestions = []
    processed = 0
    errors = 0

    for chunk_rows in sheet_mgr.read_rows_chunked("Dedupe_Report", chunk_size=1000):
        for row in chunk_rows:
            if len(row) < 11 or row[0] == "run_utc" or row[1] != current_run_id:
                continue

            file_id = row[4]
            name = row[3]
            mime_type = row[5]
            status = row[10]
            current_path = row[2]

            folder_rule, folder_rule_reason, target_name, target_id, target_path = sorter.determine_target({
                "name": name,
                "mime_type": mime_type,
                "status": status,
                "path": current_path
            })

            current_parent_id = ""
            meta = known.get(file_id, {})
            if meta.get("parent_ids_sorted"):
                current_parent_id = meta["parent_ids_sorted"].split(",")[0]
            elif "/" in current_path:
                current_parent_id = current_path.split("/", 1)[0]

            if not current_parent_id:
                current_parent_id = "N/A"

            if not target_id:
                errors += 1
                folder_rule_reason = f"FEHLER: Zielordner-ID nicht gefunden ({target_name})"

            suggestions.append([
                current_run_id, file_id, name, mime_type, current_path, current_parent_id,
                folder_rule, folder_rule_reason, target_name, target_id, target_path, "SAFE", "PENDING"
            ])
            processed += 1

        if suggestions:
            sheet_mgr.append_rows("Sorting_Suggestions", suggestions)
            suggestions = []

    state.log_run("SAFE_SORT", "SUCCESS", processed, errors)
    print(f"Safe Sort beendet. {processed} Vorschläge generiert.")


if __name__ == "__main__":
    run_safe_sort()
