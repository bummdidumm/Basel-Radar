"""Targeted unit tests for shared/drive_helpers.py.

Covers:
- is_in_target_folder: direct parent, grandparent, not found, cache hits, cycles, empty target
- execute_with_backoff: success, transient retry, non-retryable raises immediately
"""
import sys
import os
import time
import types
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from shared.drive_helpers import DriveManager


def _make_manager(target_folder_id="ROOT"):
    drive = MagicMock()
    return DriveManager(drive, target_folder_id, enable_shared_drives=False)


# ---------------------------------------------------------------------------
# is_in_target_folder
# ---------------------------------------------------------------------------

class TestIsInTargetFolder:

    def test_direct_parent_match(self):
        mgr = _make_manager("ROOT")
        assert mgr.is_in_target_folder("file1", ["ROOT"]) is True

    def test_empty_target_returns_true(self):
        mgr = _make_manager("")
        assert mgr.is_in_target_folder("file1", ["any_folder"]) is True

    def test_no_parents_returns_false(self):
        mgr = _make_manager("ROOT")
        assert mgr.is_in_target_folder("file1", []) is False

    def test_grandparent_match(self):
        mgr = _make_manager("ROOT")
        # file → parent_A → ROOT
        mgr.drive.files().get.return_value.execute.return_value = {"id": "parent_A", "parents": ["ROOT"]}
        assert mgr.is_in_target_folder("file1", ["parent_A"]) is True

    def test_not_in_target_tree(self):
        mgr = _make_manager("ROOT")
        # parent_B has no parents → dead end
        mgr.drive.files().get.return_value.execute.return_value = {"id": "parent_B", "parents": []}
        assert mgr.is_in_target_folder("file1", ["parent_B"]) is False

    def test_cache_hit_true_skips_api(self):
        mgr = _make_manager("ROOT")
        mgr.ancestor_cache["parent_X"] = True
        result = mgr.is_in_target_folder("file1", ["parent_X"])
        assert result is True
        mgr.drive.files().get.assert_not_called()

    def test_cache_hit_false_skips_api(self):
        mgr = _make_manager("ROOT")
        mgr.ancestor_cache["dead_end"] = False
        result = mgr.is_in_target_folder("file1", ["dead_end"])
        assert result is False
        mgr.drive.files().get.assert_not_called()

    def test_cycle_protection(self):
        mgr = _make_manager("ROOT")
        # folder_A points to itself → must not infinite-loop
        def fake_get(fileId, fields, **kwargs):
            m = MagicMock()
            m.execute.return_value = {"id": fileId, "parents": [fileId]}
            return m
        mgr.drive.files().get.side_effect = fake_get
        # Should terminate and return False
        assert mgr.is_in_target_folder("file1", ["folder_A"]) is False

    def test_api_exception_cached_false(self):
        mgr = _make_manager("ROOT")
        mgr.drive.files().get.return_value.execute.side_effect = Exception("network error")
        result = mgr.is_in_target_folder("file1", ["error_folder"])
        assert result is False
        assert mgr.ancestor_cache.get("error_folder") is False

    def test_grandparent_cached_on_find(self):
        mgr = _make_manager("ROOT")
        def fake_get(fileId, fields, **kwargs):
            m = MagicMock()
            m.execute.return_value = {"id": fileId, "parents": ["ROOT"]}
            return m
        mgr.drive.files().get.side_effect = fake_get
        assert mgr.is_in_target_folder("file1", ["mid_folder"]) is True
        # The mid_folder should now be cached as True
        assert mgr.ancestor_cache.get("mid_folder") is True


# ---------------------------------------------------------------------------
# execute_with_backoff
# ---------------------------------------------------------------------------

class TestExecuteWithBackoff:
    def test_success_first_try(self):
        mgr = _make_manager()
        result = mgr.execute_with_backoff(lambda: "ok")
        assert result == "ok"

    def test_retries_on_429(self):
        from googleapiclient.errors import HttpError
        from unittest.mock import patch as _patch

        mgr = _make_manager()
        resp = MagicMock()
        resp.status = 429
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise HttpError(resp, b"rate limited")
            return "done"

        with _patch("time.sleep"):
            result = mgr.execute_with_backoff(flaky)

        assert result == "done"
        assert call_count["n"] == 3

    def test_non_retryable_raises_immediately(self):
        from googleapiclient.errors import HttpError
        import pytest

        mgr = _make_manager()
        resp = MagicMock()
        resp.status = 403

        def forbidden():
            raise HttpError(resp, b"forbidden")

        with pytest.raises(HttpError):
            mgr.execute_with_backoff(forbidden)


class TestFetchDeltaChunk:
    def test_fetch_delta_chunk_uses_backoff_wrapper(self):
        mgr = _make_manager()
        mgr.execute_with_backoff = MagicMock(
            return_value={"changes": [], "nextPageToken": "nxt", "newStartPageToken": "new"}
        )

        changes, next_token, new_start = mgr.fetch_delta_chunk("token_1")

        assert changes == []
        assert next_token == "nxt"
        assert new_start == "new"
        assert mgr.execute_with_backoff.call_count == 1
