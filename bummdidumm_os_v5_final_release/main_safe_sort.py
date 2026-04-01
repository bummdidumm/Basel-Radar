import os
import json
from datetime import datetime, timezone

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

    # 1. Lese die Folder Registry vollständig (A:E)
    folder_registry_rows = sheet_mgr.read_all_rows("Folder_Registry", "A:E")
    folder_ids = {}
    for row in folder_registry_rows:
        # Schema: folder_key, folder_name, folder_id, parent_folder_id, full_path
        if len(row) >= 3 and row[0] != "folder_key":
            folder_ids[row[0]] = row[2]

    if not folder_ids:
        state.log_error("SAFE_SORT", "SYSTEM", "", "NoRegistry", "Folder_Registry ist leer. Bitte zuerst 'Ordnerstruktur initialisieren' ausführen.")
        return

    sorter = SortingRules(folder_ids)

    # 2. Lese den letzten Report (Chunked für OOM Protection)
    current_run_id = state.get_val("last_successful_run_id")

    if not current_run_id:
        state.log_error("SAFE_SORT", "SYSTEM", "", "NoRunID", "Kein erfolgreicher Pass 1 gefunden.")
        return

    suggestions = []
    processed = 0
    errors = 0

    for chunk_rows in sheet_mgr.read_rows_chunked("Dedupe_Report", chunk_size=1000):
        for row in chunk_rows:
            if len(row) < 11 or row[0] == "run_utc": continue
            if row[1] != current_run_id: continue # Nur den letzten Run bearbeiten

            file_id = row[4]
            name = row[3]
            mime_type = row[5]
            status = row[10]
            path = row[2]

            meta = {
                "name": name,
                "mime_type": mime_type,
                "status": status,
                "path": path
            }

            # Prioritäten anwenden
            target_name, target_id, rule_reason = sorter.determine_target(meta)

            if not target_id:
                errors += 1
                rule_reason = "FEHLER: Zielordner-ID nicht gefunden (" + target_name + ")"

            # Wir lösen "UNKNOWN_PARENT" auf, indem wir den echten Parent aus dem State Cache / Hash Index abfragen
            # Hash_Index liefert parent_ids_sorted. Wenn wir das haben, nutzen wir es, ansonsten N/A.
            known = state.load_known_hashes()
            current_parent_id = known.get(file_id, {}).get("parent_ids_sorted", "N/A")
            target_path = f"/{target_name}"

            suggestions.append([
                current_run_id, file_id, name, mime_type, path, current_parent_id, target_name, target_id, target_path, rule_reason, "SAFE", "PENDING"
            ])
            processed += 1

        # Write suggestions back in chunks
        if suggestions:
            sheet_mgr.append_rows("Sorting_Suggestions", suggestions)
            suggestions = []

    state.log_run("SAFE_SORT", "SUCCESS", processed, errors)
    print(f"Safe Sort beendet. {processed} Vorschläge generiert.")

if __name__ == "__main__":
    run_safe_sort()
