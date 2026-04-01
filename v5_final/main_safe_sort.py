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

    # 1. Lese die Folder Registry
    folder_registry_rows = sheet_mgr.read_all_rows("Folder_Registry", "A:C")
    folder_ids = {}
    for row in folder_registry_rows:
        if len(row) >= 3 and row[0] != "folder_key":
            # folder_key (z.B. "50a_fotos") -> folder_id
            folder_ids[row[0]] = row[2]

    if not folder_ids:
        state.log_error("SAFE_SORT", "SYSTEM", "", "NoRegistry", "Folder_Registry ist leer. Bitte zuerst 'Ordnerstruktur initialisieren' ausführen.")
        return

    sorter = SortingRules(folder_ids)

    # 1. Lese den letzten Report
    rows = sheet_mgr.read_all_rows("Dedupe_Report")
    current_run_id = state.get_val("last_successful_run_id")

    if not current_run_id:
        state.log_error("SAFE_SORT", "SYSTEM", "", "NoRunID", "Kein erfolgreicher Pass 1 gefunden.")
        return

    suggestions = []
    processed = 0
    errors = 0

    for row in rows:
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

        # Helper: Falls die Datei aktuell im Root oder in Inbox liegt, haben wir eine current_parent_id,
        # wir lesen sie hier vereinfacht als den "path". Bei Bedarf kann das genauer über die Metadaten gelöst werden.
        # "Sorting_Suggestions": ["run_id", "file_id", "name", "mime_type", "current_location", "current_parent_id", "suggested_target_folder", "suggested_target_folder_id", "target_path", "rule_reason", "action_mode", "move_result"]
        current_parent_id = "UNKNOWN_PARENT"
        target_path = f"/{target_name}"
        suggestions.append([
            current_run_id, file_id, name, mime_type, path, current_parent_id, target_name, target_id, target_path, rule_reason, "SAFE", "PENDING"
        ])
        processed += 1

    if suggestions:
        sheet_mgr.append_rows("Sorting_Suggestions", suggestions)

    state.log_run("SAFE_SORT", "SUCCESS", processed, errors)
    print(f"Safe Sort beendet. {processed} Vorschläge generiert.")

if __name__ == "__main__":
    run_safe_sort()
