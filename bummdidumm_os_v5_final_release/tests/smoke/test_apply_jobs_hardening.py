"""Regression tests for apply_sort and apply_renames hardening.

Covers:
- BUG-K: current_phase set to APPLY_SORT_FAILED / APPLY_RENAMES_FAILED on exception
- BUG-P0: batch flush uses drive_mgr.execute_with_backoff (retries 500/503)
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


# ---------------------------------------------------------------------------
# BUG-K: FAILED phase on exception
# ---------------------------------------------------------------------------

class TestApplySortFailedPhase:

    def _make_mocks(self):
        credentials = MagicMock()
        drive_service = MagicMock()
        sheets_service = MagicMock()
        sheet_mgr = MagicMock()
        state = MagicMock()
        drive_mgr = MagicMock()
        drive_mgr.execute_with_backoff.side_effect = lambda fn: fn()
        return credentials, drive_service, sheets_service, sheet_mgr, state, drive_mgr

    def test_apply_sort_failed_phase_on_exception(self):
        """BUG-K: when row processing raises, current_phase must be APPLY_SORT_FAILED."""
        import main_apply_sort

        credentials, drive_service, sheets_service, sheet_mgr, state, drive_mgr = self._make_mocks()

        state.get_val.side_effect = lambda k: "run_001" if k == "last_successful_run_id" else ""
        state.acquire_job_lock.return_value = True
        state.run_id = "run_001"

        # Simulate rows that trigger the move path but raise on execution
        _bad_row = [
            "run_001",          # run_id
            "file_001",         # file_id
            "bad_file.pdf",     # name
            "application/pdf",  # mime_type
            "",                 # current_location
            "parent_001",       # current_parent_id
        ] + [""] * 10           # pad to expected length

        sheet_mgr.headers = {"Sorting_Suggestions": ["run_id"] * 15}
        sheet_mgr.SORT_COL = {
            "file_id": 1,
            "name": 2,
            "suggested_target_folder_id": 3,
            "action_mode": 4,
            "move_result": 5,
        }
        # Row with action_mode=SAFE, target_folder_id=folder_x, move_result=PENDING
        test_row = ["run_001", "file_001", "bad_file.pdf", "folder_x", "SAFE", "PENDING"] + [""] * 9
        sheet_mgr.read_rows_chunked_with_row_numbers.return_value = [(2, test_row)]

        # Make the drive call raise
        drive_mgr.execute_with_backoff.side_effect = RuntimeError("simulated drive failure")

        phase_set = {}
        def capture_set_val(key, val):
            phase_set[key] = val
        state.set_val.side_effect = capture_set_val

        with (
            patch("main_apply_sort.CONTROL_SHEET_ID", "test_sheet_id"),
            patch("main_apply_sort.get_user_credentials", return_value=credentials),
            patch("main_apply_sort.build", side_effect=[drive_service, sheets_service]),
            patch("shared.drive_helpers.DriveManager", return_value=drive_mgr),
            patch("main_apply_sort.SheetManager", return_value=sheet_mgr),
            patch("main_apply_sort.StateTracker", return_value=state),
            patch("shared.log.get_logger", return_value=MagicMock()),
        ):
            try:
                main_apply_sort.run_apply_sort()
            except Exception:
                pass

        assert phase_set.get("current_phase") == "APPLY_SORT_FAILED", (
            f"Expected APPLY_SORT_FAILED, got {phase_set.get('current_phase')!r}"
        )


class TestApplyRenamesFailedPhase:

    def test_apply_renames_failed_phase_on_exception(self):
        """BUG-K: when row processing raises, current_phase must be APPLY_RENAMES_FAILED."""
        import main_apply_renames

        credentials = MagicMock()
        drive_service = MagicMock()
        sheets_service = MagicMock()
        sheet_mgr = MagicMock()
        state = MagicMock()
        drive_mgr = MagicMock()

        state.get_val.side_effect = lambda k: "run_001" if k == "last_successful_run_id" else ""
        state.acquire_job_lock.return_value = True
        state.run_id = "run_001"

        # Row with a rename pending
        dedupe_col = {"run_id": 1, "file_id": 2, "name": 3, "suggested_name": 4}
        sheet_mgr.DEDUPE_COL = dedupe_col
        sheet_mgr.headers = {"Dedupe_Report": ["h"] * 18}
        # row: run_utc at [0], run_id at [1], file_id at [2], name at [3], suggested at [4]
        test_row = ["2026-01-01", "run_001", "file_002", "old.pdf", "new.pdf"] + [""] * 15
        sheet_mgr.read_rows_chunked_with_row_numbers.return_value = [(2, test_row)]

        # Make the drive update raise
        drive_mgr.execute_with_backoff.side_effect = RuntimeError("simulated rename failure")

        phase_set = {}
        def capture_set_val(key, val):
            phase_set[key] = val
        state.set_val.side_effect = capture_set_val

        with (
            patch("main_apply_renames.CONTROL_SHEET_ID", "test_sheet_id"),
            patch("main_apply_renames.get_user_credentials", return_value=credentials),
            patch("main_apply_renames.build", side_effect=[drive_service, sheets_service]),
            patch("shared.drive_helpers.DriveManager", return_value=drive_mgr),
            patch("main_apply_renames.SheetManager", return_value=sheet_mgr),
            patch("main_apply_renames.StateTracker", return_value=state),
            patch("shared.log.get_logger", return_value=MagicMock()),
        ):
            try:
                main_apply_renames.run_apply_renames()
            except Exception:
                pass

        assert phase_set.get("current_phase") == "APPLY_RENAMES_FAILED", (
            f"Expected APPLY_RENAMES_FAILED, got {phase_set.get('current_phase')!r}"
        )


# ---------------------------------------------------------------------------
# BUG-P0: batch flush retries on 500
# ---------------------------------------------------------------------------

class TestApplyRenamesBatchFlushRetries:

    def test_apply_renames_batch_flush_retries_500(self):
        """BUG-P0: batch flush via drive_mgr.execute_with_backoff must retry 500 errors.

        Verifies that drive_mgr.execute_with_backoff is used for the batch flush
        (not sheet_mgr._execute_with_backoff which previously did not retry 500/503).
        """
        from pathlib import Path

        for p in [Path("main_apply_renames.py"),
                  Path("bummdidumm_os_v5_final_release/main_apply_renames.py")]:
            if p.exists():
                source = p.read_text(encoding="utf-8")
                break
        else:
            raise FileNotFoundError("main_apply_renames.py not found")

        # The batch flush must use drive_mgr.execute_with_backoff (lambda-based),
        # NOT sheet_mgr._execute_with_backoff (which received a pre-built request).
        assert "drive_mgr.execute_with_backoff" in source, (
            "Batch flush must use drive_mgr.execute_with_backoff so 500/503 errors "
            "trigger a retry with a freshly-built request (BUG-P0 fix)"
        )
        # The lambda pattern ensures a fresh request is built on each retry
        assert "lambda" in source, (
            "Batch flush lambda must be present so the Sheets request is rebuilt "
            "on each retry attempt"
        )
        # The old pattern (sheet_mgr._execute_with_backoff with a pre-built request)
        # must not be used for the batchUpdate calls
        import ast
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr == "_execute_with_backoff":
                # Check if any arg contains batchUpdate
                for arg in node.args:
                    arg_src = ast.unparse(arg) if hasattr(ast, "unparse") else ""
                    assert "batchUpdate" not in arg_src, (
                        "sheet_mgr._execute_with_backoff must NOT be called with a "
                        "batchUpdate request — use drive_mgr.execute_with_backoff instead"
                    )
