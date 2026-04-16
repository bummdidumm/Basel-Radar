import os

from shared.oauth_user_credentials import get_user_credentials
from googleapiclient.discovery import build

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker
from shared.sorting_helpers import SortingRules

CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")


def run_safe_sort():
    if not CONTROL_SHEET_ID:
        raise ValueError("Missing CONTROL_SHEET_ID")

    credentials = get_user_credentials()
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)
    from shared.log import get_logger
    log = get_logger("safe_sort", phase="SAFE_SORT")
    log.info("Safe Sort gestartet")

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
    known_file_ids = set(known.keys())

    # Load semantic hints (file_id → primary topic) for sorting decisions.
    # Prefer the compact file_topics.json written by Pass 2 writers; fall back to
    # streaming the full record index for installations that predate this file.
    from pathlib import Path
    import json
    import logging
    semantic_hints: dict[str, str] = {}
    brain_index_root = Path(os.environ.get("BRAIN_INDEX_ROOT", str(Path(__file__).parent / "brain_index")))
    if "K_SERVICE" in os.environ and not os.environ.get("BRAIN_INDEX_ROOT"):
        log.warning("BRAIN_INDEX_ROOT is not set in Cloud Run. Semantic hints will not be available.")

    hint_path = brain_index_root / "20_index" / "published" / "file_topics.json"
    if hint_path.exists():
        try:
            loaded = json.loads(hint_path.read_text(encoding="utf-8"))
            # Filter to known file_ids to keep the dict bounded.
            semantic_hints = {k: v for k, v in loaded.items() if not known_file_ids or k in known_file_ids}
        except Exception as e:
            logging.debug(f"Failed to load topic hints file: {e}")
    else:
        # Fallback: stream record index (legacy path, before hints file was generated).
        registry_path = brain_index_root / "20_index" / "published" / "01_record_index.jsonl"
        if registry_path.exists():
            try:
                with registry_path.open(encoding="utf-8") as rh:
                    for line in rh:
                        if not line.strip():
                            continue
                        try:
                            s_data = json.loads(line)
                            f_id = s_data.get("file_id")
                            if f_id and (not known_file_ids or f_id in known_file_ids):
                                topics = s_data.get("topics", [])
                                if topics:
                                    semantic_hints[f_id] = topics[0]
                        except Exception as e:
                            logging.debug(f"Failed to parse line in record index: {e}")
            except Exception as e:
                logging.debug(f"Failed to read record index for semantic hints: {e}")

    suggestions = []
    processed = 0
    errors = 0

    # DM-2 fix: load already-written suggestions for this run to prevent duplicates
    # when safe_sort is restarted mid-run (crash recovery).
    existing_suggestion_file_ids: set = set()
    for ex_row in sheet_mgr.read_all_rows("Sorting_Suggestions", "A:B"):
        if len(ex_row) >= 2 and ex_row[0] == current_run_id:
            existing_suggestion_file_ids.add(ex_row[1])

    for chunk_rows in sheet_mgr.read_rows_chunked("Dedupe_Report", chunk_size=1000):
        for row in chunk_rows:
            if len(row) < len(sheet_mgr.headers["Dedupe_Report"]) or row[0] == "run_utc" or row[1] != current_run_id:
                continue

            file_id = row[sheet_mgr.DEDUPE_COL["file_id"]]
            if file_id in existing_suggestion_file_ids:
                continue  # DM-2 fix: already suggested for this run
            name = row[sheet_mgr.DEDUPE_COL["name"]]
            mime_type = row[sheet_mgr.DEDUPE_COL["mime_type"]]
            status = row[sheet_mgr.DEDUPE_COL["status"]]
            current_path = row[sheet_mgr.DEDUPE_COL["path"]]

            current_parent_id = ""
            meta = known.get(file_id, {})
            if meta.get("parent_ids_sorted"):
                current_parent_id = meta["parent_ids_sorted"].split(",")[0]

            if not current_parent_id:
                current_parent_id = "N/A"

            notes = str(row[sheet_mgr.DEDUPE_COL["notes"]]) if row[sheet_mgr.DEDUPE_COL["notes"]] is not None else ""
            lane = "INBOX_TRASH" if "Lane: INBOX_TRASH" in notes else "ACTIVE"
            semantic_topic_hint = semantic_hints.get(file_id, "")

            folder_rule, folder_rule_reason, target_name, target_id, target_path = sorter.determine_target({
                "name": name,
                "mime_type": mime_type,
                "status": status,
                "path": current_path,
                "lane": lane,
                "current_parent_id": current_parent_id,
                "semantic_topic_hint": semantic_topic_hint,
            })

            if not target_id:
                errors += 1
                folder_rule_reason = f"FEHLER: Zielordner-ID nicht gefunden ({target_name})"

            action_mode = "SAFE"
            if folder_rule == "01_inbox_trash":
                action_mode = "SWEEP_TRASH"

            suggestions.append([
                current_run_id,
                file_id,
                name,
                mime_type,
                current_path,
                current_parent_id,
                folder_rule, folder_rule_reason, target_name, target_id, target_path, action_mode, "PENDING"
            ])
            processed += 1

        if suggestions:
            sheet_mgr.append_rows("Sorting_Suggestions", suggestions)
            suggestions = []

    state.log_run("SAFE_SORT", "SUCCESS", processed, errors)
    log.info("Safe Sort beendet", extra={"processed": processed})


if __name__ == "__main__":
    run_safe_sort()
