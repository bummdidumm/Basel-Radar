from datetime import datetime, timezone
import os
from typing import Dict, List, Optional, Any
from .sheets_helpers import SheetManager
from .models import FileRecord
from shared.log import get_logger as _get_logger
_log = _get_logger("state", phase="SHARED")

class StateTracker:
    def __init__(self, sheets_manager: SheetManager):
        self.sheets = sheets_manager
        self.run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        self._state_cache: dict[str, str] = {}
        self._known_hashes: Optional[Dict[str, dict[str, Any]]] = None
        self._dirty = False

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
            self.flush_state()

    def _load_state(self):
        rows = self.sheets.read_all_rows("State", "A:B")
        for row in rows:
            if len(row) >= 2 and row[0] != "key":
                self._state_cache[row[0]] = row[1]

    def get_val(self, key: str) -> Optional[str]:
        return self._state_cache.get(key)

    def set_val(self, key: str, value: str):
        self._state_cache[key] = str(value) if value is not None else ""
        self._dirty = True

    def flush_state(self):
        if not self._dirty:
            return

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
            self._dirty = False
        except Exception as e:
            _log.error("State flush fehlgeschlagen", extra={"error": str(e)})
            raise e

    def compact_hash_index(self):
        COMPACT_THRESHOLD = int(os.environ.get("HASH_INDEX_COMPACT_THRESHOLD", "50000"))
        known = self.load_known_hashes()
        if len(known) < COMPACT_THRESHOLD:
            return
        _log.info("Hash_Index Kompaktierung gestartet", extra={"entries": len(known)})
        rows = [["sha256","file_id","name","parent_ids_sorted","path_display","updated_at","size_bytes","md5","effective_mime_type"]]
        for fid, meta in known.items():
            rows.append([meta.get("sha",""), fid, meta.get("name",""), meta.get("parent_ids_sorted",""),
                         meta.get("path_display",""), meta.get("updated_at",""), meta.get("size_bytes",""),
                         meta.get("md5",""), meta.get("effective_mime_type","")])
        self.sheets._execute_with_backoff(
            self.sheets.sheets.spreadsheets().values().update(
                spreadsheetId=self.sheets.spreadsheet_id,
                range="Hash_Index!A1", valueInputOption="RAW", body={"values": rows}
            )
        )
        _log.info("Hash_Index kompaktiert", extra={"entries": len(known)})

    def compact_reports(self):
        """Compact Run_Log, Error_Report and Dedupe_Report by retaining only the most recent rows."""
        RUN_LOG_MAX = int(os.environ.get("RUN_LOG_COMPACT_MAX", "500"))
        ERROR_REPORT_MAX = int(os.environ.get("ERROR_REPORT_COMPACT_MAX", "500"))
        # Dedupe_Report grows with every run and has no upper bound — compact it
        # proactively to avoid hitting the Google Sheets 10M-cell limit.
        # Default of 2000 rows covers ~100 runs at 20 files/run with room to spare.
        DEDUPE_REPORT_MAX = int(os.environ.get("DEDUPE_REPORT_COMPACT_MAX", "2000"))

        for sheet_name, max_rows, col_range in [
            ("Run_Log", RUN_LOG_MAX, "A:F"),
            ("Error_Report", ERROR_REPORT_MAX, "A:G"),
            ("Dedupe_Report", DEDUPE_REPORT_MAX, "A:Q"),
        ]:
            rows = self.sheets.read_all_rows(sheet_name, col_range)
            if len(rows) <= max_rows + 1:  # +1 for header
                continue
            header = rows[0] if rows else []
            keep = rows[1:][-max_rows:]
            compacted = ([header] if header else []) + keep
            _log.info(f"{sheet_name} Kompaktierung gestartet",
                      extra={"before": len(rows), "after": len(compacted)})
            # Clear first to avoid stale trailing rows, then rewrite
            self.sheets._execute_with_backoff(
                self.sheets.sheets.spreadsheets().values().clear(
                    spreadsheetId=self.sheets.spreadsheet_id,
                    range=f"{sheet_name}!{col_range}",
                    body={}
                )
            )
            self.sheets._execute_with_backoff(
                self.sheets.sheets.spreadsheets().values().update(
                    spreadsheetId=self.sheets.spreadsheet_id,
                    range=f"{sheet_name}!A1",
                    valueInputOption="RAW",
                    body={"values": compacted}
                )
            )
            _log.info(f"{sheet_name} kompaktiert", extra={"kept": len(keep)})

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
        valid_statuses = ("ORIGINAL", "ORIGINAL_RESUMED", "UNCHANGED_CONTENT", "SKIPPED_SIZE")
        for r in new_records:

            if r.sha256 and r.status.startswith(valid_statuses):
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

        # Enforce limits (primitive sliding window retention)
        # Assuming maximum of ~10k items per run, appending is usually safe.
        # For actual deletion logic, it's better placed in a cleanup run, but we will wrap this defensively.
        try:
            self.sheets.append_rows("Dedupe_Report", rows)
        except Exception as e:
            _log.error("Dedupe_Report append fehlgeschlagen", extra={"error": str(e)})
            raise e

    def flush_duplicate_groups(self, groups_accumulator: Dict[str, Dict]):
        """
        Duplicate_Groups: sha256, original_file_id, duplicate_file_ids, count
        Nimmt das lokale Dict {sha: {"original": id, "duplicates": set(ids)}}
        und batched das Sheet Update, um O(n) API Read/Writes pro Duplikat zu vermeiden.
        """
        if not groups_accumulator:
            return

        try:
            # 1. Read existing rows once
            rows = self.sheets.read_all_rows("Duplicate_Groups", "A:D")

            # 2. Build index of existing shas to row_index (1-based)
            existing_index: dict[str, dict[str, Any]] = {}
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
            _log.error("Duplicate_Groups flush fehlgeschlagen", extra={"error": str(e)})
            raise e
