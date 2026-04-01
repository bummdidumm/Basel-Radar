import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from .sheets_helpers import SheetManager
from .models import FileRecord

class StateTracker:
    def __init__(self, sheets_manager: SheetManager):
        self.sheets = sheets_manager
        self.run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

        # State key-value cache
        self._state_cache = {}
        self._known_hashes = None
        self._known_file_ids = None

        # Initialization
        self.sheets.initialize_headers()
        self._load_state()

    def _load_state(self):
        rows = self.sheets.read_all_rows("State", "A:B")
        for row in rows:
            if len(row) >= 2 and row[0] != "key":
                self._state_cache[row[0]] = row[1]

    def get_val(self, key: str) -> Optional[str]:
        return self._state_cache.get(key)

    def set_val(self, key: str, value: str):
        self._state_cache[key] = value

        # Flush State Sheet
        rows = [["key", "value"]]
        for k, v in self._state_cache.items():
            rows.append([k, v])

        self.sheets.sheets.spreadsheets().values().update(
            spreadsheetId=self.sheets.spreadsheet_id,
            range="State!A1:B",
            valueInputOption="RAW",
            body={"values": rows}
        ).execute()

    def load_known_hashes(self) -> Dict[str, str]:
        if self._known_hashes is not None:
            return self._known_hashes

        self._known_hashes = {}
        self._known_file_ids = {}

        rows = self.sheets.read_all_rows("Hash_Index", "A:C") # sha256, file_id, name
        for row in rows:
            if len(row) >= 2 and row[0] != "sha256":
                sha = row[0]
                fid = row[1]
                self._known_hashes[sha] = fid
                self._known_file_ids[fid] = sha
        return self._known_hashes

    def append_new_hashes(self, new_records: List[FileRecord]):
        rows = []
        for r in new_records:
            if r.sha256 and r.status == "ORIGINAL":
                # Hash_Index: sha256, file_id, name, path, updated_at, size_bytes, md5, effective_mime_type
                rows.append([r.sha256, r.file_id, r.name, r.path, r.updated_at, r.size_bytes, r.md5, r.effective_mime_type])

                if self._known_hashes is not None:
                    self._known_hashes[r.sha256] = r.file_id
                    self._known_file_ids[r.file_id] = r.sha256
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
            # Dedupe_Report schema
            rows.append([
                utc, self.run_id, r.path, r.name, r.file_id, r.mime_type, r.effective_mime_type,
                r.size_bytes, r.md5, r.sha256, r.status, r.change_type, r.duplicate_of,
                r.archive_result, r.suggested_name, r.web_link, r.notes
            ])
        self.sheets.append_rows("Dedupe_Report", rows)

    def append_duplicate_group(self, sha: str, original_id: str, duplicate_id: str):
        # We append a simple log here. A true grouped view requires reading existing groups and updating the count/array
        # For simplicity in this job, we append duplicates as they are found.
        # Format: sha256, original_file_id, duplicate_file_ids, count
        self.sheets.append_rows("Duplicate_Groups", [[sha, original_id, duplicate_id, 1]])
