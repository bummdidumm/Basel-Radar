"""Targeted unit tests for shared/state_helpers.py.

Covers:
- load_known_hashes: caching (sheet read only once), correct schema mapping
- set_val + flush_state: dirty-flag logic, flush skipped when clean
- compact_reports: under threshold → no compaction, over threshold → compacted
- log_run / log_error: correct row shape appended
"""
import sys
import os
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from shared.state_helpers import StateTracker


def _make_tracker(state_rows=None, hash_rows=None):
    sheets = MagicMock()

    # State tab returns key=run_id so resume logic doesn't interfere
    sheets.read_all_rows.side_effect = lambda tab, rng, raise_on_error=False: {
        "State": state_rows or [["key", "value"], ["run_id", "run_test_001"]],
        "Hash_Index": hash_rows or [["sha256", "file_id", "name", "parent_ids_sorted",
                                     "path_display", "updated_at", "size_bytes", "md5",
                                     "effective_mime_type"]],
    }.get(tab, [])

    sheets.sheets = MagicMock()
    sheets.spreadsheet_id = "sheet_id"

    tracker = StateTracker.__new__(StateTracker)
    tracker.sheets = sheets
    tracker.run_id = "run_test_001"
    tracker._state_cache = {"run_id": "run_test_001", "current_phase": "IDLE"}
    tracker._known_hashes = None
    tracker._dirty = False
    return tracker


# ---------------------------------------------------------------------------
# load_known_hashes
# ---------------------------------------------------------------------------

class TestLoadKnownHashes:
    def test_returns_correct_schema(self):
        hash_rows = [
            ["sha256", "file_id", "name", "parent_ids_sorted", "path_display",
             "updated_at", "size_bytes", "md5", "effective_mime_type"],
            ["abc123", "file_001", "doc.pdf", "folder1", "/folder1/doc.pdf",
             "2026-01-01", "1024", "md5abc", "application/pdf"],
        ]
        tracker = _make_tracker(hash_rows=hash_rows)
        known = tracker.load_known_hashes()
        assert "file_001" in known
        assert known["file_001"]["sha"] == "abc123"
        assert known["file_001"]["name"] == "doc.pdf"

    def test_caching_reads_sheet_only_once(self):
        tracker = _make_tracker()
        tracker.load_known_hashes()
        tracker.load_known_hashes()
        # Hash_Index should only be read once
        hash_calls = [c for c in tracker.sheets.read_all_rows.call_args_list
                      if c[0][0] == "Hash_Index"]
        assert len(hash_calls) == 1

    def test_skips_header_row(self):
        hash_rows = [
            ["sha256", "file_id", "name", "parent_ids_sorted", "path_display",
             "updated_at", "size_bytes", "md5", "effective_mime_type"],
        ]
        tracker = _make_tracker(hash_rows=hash_rows)
        known = tracker.load_known_hashes()
        # Header row must not be included
        assert "sha256" not in known
        assert len(known) == 0


# ---------------------------------------------------------------------------
# set_val + flush_state
# ---------------------------------------------------------------------------

class TestFlushState:
    def test_set_val_marks_dirty(self):
        tracker = _make_tracker()
        assert tracker._dirty is False
        tracker.set_val("current_phase", "DELTA_FETCH")
        assert tracker._dirty is True

    def test_flush_state_clears_dirty_flag(self):
        tracker = _make_tracker()
        tracker.set_val("current_phase", "DELTA_FETCH")
        tracker.flush_state()
        assert tracker._dirty is False

    def test_flush_not_called_when_clean(self):
        tracker = _make_tracker()
        tracker.flush_state()
        # Sheet should not be touched
        tracker.sheets.sheets.spreadsheets.assert_not_called()

    def test_flush_writes_all_state_keys(self):
        tracker = _make_tracker()
        tracker.set_val("foo", "bar")
        tracker.flush_state()
        # Verify that batchUpdate / update was called
        assert tracker.sheets.sheets.spreadsheets().values().update.called


# ---------------------------------------------------------------------------
# compact_reports
# ---------------------------------------------------------------------------

class TestCompactReports:
    def _run_log_rows(self, n):
        header = ["run_utc", "run_id", "phase", "status", "files_processed", "errors"]
        return [header] + [[f"2026-01-0{i%9+1}", f"run_{i}", "PASS_1", "SUCCESS", i, 0] for i in range(n)]

    def test_under_threshold_no_compaction(self):
        tracker = _make_tracker()
        tracker.sheets.read_all_rows.side_effect = lambda tab, rng: (
            self._run_log_rows(10) if tab == "Run_Log" else
            self._run_log_rows(10) if tab == "Error_Report" else []
        )
        tracker.compact_reports()
        # No clear/update should be called
        tracker.sheets._execute_with_backoff.assert_not_called()

    def test_over_threshold_triggers_compaction(self):
        tracker = _make_tracker()
        import os
        with patch.dict(os.environ, {"RUN_LOG_COMPACT_MAX": "5", "ERROR_REPORT_COMPACT_MAX": "5"}):
            tracker.sheets.read_all_rows.side_effect = lambda tab, rng: (
                self._run_log_rows(20) if tab == "Run_Log" else
                self._run_log_rows(3) if tab == "Error_Report" else []
            )
            tracker.compact_reports()
        # clear + update should have been called for Run_Log
        assert tracker.sheets._execute_with_backoff.call_count >= 2


# ---------------------------------------------------------------------------
# log_run / log_error
# ---------------------------------------------------------------------------

class TestLogHelpers:
    def test_log_run_appends_correct_shape(self):
        tracker = _make_tracker()
        tracker.log_run("PASS_1", "SUCCESS", 42, 0)
        args = tracker.sheets.append_rows.call_args
        tab, rows = args[0]
        assert tab == "Run_Log"
        row = rows[0]
        assert row[2] == "PASS_1"
        assert row[3] == "SUCCESS"
        assert row[4] == 42

    def test_log_error_appends_correct_shape(self):
        tracker = _make_tracker()
        tracker.log_error("PASS_2", "file_xyz", "/path/to/file", "HashError", "SHA256 failed")
        args = tracker.sheets.append_rows.call_args
        tab, rows = args[0]
        assert tab == "Error_Report"
        row = rows[0]
        assert row[2] == "PASS_2"
        assert row[3] == "file_xyz"
        assert row[5] == "HashError"
