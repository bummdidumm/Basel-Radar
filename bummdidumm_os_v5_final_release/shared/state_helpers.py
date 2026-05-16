from datetime import datetime, timezone
import os
import time
import uuid
from typing import Dict, List, Optional, Any
from .sheets_helpers import SheetManager
from .models import FileRecord
from shared.log import get_logger as _get_logger
_log = _get_logger("state", phase="SHARED")

class StateTracker:
    def __init__(self, sheets_manager: SheetManager):
        self.sheets = sheets_manager
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        uniq = uuid.uuid4().hex[:8]
        self.run_id = f"run_{ts}_{uniq}"
        self.owner_id = f"owner_{uuid.uuid4().hex}"

        self._state_cache: dict[str, str] = {}
        self._known_hashes: Optional[Dict[str, dict[str, Any]]] = None
        self._dirty = False

        self.sheets.initialize_headers()
        self._load_state()

    def _load_state(self):
        self._state_cache = {}
        rows = self.sheets.read_all_rows("State", "A:B")
        for row in rows:
            if len(row) >= 2 and row[0] != "key":
                self._state_cache[row[0]] = row[1]

    def reload_state(self):
        self._load_state()

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
            self.sheets._execute_with_backoff(
                self.sheets.sheets.spreadsheets().values().update(
                    spreadsheetId=self.sheets.spreadsheet_id,
                    range="State!A1:B",
                    valueInputOption="RAW",
                    body={"values": rows}
                )
            )
            self._dirty = False
        except Exception as e:
            _log.error("State flush fehlgeschlagen", extra={"error": str(e)})
            raise e

    # ------------------------------------------------------------------
    # Job-level locking for downstream jobs (safe_sort, apply_sort,
    # apply_renames).  Simpler than the Pass-1 lease — no heartbeat
    # required for short-lived jobs.
    # ------------------------------------------------------------------

    def acquire_job_lock(self, job_name: str, timeout_sec: int = 600) -> bool:
        """Acquire a short-lived job-level lock stored in the State sheet.

        Returns True when the lock is successfully acquired.  Returns False if
        another instance holds a non-stale lock for the same job.

        State keys used:
          {job_name}_lock_owner  — owner_id of the lock holder
          {job_name}_lock_at     — ISO-UTC timestamp of acquisition

        A lock is stale when its age exceeds ``timeout_sec`` and may be
        taken over by any new caller.
        """
        owner_key = f"{job_name}_lock_owner"
        at_key = f"{job_name}_lock_at"

        self.reload_state()
        existing_owner = self.get_val(owner_key)
        lock_at_str = self.get_val(at_key)

        if existing_owner and existing_owner != self.owner_id:
            stale = False
            if lock_at_str:
                try:
                    lock_t = datetime.fromisoformat(lock_at_str)
                    diff = (datetime.now(timezone.utc) - lock_t).total_seconds()
                    stale = diff >= timeout_sec
                except (ValueError, TypeError):
                    stale = True  # unreadable timestamp → treat as stale
            if not stale:
                _log.warning(
                    "Job lock held by another instance — aborting",
                    extra={"job": job_name, "holder": existing_owner, "lock_at": lock_at_str},
                )
                return False

        self.set_val(owner_key, self.owner_id)
        self.set_val(at_key, datetime.now(timezone.utc).isoformat())
        self.flush_state()
        time.sleep(0.5)  # TOCTOU fence (Sheets eventual-consistency, cf. main_pass1 RISK-1)
        # Post-claim verify: reload to detect a concurrent takeover that wrote after us.
        self.reload_state()
        if self.get_val(owner_key) != self.owner_id:
            _log.warning(
                "Job lock claim lost after flush — concurrent takeover",
                extra={"job": job_name},
            )
            return False
        return True

    def release_job_lock(self, job_name: str) -> None:
        """Release a job-level lock if this instance still owns it.

        Does nothing when another instance has already taken over the lock
        (e.g. after a timeout), preventing accidental invalidation of an
        active successor's lock.
        """
        owner_key = f"{job_name}_lock_owner"
        at_key = f"{job_name}_lock_at"
        self.reload_state()
        if self.get_val(owner_key) == self.owner_id:
            self.set_val(owner_key, "")
            self.set_val(at_key, "")
            self.flush_state()

    def compact_hash_index(self):
        """Compact the Hash_Index sheet by rewriting only the unique current entries.

        Uses clear-then-chunked-write with a rollback buffer (RISK-4 pattern) so
        that a crash after clear but before the write restores the original data.
        Writes are chunked at _HASH_COMPACT_CHUNK_SIZE rows to stay within the
        Sheets API payload limit for very large indices.
        """
        _HASH_COMPACT_CHUNK_SIZE = 10_000
        COMPACT_THRESHOLD = int(os.environ.get("HASH_INDEX_COMPACT_THRESHOLD", "50000"))
        known = self.load_known_hashes()
        if len(known) < COMPACT_THRESHOLD:
            return
        _log.info("Hash_Index Kompaktierung gestartet", extra={"entries": len(known)})

        header = ["sha256","file_id","name","parent_ids_sorted","path_display","updated_at","size_bytes","md5","effective_mime_type"]
        rows = [header]
        for fid, meta in known.items():
            rows.append([meta.get("sha",""), fid, meta.get("name",""), meta.get("parent_ids_sorted",""),
                         meta.get("path_display",""), meta.get("updated_at",""), meta.get("size_bytes",""),
                         meta.get("md5",""), meta.get("effective_mime_type","")])

        # Read original rows for rollback in case update fails after clear.
        # raise_on_error=True: if this read fails we must not proceed to clear,
        # as an empty rollback buffer would leave Hash_Index wiped on any write failure.
        original_rows = self.sheets.read_all_rows("Hash_Index", "A:I", raise_on_error=True)

        self.sheets._execute_with_backoff(
            self.sheets.sheets.spreadsheets().values().clear(
                spreadsheetId=self.sheets.spreadsheet_id,
                range="Hash_Index!A:I",
                body={}
            )
        )

        try:
            for chunk_start in range(0, len(rows), _HASH_COMPACT_CHUNK_SIZE):
                chunk = rows[chunk_start:chunk_start + _HASH_COMPACT_CHUNK_SIZE]
                self.sheets._execute_with_backoff(
                    self.sheets.sheets.spreadsheets().values().update(
                        spreadsheetId=self.sheets.spreadsheet_id,
                        range=f"Hash_Index!A{chunk_start + 1}",
                        valueInputOption="RAW",
                        body={"values": chunk}
                    )
                )
        except Exception as update_exc:
            _log.error("Hash_Index Kompaktierung Update fehlgeschlagen — versuche Wiederherstellung",
                       extra={"error": str(update_exc)})
            try:
                for chunk_start in range(0, len(original_rows), _HASH_COMPACT_CHUNK_SIZE):
                    chunk = original_rows[chunk_start:chunk_start + _HASH_COMPACT_CHUNK_SIZE]
                    self.sheets._execute_with_backoff(
                        self.sheets.sheets.spreadsheets().values().update(
                            spreadsheetId=self.sheets.spreadsheet_id,
                            range=f"Hash_Index!A{chunk_start + 1}",
                            valueInputOption="RAW",
                            body={"values": chunk}
                        )
                    )
                _log.info("Hash_Index Wiederherstellung nach fehlgeschlagenem Update erfolgreich")
            except Exception as restore_exc:
                _log.error("Hash_Index Wiederherstellung fehlgeschlagen — Sheet möglicherweise leer!",
                           extra={"restore_error": str(restore_exc)})
            raise update_exc

        _log.info("Hash_Index kompaktiert", extra={"entries": len(known)})

    def compact_reports(self):
        """Compact Run_Log and Error_Report by retaining only the most recent rows."""
        RUN_LOG_MAX = int(os.environ.get("RUN_LOG_COMPACT_MAX", "500"))
        ERROR_REPORT_MAX = int(os.environ.get("ERROR_REPORT_COMPACT_MAX", "500"))

        for sheet_name, max_rows, col_range in [
            ("Run_Log", RUN_LOG_MAX, "A:F"),
            ("Error_Report", ERROR_REPORT_MAX, "A:G"),
        ]:
            rows = self.sheets.read_all_rows(sheet_name, col_range)
            if len(rows) <= max_rows + 1:  # +1 for header
                continue
            header = rows[0] if rows else []
            keep = rows[1:][-max_rows:]
            compacted = ([header] if header else []) + keep
            _log.info(f"{sheet_name} Kompaktierung gestartet",
                      extra={"before": len(rows), "after": len(compacted)})
            # RISK-4 fix: buffer locally so we can restore if update fails after clear
            buffered_compacted = list(compacted)
            original_rows = list(rows)

            self.sheets._execute_with_backoff(
                self.sheets.sheets.spreadsheets().values().clear(
                    spreadsheetId=self.sheets.spreadsheet_id,
                    range=f"{sheet_name}!{col_range}",
                    body={}
                )
            )
            # If clear succeeded but update fails, restore original data (best-effort)
            try:
                self.sheets._execute_with_backoff(
                    self.sheets.sheets.spreadsheets().values().update(
                        spreadsheetId=self.sheets.spreadsheet_id,
                        range=f"{sheet_name}!A1",
                        valueInputOption="RAW",
                        body={"values": buffered_compacted}
                    )
                )
            except Exception as update_exc:
                _log.error(
                    f"{sheet_name} Kompaktierung Update fehlgeschlagen — versuche Wiederherstellung",
                    extra={"error": str(update_exc)}
                )
                try:
                    self.sheets._execute_with_backoff(
                        self.sheets.sheets.spreadsheets().values().update(
                            spreadsheetId=self.sheets.spreadsheet_id,
                            range=f"{sheet_name}!A1",
                            valueInputOption="RAW",
                            body={"values": original_rows}
                        )
                    )
                    _log.info(f"{sheet_name} Wiederherstellung nach fehlgeschlagenem Update erfolgreich")
                except Exception as restore_exc:
                    _log.error(
                        f"{sheet_name} Wiederherstellung fehlgeschlagen — Sheet möglicherweise leer!",
                        extra={"restore_error": str(restore_exc)}
                    )
                raise update_exc
            _log.info(f"{sheet_name} kompaktiert", extra={"kept": len(keep)})

    def load_known_hashes(self) -> Dict[str, dict]:
        """Liest den Hash_Index vollständig aus und liefert ein Dictionary {file_id: {vollständiges Schema}}.

        Hash_Index is content-addressed, not lifecycle-addressed: entries accumulate
        over time and are keyed by file_id. Entries for deleted/removed files are
        intentionally preserved — they act as a content fingerprint registry so that
        re-uploaded files with the same content are correctly identified as duplicates.
        Stale entries do not cause correctness issues because delta runs re-classify
        files via change_type logic (DELETED/TRASHED/MOVED_OUT_OF_SCOPE).

        Raises on API error (raise_on_error=True) to prevent a silent empty-return
        from causing a full re-hash storm on the next run.
        """
        if self._known_hashes is not None:
            return self._known_hashes

        self._known_hashes = {}
        rows = self.sheets.read_all_rows("Hash_Index", "A:I", raise_on_error=True)
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
        """Append truly new Hash_Index entries and update the in-memory cache.

        Only ORIGINAL and ORIGINAL_RESUMED records are written to the sheet —
        these represent content seen for the first time (or resumed after a gap).
        UNCHANGED_CONTENT and SKIPPED_SIZE records still update the in-memory cache
        so subsequent batch processing has current metadata, but they are NOT
        re-appended to the sheet on every run (which caused unbounded growth).
        """
        # Statuses that are written to the Hash_Index sheet (genuinely new entries)
        _APPEND_STATUSES = ("ORIGINAL", "ORIGINAL_RESUMED")
        # Statuses that refresh the in-memory cache only (already in sheet)
        _CACHE_UPDATE_STATUSES = ("ORIGINAL", "ORIGINAL_RESUMED", "UNCHANGED_CONTENT", "SKIPPED_SIZE")

        rows = []
        for r in new_records:
            if not (r.sha256 and r.status.startswith(_CACHE_UPDATE_STATUSES)):
                continue

            # Always refresh in-memory cache to keep metadata current within a run
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

            # Only append to sheet for new/resumed originals (not already-tracked entries)
            if r.status.startswith(_APPEND_STATUSES):
                rows.append([
                    r.sha256, r.file_id, r.name, r.parent_ids_sorted, r.path_display,
                    r.updated_at, r.size_bytes, r.md5, r.effective_mime_type
                ])

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
                if len(row) >= 3 and row[0] != "sha256":  # M-2 fix: skip header row
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
