"""Regression tests for Hash_Index compaction and append logic.

Covers:
- BUG-A: compact_hash_index() uses clear-then-write (not update-only) to remove stale rows
- BUG-B: append_new_hashes() does NOT write UNCHANGED_CONTENT/SKIPPED_SIZE to the sheet
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from shared.state_helpers import StateTracker
from shared.models import FileRecord


def _make_tracker():
    sheets = MagicMock()
    sheets.spreadsheet_id = "sheet_id"
    sheets.sheets = MagicMock()
    tracker = StateTracker.__new__(StateTracker)
    tracker.sheets = sheets
    tracker.run_id = "run_test"
    tracker._state_cache = {}
    tracker._known_hashes = None
    tracker._dirty = False
    return tracker


def _known_dict(n):
    return {
        f"fid_{i}": {
            "sha": f"sha_{i:064x}",
            "name": f"file_{i}.pdf",
            "parent_ids_sorted": "parent1",
            "path_display": f"/p/file_{i}.pdf",
            "updated_at": "2026-01-01",
            "size_bytes": 1024,
            "md5": f"md5_{i}",
            "effective_mime_type": "application/pdf",
        }
        for i in range(n)
    }


def _make_record(file_id, status, sha256="a" * 64):
    return FileRecord(
        file_id=file_id,
        status=status,
        sha256=sha256,
        name=f"file_{file_id}.pdf",
        parent_ids_sorted="parent1",
        path_display=f"/p/{file_id}",
        updated_at="2026-01-01",
        size_bytes=1024,
        md5=f"md5_{file_id}",
        effective_mime_type="application/pdf",
    )


# ---------------------------------------------------------------------------
# BUG-A: compact_hash_index
# ---------------------------------------------------------------------------

class TestCompactHashIndex:

    def _run_compact(self, tracker, n=100):
        tracker._known_hashes = _known_dict(n)
        tracker.sheets.read_all_rows.return_value = [["sha256", "file_id"]]  # rollback buf

        call_log = []

        def make_clear(**kwargs):
            m = MagicMock()
            m._op = "clear"
            return m

        def make_update(**kwargs):
            m = MagicMock()
            m._op = "update"
            m._body = kwargs.get("body", {})
            return m

        ss = tracker.sheets.sheets.spreadsheets.return_value.values.return_value
        ss.clear.side_effect = make_clear
        ss.update.side_effect = make_update

        def recording_execute(req):
            call_log.append(getattr(req, "_op", "?"))
            return MagicMock()

        tracker.sheets._execute_with_backoff = recording_execute

        with patch.dict(os.environ, {"HASH_INDEX_COMPACT_THRESHOLD": "50"}):
            tracker.compact_hash_index()

        return call_log, ss

    def test_compact_hash_index_clear_before_write(self):
        tracker = _make_tracker()
        call_log, _ = self._run_compact(tracker)
        assert "clear" in call_log, "clear() must be called during compaction"
        assert "update" in call_log, "update() must be called during compaction"
        clear_idx = call_log.index("clear")
        update_idx = call_log.index("update")
        assert clear_idx < update_idx, "clear() must precede the first update()"

    def test_compact_hash_index_stale_rows_removed(self):
        """After compaction the update payload must be exactly header + N data rows."""
        N = 100
        tracker = _make_tracker()
        written_rows = []

        def make_clear(**kwargs):
            m = MagicMock()
            m._op = "clear"
            return m

        def make_update(**kwargs):
            m = MagicMock()
            m._op = "update"
            chunk = kwargs.get("body", {}).get("values", [])
            written_rows.extend(chunk)
            return m

        tracker._known_hashes = _known_dict(N)
        tracker.sheets.read_all_rows.return_value = []

        ss = tracker.sheets.sheets.spreadsheets.return_value.values.return_value
        ss.clear.side_effect = make_clear
        ss.update.side_effect = make_update
        tracker.sheets._execute_with_backoff = lambda req: req

        with patch.dict(os.environ, {"HASH_INDEX_COMPACT_THRESHOLD": "50"}):
            tracker.compact_hash_index()

        # header row + N data rows = N + 1
        assert len(written_rows) == N + 1, (
            f"Expected {N + 1} rows (header + {N} entries), got {len(written_rows)}"
        )

    def test_compact_hash_index_rollback_on_update_failure(self):
        """If update raises after clear, a restore update must be attempted."""
        tracker = _make_tracker()
        tracker._known_hashes = _known_dict(100)
        original = [["sha256", "file_id"], ["sha_orig", "fid_orig"]]
        tracker.sheets.read_all_rows.return_value = original

        update_call_count = [0]
        restore_called = [False]

        def make_clear(**kwargs):
            m = MagicMock()
            m._op = "clear"
            return m

        def make_update(**kwargs):
            update_call_count[0] += 1
            m = MagicMock()
            m._op = "update"
            m._body = kwargs.get("body", {})
            # First update attempt raises; second (restore) must succeed
            if update_call_count[0] == 1:
                raise Exception("simulated update failure")
            restore_called[0] = True
            return m

        ss = tracker.sheets.sheets.spreadsheets.return_value.values.return_value
        ss.clear.side_effect = make_clear
        ss.update.side_effect = make_update
        tracker.sheets._execute_with_backoff = lambda req: req._op and req  # call side_effect

        # Wrap _execute_with_backoff to actually invoke the mock
        def exe(req):
            return req  # side_effect on the mock was already called when building req

        tracker.sheets._execute_with_backoff = exe

        try:
            with patch.dict(os.environ, {"HASH_INDEX_COMPACT_THRESHOLD": "50"}):
                tracker.compact_hash_index()
        except Exception:
            pass  # expected — update failed

        assert update_call_count[0] >= 2, "Restore update must be attempted after failure"
        assert restore_called[0], "Second update call (restore) must have been invoked"


# ---------------------------------------------------------------------------
# BUG-B: append_new_hashes — only ORIGINAL/ORIGINAL_RESUMED go to the sheet
# ---------------------------------------------------------------------------

class TestAppendNewHashes:

    def test_append_new_hashes_no_append_for_unchanged(self):
        """UNCHANGED_CONTENT and SKIPPED_SIZE must not be appended to Hash_Index."""
        tracker = _make_tracker()
        tracker._known_hashes = {}  # start with empty cache

        records = (
            [_make_record(f"uc_{i}", "UNCHANGED_CONTENT") for i in range(3)]
            + [_make_record(f"ss_{i}", "SKIPPED_SIZE") for i in range(2)]
            + [_make_record("orig_1", "ORIGINAL")]
        )

        tracker.append_new_hashes(records)

        # Only ORIGINAL should be appended to the sheet
        assert tracker.sheets.append_rows.call_count == 1
        call_args = tracker.sheets.append_rows.call_args
        rows_written = call_args[0][1]  # positional arg: rows list
        assert len(rows_written) == 1, (
            f"Expected 1 row appended (ORIGINAL only), got {len(rows_written)}"
        )

        # In-memory cache must have all 6 entries
        assert len(tracker._known_hashes) == 6, (
            f"_known_hashes must track all 6 records, got {len(tracker._known_hashes)}"
        )
        assert "orig_1" in tracker._known_hashes
        for i in range(3):
            assert f"uc_{i}" in tracker._known_hashes
        for i in range(2):
            assert f"ss_{i}" in tracker._known_hashes
