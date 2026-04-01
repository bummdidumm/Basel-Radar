import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from .sheets_helpers import SheetManager
from .models import FileRecord

class StateTracker:
    def __init__(self, sheets_manager: SheetManager):
        self.sheets = sheets_manager
        self.run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        self._state_cache = {}
        self._known_hashes = None

        self.sheets.initialize_headers()
        self._load_state()

        # Resume-Verhalten absichern:
        # Falls wir uns noch in einem laufenden Lauf befinden, behalten wir die run_id,
        # anstatt einen neuen Report-Block anzufangen.
        current_phase = self._state_cache.get("current_phase", "IDLE")
        saved_run_id = self._state_cache.get("run_id")
        if current_phase in ["DELTA_FETCH", "INITIAL_SCAN"] and saved_run_id:
            self.run_id = saved_run_id
        else:
            # Speichere die neue run_id
            self.set_val("run_id", self.run_id)

    def _load_state(self):
        rows = self.sheets.read_all_rows("State", "A:B")
        for row in rows:
            if len(row) >= 2 and row[0] != "key":
                self._state_cache[row[0]] = row[1]

    def get_val(self, key: str) -> Optional[str]:
        return self._state_cache.get(key)

    def set_val(self, key: str, value: str):
        self._state_cache[key] = str(value) if value is not None else ""

        # Flush State Sheet
        rows = [["key", "value"]]
        for k, v in self._state_cache.items():
            rows.append([k, v])

        try:
            self.sheets.sheets.spreadsheets().values().update(
                spreadsheetId=self.sheets.spreadsheet_id,
                range="State!A1:B",
                valueInputOption="RAW",
                body={"values": rows}
            ).execute()
        except Exception as e:
            print(f"Failed to save state to sheet: {e}")

    def load_known_hashes(self) -> Dict[str, dict]:
        """Liest den Hash_Index vollständig aus und liefert ein Dictionary {file_id: {vollständiges Schema}}."""
        if self._known_hashes is not None:
            return self._known_hashes

        self._known_hashes = {}
        rows = self.sheets.read_all_rows("Hash_Index", "A:I")
        for row in rows:
            if len(row) >= 9 and row[0] != "sha256":
                sha = row[0]
                fid = row[1]
                name = row[2]
                parent_ids_sorted = row[3]
                path_display = row[4]
                updated_at = row[5]
                size_bytes = row[6]
                md5 = row[7]
                eff_mime = row[8]

                self._known_hashes[fid] = {
                    "sha": sha,
                    "name": name,
                    "parent_ids_sorted": parent_ids_sorted,
                    "path_display": path_display,
                    "updated_at": updated_at,
                    "size_bytes": size_bytes,
                    "md5": md5,
                    "effective_mime_type": eff_mime
                }
        return self._known_hashes

    def append_new_hashes(self, new_records: List[FileRecord]):
        rows = []
        for r in new_records:
            valid_statuses = ["ORIGINAL", "ORIGINAL_RESUMED", "UNCHANGED_CONTENT", "SKIPPED_SIZE"]

            if r.sha256 and any(r.status.startswith(s) for s in valid_statuses):
                # Hash_Index: sha256, file_id, name, parent_ids_sorted, path_display, updated_at, size_bytes, md5, effective_mime_type
                rows.append([
                    r.sha256, r.file_id, r.name, r.parent_ids_sorted, r.path_display,
                    r.updated_at, r.size_bytes, r.md5, r.effective_mime_type
                ])

                if self._known_hashes is not None:
                    self._known_hashes[r.file_id] = {
                        "sha": r.sha256,
                        "name": r.name,
                        "parent_ids_sorted": r.parent_ids_sorted,
                        "path_display": r.path_display,
                        "updated_at": r.updated_at,
                        "size_bytes": r.size_bytes,
                        "md5": r.md5,
                        "effective_mime_type": r.effective_mime_type
                    }
        self.sheets.append_rows("Hash_Index", rows)

    def log_run(self, phase: str, status: str, processed: int, errors: int):
        utc = datetime.now(timezone.utc).isoformat()
        # Run_Log: run_utc, run_id, phase, status, files_processed, errors
        self.sheets.append_rows("Run_Log", [[utc, self.run_id, phase, status, processed, errors]])

    def log_error(self, phase: str, file_id: str, path: str, err_type: str, msg: str):
        utc = datetime.now(timezone.utc).isoformat()
        # Error_Report: run_utc, run_id, phase, file_id, path, error_type, error_message
        self.sheets.append_rows("Error_Report", [[utc, self.run_id, phase, file_id, path, err_type, msg[:500]]])

    def append_dedupe_reports(self, records: List[FileRecord]):
        rows = []
        utc = datetime.now(timezone.utc).isoformat()
        for r in records:
            # Dedupe_Report: run_utc, run_id, path, name, file_id, mime_type, effective_mime_type, size_bytes, md5, sha256, status, change_type, duplicate_of, archive_result, suggested_name, web_link, notes
            rows.append([
                utc, self.run_id, r.path_display, r.name, r.file_id, r.mime_type, r.effective_mime_type,
                r.size_bytes, r.md5, r.sha256, r.status, r.change_type, r.duplicate_of,
                r.archive_result, r.suggested_name, r.web_link, r.notes
            ])
        self.sheets.append_rows("Dedupe_Report", rows)

    def flush_duplicate_groups(self, groups_accumulator: Dict[str, Dict]):
        """
        Duplicate_Groups: sha256, original_file_id, duplicate_file_ids, count
        Nimmt das lokale Dict {sha: {"original": id, "duplicates": set(ids)}}
        und batched das Sheet Update, um O(n) API Read/Writes pro Duplikat zu vermeiden.
        """
        if not groups_accumulator: return

        try:
            # 1. Read existing rows once
            rows = self.sheets.read_all_rows("Duplicate_Groups", "A:D")

            # 2. Build index of existing shas to row_index (1-based)
            existing_index = {}
            for i, row in enumerate(rows):
                if len(row) >= 3:
                    existing_index[row[0]] = {
                        "row_idx": i + 1,
                        "original": row[1],
                        "dups": set(row[2].split(",") if row[2] else [])
                    }

            updates = []
            appends = []

            # 3. Merge locally
            for sha, data in groups_accumulator.items():
                if sha in existing_index:
                    merged_dups = existing_index[sha]["dups"].union(data["duplicates"])
                    dup_str = ",".join(merged_dups)
                    count = len(merged_dups)
                    row_idx = existing_index[sha]["row_idx"]
                    updates.append({
                        "range": f"Duplicate_Groups!A{row_idx}:D{row_idx}",
                        "values": [[sha, existing_index[sha]["original"], dup_str, count]]
                    })
                else:
                    dup_str = ",".join(data["duplicates"])
                    count = len(data["duplicates"])
                    appends.append([sha, data["original"], dup_str, count])

            # 4. Batch Execute
            if updates:
                body = {
                    "valueInputOption": "RAW",
                    "data": updates
                }
                self.sheets._execute_with_backoff(
                    self.sheets.sheets.spreadsheets().values().batchUpdate(
                        spreadsheetId=self.sheets.spreadsheet_id,
                        body=body
                    )
                )

            if appends:
                self.sheets.append_rows("Duplicate_Groups", appends)

        except Exception as e:
            print(f"Error flushing Duplicate_Groups: {e}")
