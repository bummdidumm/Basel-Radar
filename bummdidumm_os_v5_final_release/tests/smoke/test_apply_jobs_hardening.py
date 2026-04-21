"""Regression tests for apply_sort and apply_renames hardening.

Covers:
- BUG-K: current_phase set to APPLY_SORT_FAILED / APPLY_RENAMES_FAILED on exception
- BUG-P0 (updated): apply job batch flushes use SheetManager.batch_update_values
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
# BUG-P0 (updated): apply-job batch flushes must use Sheets retry path
# ---------------------------------------------------------------------------

class TestApplySortBatchFlushWiring:

    def test_apply_sort_batch_flush_uses_sheet_mgr_backoff_in_source(self):
        """Static contract: batchUpdate flushes must route via sheet_mgr.batch_update_values."""
        from pathlib import Path
        import ast

        for p in [Path("main_apply_sort.py"),
                  Path("bummdidumm_os_v5_final_release/main_apply_sort.py")]:
            if p.exists():
                source = p.read_text(encoding="utf-8")
                break
        else:
            raise FileNotFoundError("main_apply_sort.py not found")

        tree = ast.parse(source)
        good_calls = 0
        bad_calls = 0

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if isinstance(node.func, ast.Attribute) and node.func.attr == "batch_update_values":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "sheet_mgr" and node.args:
                    if isinstance(node.args[0], ast.Name) and node.args[0].id == "_batch":
                        good_calls += 1

            if isinstance(node.func, ast.Attribute) and node.func.attr == "execute_with_backoff":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "drive_mgr":
                    if any(
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "batchUpdate"
                        for arg in node.args
                        for sub in ast.walk(arg)
                    ):
                        bad_calls += 1

        assert good_calls >= 2, "Expected both apply-sort batch flushes to use sheet_mgr.batch_update_values(_batch)"
        assert bad_calls == 0, "Apply-sort batch flush must not route batchUpdate via drive_mgr.execute_with_backoff"

    def test_apply_sort_runtime_flush_calls_sheet_mgr_backoff(self):
        """Functional contract: runtime flush routes writes through sheet_mgr.batch_update_values."""
        import main_apply_sort

        credentials = MagicMock()
        drive_service = MagicMock()
        sheets_service = MagicMock()
        sheet_mgr = MagicMock()
        state = MagicMock()
        drive_mgr = MagicMock()

        state.get_val.side_effect = lambda k: "run_001" if k == "last_successful_run_id" else ""
        state.acquire_job_lock.return_value = True

        sheet_mgr.headers = {"Sorting_Suggestions": ["run_id"] * 13}
        sheet_mgr.SORT_COL = {
            "file_id": 1,
            "name": 2,
            "suggested_target_folder_id": 9,
            "action_mode": 11,
            "move_result": 12,
            "current_parent_id": 5,
        }
        test_row = [
            "run_001",          # run_id
            "file_001",         # file_id
            "doc.pdf",          # name
            "application/pdf",  # mime_type
            "/old/path",        # current_location
            "parent_001",       # current_parent_id
            "", "", "",         # folder_rule, reason, target_name
            "folder_x",         # suggested_target_folder_id
            "/target/path",     # target_path
            "SAFE",             # action_mode
            "PENDING",          # move_result
        ]
        sheet_mgr.read_rows_chunked_with_row_numbers.return_value = [(2, test_row)]

        drive_mgr.execute_with_backoff.side_effect = [
            {"parents": ["parent_001"], "trashed": False},  # live state
            {"parents": ["parent_001"]},                    # metadata before move
            {"id": "file_001"},                             # files().update
        ]

        sheet_mgr.batch_update_values = MagicMock()

        with (
            patch("main_apply_sort.CONTROL_SHEET_ID", "test_sheet_id"),
            patch("main_apply_sort.get_user_credentials", return_value=credentials),
            patch("main_apply_sort.build", side_effect=[drive_service, sheets_service]),
            patch("shared.drive_helpers.DriveManager", return_value=drive_mgr),
            patch("main_apply_sort.SheetManager", return_value=sheet_mgr),
            patch("main_apply_sort.StateTracker", return_value=state),
            patch("shared.log.get_logger", return_value=MagicMock()),
        ):
            main_apply_sort.run_apply_sort()

        sheet_mgr.batch_update_values.assert_called_once()
        passed_batch = sheet_mgr.batch_update_values.call_args[0][0]
        assert isinstance(passed_batch, list) and passed_batch, "Batch flush must pass non-empty update list"


class TestApplyRenamesBatchFlushWiring:

    def test_apply_renames_batch_flush_uses_sheet_mgr_backoff_in_source(self):
        """Static contract: batchUpdate flushes must route via sheet_mgr.batch_update_values."""
        from pathlib import Path
        import ast

        for p in [Path("main_apply_renames.py"),
                  Path("bummdidumm_os_v5_final_release/main_apply_renames.py")]:
            if p.exists():
                source = p.read_text(encoding="utf-8")
                break
        else:
            raise FileNotFoundError("main_apply_renames.py not found")

        tree = ast.parse(source)
        good_calls = 0
        bad_calls = 0

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            if isinstance(node.func, ast.Attribute) and node.func.attr == "batch_update_values":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "sheet_mgr" and node.args:
                    if isinstance(node.args[0], ast.Name) and node.args[0].id == "_batch":
                        good_calls += 1

            if isinstance(node.func, ast.Attribute) and node.func.attr == "execute_with_backoff":
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "drive_mgr":
                    if any(
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Attribute)
                        and sub.func.attr == "batchUpdate"
                        for arg in node.args
                        for sub in ast.walk(arg)
                    ):
                        bad_calls += 1

        assert good_calls >= 2, "Expected both rename batch flushes to use sheet_mgr.batch_update_values(_batch)"
        assert bad_calls == 0, "Rename batch flush must not route batchUpdate via drive_mgr.execute_with_backoff"

    def test_apply_renames_runtime_flush_calls_sheet_mgr_backoff(self):
        """Functional contract: runtime flush routes writes through sheet_mgr.batch_update_values."""
        import main_apply_renames

        credentials = MagicMock()
        drive_service = MagicMock()
        sheets_service = MagicMock()
        sheet_mgr = MagicMock()
        state = MagicMock()
        drive_mgr = MagicMock()

        state.get_val.side_effect = lambda k: "run_001" if k == "last_successful_run_id" else ""
        state.acquire_job_lock.return_value = True

        sheet_mgr.DEDUPE_COL = {"run_id": 1, "file_id": 2, "name": 3, "suggested_name": 4, "rename_result": 17}
        sheet_mgr.headers = {"Dedupe_Report": ["h"] * 18}
        test_row = ["2026-01-01", "run_001", "file_002", "old.pdf", "new.pdf"] + [""] * 15
        sheet_mgr.read_rows_chunked_with_row_numbers.return_value = [(2, test_row)]

        drive_mgr.execute_with_backoff.side_effect = [
            {"name": "old.pdf"},  # files().get
            {"id": "file_002"},  # files().update
        ]

        sheet_mgr.batch_update_values = MagicMock()

        with (
            patch("main_apply_renames.CONTROL_SHEET_ID", "test_sheet_id"),
            patch("main_apply_renames.get_user_credentials", return_value=credentials),
            patch("main_apply_renames.build", side_effect=[drive_service, sheets_service]),
            patch("shared.drive_helpers.DriveManager", return_value=drive_mgr),
            patch("main_apply_renames.SheetManager", return_value=sheet_mgr),
            patch("main_apply_renames.StateTracker", return_value=state),
            patch("shared.log.get_logger", return_value=MagicMock()),
        ):
            main_apply_renames.run_apply_renames()

        sheet_mgr.batch_update_values.assert_called_once()
        passed_batch = sheet_mgr.batch_update_values.call_args[0][0]
        assert isinstance(passed_batch, list) and passed_batch, "Batch flush must pass non-empty update list"
