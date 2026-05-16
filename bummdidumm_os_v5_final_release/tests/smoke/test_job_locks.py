"""Tests for job-level lock helpers in StateTracker.

Gap-G: downstream jobs (safe_sort, apply_sort, apply_renames) must use
acquire_job_lock / release_job_lock to prevent concurrent corruption.

Uses a shared in-memory state store (similar to test_parallel_run_guard.py)
to exercise the lock logic without real Sheets API calls.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta

from shared.state_helpers import StateTracker


class SharedStateStore:
    """Minimal shared state backend for StateTracker tests."""
    def __init__(self, initial: dict | None = None):
        self.data: dict[str, str] = dict(initial or {})


def _make_tracker(store: SharedStateStore, owner_id: str) -> StateTracker:
    """Build a StateTracker backed by a shared in-memory store."""
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


class TestAcquireJobLock(unittest.TestCase):

    def test_first_instance_acquires_lock(self):
        store = SharedStateStore()
        t = _make_tracker(store, "owner_a")
        result = t.acquire_job_lock("safe_sort", timeout_sec=600)
        self.assertTrue(result, "First instance must acquire the lock")
        self.assertEqual(store.data.get("safe_sort_lock_owner"), "owner_a")

    def test_second_instance_blocked_by_fresh_lock(self):
        store = SharedStateStore()
        t_a = _make_tracker(store, "owner_a")
        t_b = _make_tracker(store, "owner_b")

        t_a.acquire_job_lock("safe_sort", timeout_sec=600)
        result_b = t_b.acquire_job_lock("safe_sort", timeout_sec=600)
        self.assertFalse(result_b, "Second instance must be blocked when lock is fresh")
        # Lock owner must remain owner_a
        self.assertEqual(store.data.get("safe_sort_lock_owner"), "owner_a")

    def test_stale_lock_can_be_taken_over(self):
        stale_at = (datetime.now(timezone.utc) - timedelta(seconds=700)).isoformat()
        store = SharedStateStore({
            "safe_sort_lock_owner": "owner_old",
            "safe_sort_lock_at": stale_at,
        })
        t_new = _make_tracker(store, "owner_new")
        result = t_new.acquire_job_lock("safe_sort", timeout_sec=600)
        self.assertTrue(result, "New instance must be able to take over a stale lock")
        self.assertEqual(store.data.get("safe_sort_lock_owner"), "owner_new")

    def test_lock_not_taken_over_before_timeout(self):
        recent_at = (datetime.now(timezone.utc) - timedelta(seconds=100)).isoformat()
        store = SharedStateStore({
            "safe_sort_lock_owner": "owner_running",
            "safe_sort_lock_at": recent_at,
        })
        t_other = _make_tracker(store, "owner_other")
        result = t_other.acquire_job_lock("safe_sort", timeout_sec=600)
        self.assertFalse(result, "Lock must NOT be taken over before timeout expires")

    def test_same_owner_can_re_acquire(self):
        store = SharedStateStore()
        t = _make_tracker(store, "owner_self")
        t.acquire_job_lock("safe_sort", timeout_sec=600)
        # Same owner tries again (e.g. restart with same owner_id) — must succeed.
        result = t.acquire_job_lock("safe_sort", timeout_sec=600)
        self.assertTrue(result, "Same owner must be able to re-acquire its own lock")

    def test_unreadable_lock_timestamp_treated_as_stale(self):
        store = SharedStateStore({
            "safe_sort_lock_owner": "owner_broken",
            "safe_sort_lock_at": "not-a-timestamp",
        })
        t_new = _make_tracker(store, "owner_new")
        result = t_new.acquire_job_lock("safe_sort", timeout_sec=600)
        self.assertTrue(result, "Unreadable timestamp must be treated as stale → lock takeover")

    def test_multiple_jobs_have_independent_locks(self):
        """Locks for different job names must not interfere."""
        store = SharedStateStore()
        t = _make_tracker(store, "owner_a")

        r1 = t.acquire_job_lock("safe_sort", timeout_sec=600)
        r2 = t.acquire_job_lock("apply_sort", timeout_sec=600)
        r3 = t.acquire_job_lock("apply_renames", timeout_sec=600)
        self.assertTrue(r1)
        self.assertTrue(r2)
        self.assertTrue(r3)
        self.assertEqual(store.data.get("safe_sort_lock_owner"), "owner_a")
        self.assertEqual(store.data.get("apply_sort_lock_owner"), "owner_a")
        self.assertEqual(store.data.get("apply_renames_lock_owner"), "owner_a")

    def test_acquire_job_lock_has_toctou_fence(self):
        """P1.5 / RISK-1: acquire_job_lock must sleep 0.5s between flush and reload."""
        from unittest.mock import patch
        store = SharedStateStore()
        t = _make_tracker(store, "owner_fence")
        sleep_calls = []
        with patch("shared.state_helpers.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            t.acquire_job_lock("safe_sort", timeout_sec=600)
        self.assertIn(0.5, sleep_calls,
                      "acquire_job_lock must call time.sleep(0.5) for TOCTOU fence")


class TestReleaseJobLock(unittest.TestCase):

    def test_release_clears_own_lock(self):
        store = SharedStateStore()
        t = _make_tracker(store, "owner_c")
        t.acquire_job_lock("apply_sort", timeout_sec=600)
        self.assertEqual(store.data.get("apply_sort_lock_owner"), "owner_c")

        t.release_job_lock("apply_sort")
        self.assertEqual(store.data.get("apply_sort_lock_owner", ""), "",
                         "Lock owner must be cleared after release")
        self.assertEqual(store.data.get("apply_sort_lock_at", ""), "")

    def test_release_does_not_clear_foreign_lock(self):
        store = SharedStateStore({
            "apply_sort_lock_owner": "owner_foreign",
            "apply_sort_lock_at": datetime.now(timezone.utc).isoformat(),
        })
        t_local = _make_tracker(store, "owner_local")
        t_local.release_job_lock("apply_sort")
        # Foreign lock must remain intact
        self.assertEqual(store.data.get("apply_sort_lock_owner"), "owner_foreign",
                         "release must not clear a lock held by a different instance")

    def test_lock_can_be_acquired_after_release(self):
        store = SharedStateStore()
        t_a = _make_tracker(store, "owner_a")
        t_b = _make_tracker(store, "owner_b")

        t_a.acquire_job_lock("safe_sort", timeout_sec=600)
        t_a.release_job_lock("safe_sort")

        result_b = t_b.acquire_job_lock("safe_sort", timeout_sec=600)
        self.assertTrue(result_b, "Lock must be acquirable after the previous holder releases it")
        self.assertEqual(store.data.get("safe_sort_lock_owner"), "owner_b")


class TestJobLockWiringInScripts(unittest.TestCase):
    """Structural regression: downstream scripts must call acquire/release."""

    def _read(self, rel_path: str) -> str:
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        p = root / rel_path
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def test_safe_sort_wires_acquire(self):
        code = self._read("main_safe_sort.py")
        self.assertIn("acquire_job_lock", code,
                      "main_safe_sort.py must call acquire_job_lock")
        self.assertIn("release_job_lock", code,
                      "main_safe_sort.py must call release_job_lock")

    def test_apply_sort_wires_acquire(self):
        code = self._read("main_apply_sort.py")
        self.assertIn("acquire_job_lock", code,
                      "main_apply_sort.py must call acquire_job_lock")
        self.assertIn("release_job_lock", code,
                      "main_apply_sort.py must call release_job_lock")

    def test_apply_renames_wires_acquire(self):
        code = self._read("main_apply_renames.py")
        self.assertIn("acquire_job_lock", code,
                      "main_apply_renames.py must call acquire_job_lock")
        self.assertIn("release_job_lock", code,
                      "main_apply_renames.py must call release_job_lock")


if __name__ == "__main__":
    unittest.main()
