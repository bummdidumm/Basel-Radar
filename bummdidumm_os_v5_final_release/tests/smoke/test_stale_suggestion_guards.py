"""Regression tests for stale-suggestion guard logic in apply_sort and apply_renames.

Covers apply_sort:
- File already in target folder → SUCCESS_ALREADY_IN_TARGET, no move executed
- File moved to unexpected parent since suggestion → STALE_SOURCE_STATE, no move
- SWEEP_TRASH on already-trashed file → SUCCESS_ALREADY_TRASHED, no update

Covers apply_renames:
- File already has suggested_name in Drive → SUCCESS_ALREADY_RENAMED, no update
- File renamed externally, name doesn't match expected current_name → STALE_NAME_MISMATCH
- Row with existing SUCCESS result is skipped (idempotency still works)
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))


# ---------------------------------------------------------------------------
# Shared row builders
# ---------------------------------------------------------------------------

def _sort_row(run_id, file_id, name, current_parent_id, target_folder_id,
              action_mode="SAFE", move_result="PENDING"):
    """Build a Sorting_Suggestions row matching the sheet schema."""
    # ["run_id","file_id","name","mime_type","current_location","current_parent_id",
    #  "folder_rule","folder_rule_reason","suggested_target_folder",
    #  "suggested_target_folder_id","target_path","action_mode","move_result"]
    return [
        run_id, file_id, name, "application/pdf", f"/path/{file_id}",
        current_parent_id, "rule", "reason", "Target Folder", target_folder_id,
        "/target/path", action_mode, move_result,
    ]


def _rename_row(run_id, file_id, current_name, suggested_name, rename_result=""):
    """Build a Dedupe_Report row matching the sheet schema."""
    # ["run_utc","run_id","path","name","file_id","mime_type","effective_mime_type",
    #  "size_bytes","md5","sha256","status","change_type","duplicate_of",
    #  "archive_result","suggested_name","web_link","notes","rename_result"]
    return [
        "2026-01-01", run_id, f"/path/{file_id}", current_name, file_id,
        "application/pdf", "application/pdf", "1024", "md5x", "sha256x",
        "ORIGINAL", "NEW", "", "", suggested_name, "", "", rename_result,
    ]


# ---------------------------------------------------------------------------
# Test runner helpers
# ---------------------------------------------------------------------------

def _run_sort(rows, drive_get_return):
    """
    Run apply_sort with one file row.

    drive_get_return: what drive_service.files().get(...).execute() returns
                      (the live metadata dict).

    Returns the list of values written via batchUpdate data entries.
    """
    import main_apply_sort
    from shared.sheets_helpers import SheetManager

    credentials = MagicMock()
    drive_service = MagicMock()
    sheets_service = MagicMock()
    state = MagicMock()
    drive_mgr = MagicMock()

    state.acquire_job_lock.return_value = True
    state.get_val.side_effect = lambda k: "run_001" if k == "last_successful_run_id" else ""

    # drive_mgr.execute_with_backoff always calls fn() — real behaviour
    drive_mgr.execute_with_backoff.side_effect = lambda fn: fn()

    # Drive.files().get(...).execute() returns the live metadata
    drive_service.files.return_value.get.return_value.execute.return_value = drive_get_return
    # Drive.files().update(...).execute() returns a generic success dict
    drive_service.files.return_value.update.return_value.execute.return_value = {"id": "x"}

    real_sm = SheetManager.__new__(SheetManager)
    real_sm.headers = SheetManager(MagicMock(), "x").headers
    real_sm.SORT_COL = SheetManager(MagicMock(), "x").SORT_COL

    sheet_mgr = MagicMock()
    sheet_mgr.headers = real_sm.headers
    sheet_mgr.SORT_COL = real_sm.SORT_COL
    sheet_mgr.read_rows_chunked_with_row_numbers.return_value = list(enumerate(rows, start=2))

    written = []

    def capture_batch(data, value_input_option="RAW"):
        assert value_input_option == "RAW"
        for entry in data:
            written.append(entry["values"][0][0])
        return None
    sheet_mgr.batch_update_values.side_effect = capture_batch

    with (
        patch("main_apply_sort.CONTROL_SHEET_ID", "test_sheet"),
        patch("main_apply_sort.get_user_credentials", return_value=credentials),
        patch("main_apply_sort.build", side_effect=[drive_service, sheets_service]),
        patch("shared.drive_helpers.DriveManager", return_value=drive_mgr),
        patch("main_apply_sort.SheetManager", return_value=sheet_mgr),
        patch("main_apply_sort.StateTracker", return_value=state),
        patch("shared.log.get_logger", return_value=MagicMock()),
    ):
        main_apply_sort.run_apply_sort()

    return written, drive_service


def _run_renames(rows, drive_get_return):
    """
    Run apply_renames with one file row.

    drive_get_return: what drive_service.files().get(...).execute() returns.

    Returns the list of values written via batchUpdate data entries.
    """
    import main_apply_renames
    from shared.sheets_helpers import SheetManager

    credentials = MagicMock()
    drive_service = MagicMock()
    sheets_service = MagicMock()
    state = MagicMock()
    drive_mgr = MagicMock()

    state.acquire_job_lock.return_value = True
    state.get_val.side_effect = lambda k: "run_001" if k == "last_successful_run_id" else ""

    drive_mgr.execute_with_backoff.side_effect = lambda fn: fn()
    drive_service.files.return_value.get.return_value.execute.return_value = drive_get_return
    drive_service.files.return_value.update.return_value.execute.return_value = {"id": "x"}

    real_sm = SheetManager.__new__(SheetManager)
    real_sm.headers = SheetManager(MagicMock(), "x").headers
    real_sm.DEDUPE_COL = SheetManager(MagicMock(), "x").DEDUPE_COL

    sheet_mgr = MagicMock()
    sheet_mgr.headers = real_sm.headers
    sheet_mgr.DEDUPE_COL = real_sm.DEDUPE_COL
    sheet_mgr.read_rows_chunked_with_row_numbers.return_value = list(enumerate(rows, start=2))

    written = []

    def capture_batch(data, value_input_option="RAW"):
        assert value_input_option == "RAW"
        for entry in data:
            written.append(entry["values"][0][0])
        return None
    sheet_mgr.batch_update_values.side_effect = capture_batch

    with (
        patch("main_apply_renames.CONTROL_SHEET_ID", "test_sheet"),
        patch("main_apply_renames.get_user_credentials", return_value=credentials),
        patch("main_apply_renames.build", side_effect=[drive_service, sheets_service]),
        patch("shared.drive_helpers.DriveManager", return_value=drive_mgr),
        patch("main_apply_renames.SheetManager", return_value=sheet_mgr),
        patch("main_apply_renames.StateTracker", return_value=state),
        patch("shared.log.get_logger", return_value=MagicMock()),
    ):
        main_apply_renames.run_apply_renames()

    return written, drive_service


# ---------------------------------------------------------------------------
# apply_sort stale-guard tests
# ---------------------------------------------------------------------------

class TestApplySortStaleGuards:

    def test_already_in_target_folder_no_move(self):
        """File already in target → SUCCESS_ALREADY_IN_TARGET, files.update NOT called."""
        target_folder_id = "folder_target"
        row = _sort_row("run_001", "file_abt", "doc.pdf",
                        current_parent_id="folder_origin",
                        target_folder_id=target_folder_id)

        live_meta = {"id": "file_abt", "parents": [target_folder_id], "trashed": False}

        written, drive_service = _run_sort([row], live_meta)

        assert written == ["SUCCESS_ALREADY_IN_TARGET"], (
            f"Expected ['SUCCESS_ALREADY_IN_TARGET'], got {written!r}"
        )
        drive_service.files.return_value.update.assert_not_called()

    def test_stale_source_state_no_move(self):
        """File moved to unexpected parent → STALE_SOURCE_STATE, files.update NOT called."""
        row = _sort_row("run_001", "file_stale", "moved.pdf",
                        current_parent_id="folder_origin",
                        target_folder_id="folder_target")

        # File is in an unexpected folder (neither origin nor target)
        live_meta = {"id": "file_stale", "parents": ["folder_unexpected"], "trashed": False}

        written, drive_service = _run_sort([row], live_meta)

        assert written == ["STALE_SOURCE_STATE"], (
            f"Expected ['STALE_SOURCE_STATE'], got {written!r}"
        )
        drive_service.files.return_value.update.assert_not_called()

    def test_sweep_trash_already_trashed_no_update(self):
        """SWEEP_TRASH on already-trashed file → SUCCESS_ALREADY_TRASHED, no second update."""
        row = _sort_row("run_001", "file_trash", "trash.pdf",
                        current_parent_id="folder_origin",
                        target_folder_id="",
                        action_mode="SWEEP_TRASH")

        live_meta = {"id": "file_trash", "parents": ["folder_origin"], "trashed": True}

        written, drive_service = _run_sort([row], live_meta)

        assert written == ["SUCCESS_ALREADY_TRASHED"], (
            f"Expected ['SUCCESS_ALREADY_TRASHED'], got {written!r}"
        )
        drive_service.files.return_value.update.assert_not_called()


# ---------------------------------------------------------------------------
# apply_renames stale-guard tests
# ---------------------------------------------------------------------------

class TestApplyRenamesStaleGuards:

    def test_already_renamed_no_update(self):
        """Live name == suggested_name → SUCCESS_ALREADY_RENAMED, files.update NOT called."""
        current_name = "old_name.pdf"
        suggested_name = "new_name.pdf"
        row = _rename_row("run_001", "file_arb", current_name, suggested_name)

        live_meta = {"id": "file_arb", "name": suggested_name}

        written, drive_service = _run_renames([row], live_meta)

        assert written == ["SUCCESS_ALREADY_RENAMED"], (
            f"Expected ['SUCCESS_ALREADY_RENAMED'], got {written!r}"
        )
        drive_service.files.return_value.update.assert_not_called()

    def test_stale_name_mismatch_no_rename(self):
        """Live name differs from expected current_name → STALE_NAME_MISMATCH, no rename."""
        current_name = "original.pdf"
        suggested_name = "suggested.pdf"
        row = _rename_row("run_001", "file_stale_rename", current_name, suggested_name)

        live_meta = {"id": "file_stale_rename", "name": "external_rename.pdf"}

        written, drive_service = _run_renames([row], live_meta)

        assert written == ["STALE_NAME_MISMATCH"], (
            f"Expected ['STALE_NAME_MISMATCH'], got {written!r}"
        )
        drive_service.files.return_value.update.assert_not_called()

    def test_existing_success_row_skipped(self):
        """Row already marked SUCCESS must be skipped — no Drive call, no sheet write."""
        row = _rename_row("run_001", "file_done", "old.pdf", "new.pdf",
                          rename_result="SUCCESS")

        written, drive_service = _run_renames([row], {})

        assert written == [], "No batchUpdate should occur for already-SUCCESS row"
        drive_service.files.return_value.get.assert_not_called()
