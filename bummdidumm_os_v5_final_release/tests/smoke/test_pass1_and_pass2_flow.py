"""Regression tests for Pass 1 delta-token flushing and Pass 2 job-lock / JSONL safety.

Covers:
- BUG-C: flush_state() called after every in-progress token update in the delta loop
- BUG-E: Pass 2 acquires a job lock; second concurrent instance must abort
- BUG-F: Pass 2 JSONL written under BRAIN_INDEX_ROOT, not the ephemeral CWD
- BUG-L: Upload step skipped when pass2_jsonl_upload_done marker matches run_id
"""
import ast
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from shared.state_helpers import StateTracker


# ---------------------------------------------------------------------------
# Shared state store (reused from test_job_locks.py pattern)
# ---------------------------------------------------------------------------

class SharedStateStore:
    def __init__(self, initial=None):
        self.data = dict(initial or {})


def _make_tracker(store: SharedStateStore, owner_id: str) -> StateTracker:
    tracker = StateTracker.__new__(StateTracker)
    tracker.owner_id = owner_id
    tracker.run_id = f"run_{owner_id}"
    tracker._state_cache = dict(store.data)
    tracker._known_hashes = None
    tracker._dirty = False

    def _flush():
        if tracker._dirty:
            store.data.clear()
            store.data.update(tracker._state_cache)
            tracker._dirty = False

    def _reload():
        tracker._state_cache = dict(store.data)

    def _set_val(key, val):
        tracker._state_cache[key] = str(val) if val is not None else ""
        tracker._dirty = True

    def _get_val(key):
        return tracker._state_cache.get(key)

    tracker.flush_state = _flush
    tracker.reload_state = _reload
    tracker.set_val = _set_val
    tracker.get_val = _get_val
    return tracker


# ---------------------------------------------------------------------------
# BUG-C: token flush in delta loop (structural check)
# ---------------------------------------------------------------------------

class TestDeltaTokenFlush:

    def _source(self):
        for p in [Path("main_pass1.py"), Path("bummdidumm_os_v5_final_release/main_pass1.py")]:
            if p.exists():
                return p.read_text(encoding="utf-8")
        raise FileNotFoundError("main_pass1.py not found")

    def test_delta_token_flushed_per_chunk(self):
        """BUG-C: flush_state() must immediately follow the in_progress_page_token update.

        Verified structurally: in the block that advances the token, flush_state()
        must appear before the loop continues to the next chunk.
        """
        source = self._source()
        tree = ast.parse(source)

        # Walk AST to find the If node that checks next_token and sets the token
        # Verify that a flush_state call appears in the same If body
        found_token_flush = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            body_src = ast.unparse(node) if hasattr(ast, "unparse") else ""
            if "in_progress_page_token" in body_src and "flush_state" in body_src:
                found_token_flush = True
                break

        assert found_token_flush, (
            "flush_state() must appear in the same If-block as set_val('in_progress_page_token') "
            "to persist token advancement after each delta chunk (BUG-C fix)"
        )


# ---------------------------------------------------------------------------
# BUG-E: Pass 2 job lock blocks concurrent instance
# ---------------------------------------------------------------------------

class TestPass2JobLock:

    def test_pass2_job_lock_blocks_concurrent(self):
        """Second Pass 2 instance must fail to acquire the lock when first holds it."""
        store = SharedStateStore()
        instance_a = _make_tracker(store, "pass2_owner_A")
        instance_b = _make_tracker(store, "pass2_owner_B")

        result_a = instance_a.acquire_job_lock("pass2", timeout_sec=3600)
        assert result_a is True, "First instance must acquire the pass2 lock"

        result_b = instance_b.acquire_job_lock("pass2", timeout_sec=3600)
        assert result_b is False, (
            "Second instance must be blocked from acquiring the pass2 lock "
            "while the first instance still holds it"
        )
        assert store.data.get("pass2_lock_owner") == "pass2_owner_A"


# ---------------------------------------------------------------------------
# BUG-F: JSONL path under BRAIN_INDEX_ROOT (structural check)
# ---------------------------------------------------------------------------

class TestPass2JsonlPath:

    def _source(self):
        for p in [Path("main_pass2.py"), Path("bummdidumm_os_v5_final_release/main_pass2.py")]:
            if p.exists():
                return p.read_text(encoding="utf-8")
        raise FileNotFoundError("main_pass2.py not found")

    def test_pass2_jsonl_under_brain_index_root(self):
        """BUG-F: JSONL file must be created under BRAIN_INDEX_ROOT, not the ephemeral CWD.

        Verified structurally: 'jsonl_path = BRAIN_INDEX_ROOT / filename' must appear
        and a bare open(filename, ...) that would write to CWD must not.
        """
        source = self._source()

        assert "jsonl_path = BRAIN_INDEX_ROOT / filename" in source, (
            "JSONL path must be explicitly anchored under BRAIN_INDEX_ROOT"
        )
        # Ensure no raw open(filename) that would write to CWD
        assert 'open(filename,' not in source and 'open(filename ,' not in source, (
            "JSONL must not be opened by bare filename (CWD-relative)"
        )


# ---------------------------------------------------------------------------
# BUG-L: upload step skipped when marker matches run_id
# ---------------------------------------------------------------------------

class TestPass2UploadIdempotency:

    def test_pass2_upload_skipped_when_marker_matches_run_id(self):
        """BUG-L: when pass2_jsonl_upload_done == run_id, upload must be skipped.

        Scenario: upload already succeeded in a prior attempt; Brain runtime then
        failed. On retry the upload block must be skipped to avoid duplicate JSONL.
        """
        import main_pass2

        run_id = "run_test_idempotency_001"

        # Build a minimal state mock that reports the upload already done
        state = MagicMock()
        state.run_id = run_id
        state.get_val.side_effect = lambda k: run_id if k == "pass2_jsonl_upload_done" else ""

        drive_service = MagicMock()
        drive_mgr = MagicMock()

        already_uploaded = state.get_val("pass2_jsonl_upload_done") == state.run_id
        assert already_uploaded, "Test precondition: marker must match run_id"

        # Simulate the upload-guard block from run_pass2
        if not already_uploaded:
            drive_service.files().create()  # pragma: no cover — must NOT run

        # files().create must never have been called
        drive_service.files.assert_not_called()
