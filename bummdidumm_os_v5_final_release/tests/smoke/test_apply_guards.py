"""Regression tests for idempotency and staleness guards in apply_sort / apply_renames.

Guards verified:
  apply_sort:    SUCCESS_ALREADY_IN_TARGET  — file already in target folder
                 SUCCESS_ALREADY_TRASHED    — file already trashed (SWEEP_TRASH)
                 STALE_SOURCE_STATE         — file trashed but mode is SAFE move
  apply_renames: SUCCESS_ALREADY_RENAMED    — file already has the suggested name
                 STALE_NAME_MISMATCH        — current Drive name differs from sheet value
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


# ── Stub helpers (same pattern as test_change_type_propagation.py) ───────────

def _make_apply_stubs() -> dict:
    candidates = {
        "shared.oauth_user_credentials": {"get_user_credentials": MagicMock(return_value=MagicMock())},
        "googleapiclient.discovery": {"build": MagicMock()},
    }
    stubs = {}
    for mod, attrs in candidates.items():
        if mod not in sys.modules:
            stub = MagicMock()
            for k, v in attrs.items():
                setattr(stub, k, v)
            stubs[mod] = stub
    return stubs


# ── Column layouts (mirrors shared/sheets_helpers.py) ────────────────────────

_SORT_HEADERS = [
    "run_id", "file_id", "name", "mime_type", "current_location",
    "current_parent_id", "folder_rule", "folder_rule_reason",
    "suggested_target_folder", "suggested_target_folder_id",
    "target_path", "action_mode", "move_result",
]
_SORT_COL = {c: i for i, c in enumerate(_SORT_HEADERS)}

_DEDUPE_HEADERS = [
    "run_utc", "run_id", "path", "name", "file_id", "mime_type",
    "effective_mime_type", "size_bytes", "md5", "sha256", "status",
    "change_type", "duplicate_of", "archive_result", "suggested_name",
    "web_link", "notes", "rename_result",
]
_DEDUPE_COL = {c: i for i, c in enumerate(_DEDUPE_HEADERS)}


# ── Row factories ─────────────────────────────────────────────────────────────

def _sort_row(
    file_id="file1",
    name="file.txt",
    target_folder_id="target_folder",
    action_mode="SAFE",
    move_result="PENDING",
    run_id="run_test",
) -> list:
    row = [""] * len(_SORT_HEADERS)
    row[_SORT_COL["run_id"]] = run_id
    row[_SORT_COL["file_id"]] = file_id
    row[_SORT_COL["name"]] = name
    row[_SORT_COL["suggested_target_folder_id"]] = target_folder_id
    row[_SORT_COL["action_mode"]] = action_mode
    row[_SORT_COL["move_result"]] = move_result
    return row


def _rename_row(
    file_id="file1",
    name="old.txt",
    suggested_name="new.txt",
    rename_result="",
    run_id="run_test",
) -> list:
    row = [""] * len(_DEDUPE_HEADERS)
    row[_DEDUPE_COL["run_id"]] = run_id
    row[_DEDUPE_COL["file_id"]] = file_id
    row[_DEDUPE_COL["name"]] = name
    row[_DEDUPE_COL["suggested_name"]] = suggested_name
    row[_DEDUPE_COL["rename_result"]] = rename_result
    return row


# ── Mock factories ────────────────────────────────────────────────────────────

def _make_state_stub():
    state = MagicMock()
    state.acquire_job_lock.return_value = True
    state.get_val.side_effect = lambda k: "run_test" if k == "last_successful_run_id" else None
    return state


def _make_sort_sheet_mock(rows: list) -> MagicMock:
    sm = MagicMock()
    sm.headers = {"Sorting_Suggestions": _SORT_HEADERS}
    sm.SORT_COL = _SORT_COL
    sm.read_rows_chunked_with_row_numbers.return_value = iter(
        [(i + 2, r) for i, r in enumerate(rows)]
    )
    sm._execute_with_backoff.side_effect = lambda req: req.execute()
    return sm


def _make_rename_sheet_mock(rows: list) -> MagicMock:
    sm = MagicMock()
    sm.headers = {"Dedupe_Report": _DEDUPE_HEADERS}
    sm.DEDUPE_COL = _DEDUPE_COL
    sm.read_rows_chunked_with_row_numbers.return_value = iter(
        [(i + 2, r) for i, r in enumerate(rows)]
    )
    sm._execute_with_backoff.side_effect = lambda req: req.execute()
    return sm


def _make_drive_mock(metadata_by_file_id: dict) -> MagicMock:
    """metadata_by_file_id: {file_id: {"parents": [...], "trashed": bool, "name": str}}"""
    drive = MagicMock()

    def _get(**kwargs):
        fid = kwargs.get("fileId", "")
        meta = metadata_by_file_id.get(fid, {"parents": [], "trashed": False, "name": ""})
        req = MagicMock()
        req.execute.return_value = dict(meta)
        return req

    drive.files.return_value.get.side_effect = _get
    return drive


# ── Runner helpers ────────────────────────────────────────────────────────────

def _run_apply_sort(rows: list, drive_meta: dict) -> tuple[MagicMock, list]:
    """Run run_apply_sort with mocked sheet + Drive.  Returns (mock_drive, written_data)."""
    mock_drive_svc = _make_drive_mock(drive_meta)
    mock_sheets_svc = MagicMock()
    written_data: list = []

    def _capture_batch(**kw):
        written_data.extend(kw.get("body", {}).get("data", []))
        return MagicMock()

    mock_sheets_svc.spreadsheets.return_value.values.return_value.batchUpdate.side_effect = _capture_batch

    mock_sheet_mgr = _make_sort_sheet_mock(rows)
    mock_state = _make_state_stub()

    def _build(service, version, **kw):
        return mock_drive_svc if service == "drive" else mock_sheets_svc

    with patch.dict(sys.modules, _make_apply_stubs()):
        with patch("main_apply_sort.CONTROL_SHEET_ID", "dummy"), \
             patch("main_apply_sort.get_user_credentials", return_value=MagicMock()), \
             patch("main_apply_sort.build", side_effect=_build), \
             patch("main_apply_sort.SheetManager", return_value=mock_sheet_mgr), \
             patch("main_apply_sort.StateTracker", return_value=mock_state):
            from main_apply_sort import run_apply_sort
            run_apply_sort()

    return mock_drive_svc, written_data


def _run_apply_renames(rows: list, drive_meta: dict) -> tuple[MagicMock, list]:
    """Run run_apply_renames with mocked sheet + Drive.  Returns (mock_drive, written_data)."""
    mock_drive_svc = _make_drive_mock(drive_meta)
    mock_sheets_svc = MagicMock()
    written_data: list = []

    def _capture_batch(**kw):
        written_data.extend(kw.get("body", {}).get("data", []))
        return MagicMock()

    mock_sheets_svc.spreadsheets.return_value.values.return_value.batchUpdate.side_effect = _capture_batch

    mock_sheet_mgr = _make_rename_sheet_mock(rows)
    mock_state = _make_state_stub()

    def _build(service, version, **kw):
        return mock_drive_svc if service == "drive" else mock_sheets_svc

    with patch.dict(sys.modules, _make_apply_stubs()):
        with patch("main_apply_renames.CONTROL_SHEET_ID", "dummy"), \
             patch("main_apply_renames.get_user_credentials", return_value=MagicMock()), \
             patch("main_apply_renames.build", side_effect=_build), \
             patch("main_apply_renames.SheetManager", return_value=mock_sheet_mgr), \
             patch("main_apply_renames.StateTracker", return_value=mock_state):
            from main_apply_renames import run_apply_renames
            run_apply_renames()

    return mock_drive_svc, written_data


def _result_values(written_data: list) -> list:
    return [item["values"][0][0] for item in written_data if item.get("values")]


# ── apply_sort guard tests ────────────────────────────────────────────────────

class TestApplySortGuards(unittest.TestCase):

    def test_already_in_target_no_drive_update(self):
        """File already in target folder → SUCCESS_ALREADY_IN_TARGET, Drive update NOT called."""
        row = _sort_row(file_id="f1", target_folder_id="target123", action_mode="SAFE")
        mock_drive, written = _run_apply_sort(
            [row], {"f1": {"parents": ["target123"], "trashed": False}}
        )
        mock_drive.files.return_value.update.assert_not_called()
        self.assertIn("SUCCESS_ALREADY_IN_TARGET", _result_values(written))

    def test_already_trashed_no_drive_update(self):
        """File already trashed (SWEEP_TRASH) → SUCCESS_ALREADY_TRASHED, Drive update NOT called."""
        row = _sort_row(file_id="f2", action_mode="SWEEP_TRASH")
        mock_drive, written = _run_apply_sort(
            [row], {"f2": {"parents": [], "trashed": True}}
        )
        mock_drive.files.return_value.update.assert_not_called()
        self.assertIn("SUCCESS_ALREADY_TRASHED", _result_values(written))

    def test_stale_source_state_no_drive_update(self):
        """File already trashed in SAFE move mode → STALE_SOURCE_STATE, Drive update NOT called."""
        row = _sort_row(file_id="f3", target_folder_id="target123", action_mode="SAFE")
        mock_drive, written = _run_apply_sort(
            [row], {"f3": {"parents": ["other_folder"], "trashed": True}}
        )
        mock_drive.files.return_value.update.assert_not_called()
        self.assertIn("STALE_SOURCE_STATE", _result_values(written))

    def test_normal_move_still_calls_drive_update(self):
        """Sanity: file not in target and not trashed → Drive update IS called."""
        row = _sort_row(file_id="f4", target_folder_id="target123", action_mode="SAFE")
        mock_drive, written = _run_apply_sort(
            [row], {"f4": {"parents": ["other_folder"], "trashed": False}}
        )
        mock_drive.files.return_value.update.assert_called_once()
        self.assertIn("SUCCESS", _result_values(written))


# ── apply_renames guard tests ─────────────────────────────────────────────────

class TestApplyRenamesGuards(unittest.TestCase):

    def test_already_renamed_no_drive_update(self):
        """File already has suggested name → SUCCESS_ALREADY_RENAMED, Drive update NOT called."""
        row = _rename_row(file_id="f5", name="old.txt", suggested_name="new.txt")
        mock_drive, written = _run_apply_renames(
            [row], {"f5": {"name": "new.txt"}}
        )
        mock_drive.files.return_value.update.assert_not_called()
        self.assertIn("SUCCESS_ALREADY_RENAMED", _result_values(written))

    def test_stale_name_mismatch_no_drive_update(self):
        """Drive name differs from sheet's current_name → STALE_NAME_MISMATCH, no update."""
        row = _rename_row(file_id="f6", name="old.txt", suggested_name="new.txt")
        mock_drive, written = _run_apply_renames(
            [row], {"f6": {"name": "already_different.txt"}}
        )
        mock_drive.files.return_value.update.assert_not_called()
        self.assertIn("STALE_NAME_MISMATCH", _result_values(written))

    def test_normal_rename_still_calls_drive_update(self):
        """Sanity: Drive name matches sheet's current_name → Drive update IS called."""
        row = _rename_row(file_id="f7", name="old.txt", suggested_name="new.txt")
        mock_drive, written = _run_apply_renames(
            [row], {"f7": {"name": "old.txt"}}
        )
        mock_drive.files.return_value.update.assert_called_once()
        self.assertIn("SUCCESS", _result_values(written))


if __name__ == "__main__":
    unittest.main()
