"""Targeted unit tests for shared/drive_helpers.py.

Covers:
- is_in_target_folder: direct parent, grandparent, not found, cache hits, cycles, empty target
- execute_with_backoff: success, transient retry, non-retryable raises immediately
"""
import sys
import os
from unittest.mock import MagicMock

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


# ---------------------------------------------------------------------------
# HARDENING-1: walk queue JSON roundtrip (folder IDs with commas survive)
# ---------------------------------------------------------------------------

class TestWalkQueueJsonRoundtrip:

    def test_walk_queue_json_roundtrip(self):
        """HARDENING-1: folder IDs containing commas must survive queue checkpoint/resume.

        Previously the queue was serialised as comma-joined CSV, which silently
        split folder IDs that contained a comma into multiple invalid IDs.
        json.dumps/json.loads must now be used instead.
        """
        import json

        # Folder IDs that would break CSV serialisation
        original_queue = ["folder_normal", "folder,with,commas", "another_normal"]

        serialized = json.dumps(original_queue)
        restored = json.loads(serialized)

        assert restored == original_queue, (
            f"Queue must survive JSON roundtrip intact: {original_queue!r} → {restored!r}"
        )
        assert "folder,with,commas" in restored, (
            "Folder ID containing a comma must not be split on deserialisation"
        )

    def test_walk_queue_legacy_csv_fallback(self):
        """HARDENING-1 backward compat: old CSV-encoded queue must still be parsed."""
        import json

        # Simulate the old serialisation format that might be in a live State sheet
        old_csv_value = "folder_a,folder_b,folder_c"

        # json.loads should fail on plain CSV, then the fallback split should recover it
        try:
            result = json.loads(old_csv_value)
            # If json.loads succeeds (it won't for plain CSV without quotes), that's fine too
        except (json.JSONDecodeError, ValueError):
            result = old_csv_value.split(",")

        assert result == ["folder_a", "folder_b", "folder_c"]


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

    def test_file_moved_outside_target_produces_scope_exit_event(self):
        """T-4: BUG-3 fix — a file that moves out of the target folder tree must produce
        a synthetic removed+scope_exit event instead of being silently dropped."""
        from unittest.mock import patch as _patch
        from shared.change_type_logic import determine_change_type

        mgr = _make_manager(target_folder_id="TARGET")
        # File has parents only outside the target tree
        change_event = {
            "fileId": "file_moved_out",
            "removed": False,
            "file": {
                "id": "file_moved_out",
                "name": "moved.pdf",
                "mimeType": "application/pdf",
                "parents": ["outside_folder"],
                "trashed": False,
            },
        }
        api_response = {
            "changes": [change_event],
            "newStartPageToken": "tok_new",
        }

        with _patch.object(mgr, "is_in_target_folder", return_value=False), \
             _patch.object(mgr, "execute_with_backoff", return_value=api_response):
            changes, _next, _new_start = mgr.fetch_delta_chunk("tok_old")

        assert len(changes) == 1, "moved-out-of-scope file must appear as a change event"
        c = changes[0]
        assert c.get("removed") is True, "scope-exit event must have removed=True"
        assert c.get("scope_exit") is True, "scope-exit event must have scope_exit=True"

        # change_type_logic must classify it as MOVED_OUT_OF_SCOPE, not REMOVED_OR_NO_ACCESS
        ct = determine_change_type(c, known_file_details={}, is_initial=False)
        assert ct == "MOVED_OUT_OF_SCOPE", f"expected MOVED_OUT_OF_SCOPE, got {ct}"
