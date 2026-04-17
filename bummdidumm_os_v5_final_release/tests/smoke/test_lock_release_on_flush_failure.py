"""Regression: release_job_lock must run even when flush_state raises in finally.

RISK-02: In apply_sort and apply_renames, if flush_state() throws (rate limit,
network error), the lock must still be released. This is enforced via a nested
try/finally in the cleanup block. This test verifies the structure using AST
analysis and also a runtime scenario with a fake state store.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.state_helpers import StateTracker  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class SharedStateStore:
    """Minimal shared in-memory state store (mirrors test_job_locks.py)."""
    def __init__(self, initial: dict | None = None):
        self.data: dict[str, str] = dict(initial or {})


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


def _read(rel: str) -> str:
    p = _ROOT / rel
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AST structural checks
# ---------------------------------------------------------------------------

def _has_protected_release(source: str, job_name: str) -> bool:
    """Return True if release_job_lock(job_name) is inside its own finally block
    that is itself nested inside the outer finally block.

    We look for the pattern:
        finally:
            ...
            try:
                ...flush_state()...
            finally:
                ...release_job_lock(job_name)...
    """
    tree = ast.parse(source)

    for node in ast.walk(tree):
        # Find a Try node that has a finally body
        if not isinstance(node, ast.Try) or not node.finalbody:
            continue
        outer_finally = node.finalbody

        # Look for an inner Try/finally inside the outer finally
        for stmt in outer_finally:
            if not isinstance(stmt, ast.Try) or not stmt.finalbody:
                continue
            inner_finally = stmt.finalbody

            # Check whether release_job_lock(job_name) is in the inner finally
            for inner_stmt in inner_finally:
                for inner_node in ast.walk(inner_stmt):
                    if not isinstance(inner_node, ast.Call):
                        continue
                    fn = inner_node.func
                    method_name = fn.attr if isinstance(fn, ast.Attribute) else (
                        fn.id if isinstance(fn, ast.Name) else ""
                    )
                    if method_name != "release_job_lock":
                        continue
                    # Check that the job_name string matches
                    for arg in inner_node.args:
                        if isinstance(arg, ast.Constant) and arg.value == job_name:
                            return True
    return False


class TestLockReleaseStructure(unittest.TestCase):

    def test_apply_renames_lock_release_protected(self):
        source = _read("main_apply_renames.py")
        assert _has_protected_release(source, "apply_renames"), (
            "main_apply_renames.py: release_job_lock('apply_renames') must be inside "
            "its own finally block nested within the outer finally, so it runs even "
            "when flush_state() raises."
        )

    def test_apply_sort_lock_release_protected(self):
        source = _read("main_apply_sort.py")
        assert _has_protected_release(source, "apply_sort"), (
            "main_apply_sort.py: release_job_lock('apply_sort') must be inside "
            "its own finally block nested within the outer finally, so it runs even "
            "when flush_state() raises."
        )


# ---------------------------------------------------------------------------
# Runtime scenario: lock is released even when flush_state raises
# ---------------------------------------------------------------------------

class TestLockReleasedOnFlushFailure(unittest.TestCase):

    def test_lock_released_when_flush_raises(self):
        """Simulate flush_state failing in the finally block.

        The lock must be released regardless.
        """
        store = SharedStateStore()
        tracker = _make_tracker(store, "owner_test")

        acquired = tracker.acquire_job_lock("apply_renames", timeout_sec=600)
        self.assertTrue(acquired)
        self.assertEqual(store.data.get("apply_renames_lock_owner"), "owner_test")

        flush_call_count = [0]
        original_flush = tracker.flush_state

        def _failing_flush():
            # Fail exactly on the first call (the "current_phase=IDLE" flush in the
            # try block of the finally). Subsequent calls (lock-release flush) succeed,
            # so that release_job_lock can persist the cleared lock to the store.
            flush_call_count[0] += 1
            if flush_call_count[0] == 1:
                raise RuntimeError("Simulated Sheets API rate limit in finally")
            original_flush()

        tracker.flush_state = _failing_flush

        # Replicate the hardened finally pattern from the fixed apply scripts:
        #   try:
        #       flush_state()
        #   finally:
        #       release_job_lock(...)
        try:
            tracker.set_val("current_phase", "IDLE")
            try:
                tracker.flush_state()  # call 1 → raises
            finally:
                tracker.release_job_lock("apply_renames")  # must be reached; its own flush succeeds
        except RuntimeError:
            pass  # expected — flush failed, but release_job_lock was still called

        self.assertEqual(
            store.data.get("apply_renames_lock_owner", ""),
            "",
            "Lock must be released even when flush_state() raises",
        )


if __name__ == "__main__":
    unittest.main()
