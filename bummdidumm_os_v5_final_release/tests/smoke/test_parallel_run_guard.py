import unittest
from datetime import datetime, timezone, timedelta
from unittest import mock

import main_pass1
from main_pass1 import _acquire_lease_or_abort, _touch_lease, run_pass1


class SharedStateStore:
    def __init__(self, initial: dict):
        self.data = dict(initial)


class DummyStateTracker:
    def __init__(self, shared_store: SharedStateStore, owner_id: str, run_id: str, force_lose_after_flush: bool = False):
        self._shared = shared_store
        self._state = dict(shared_store.data)
        self.owner_id = owner_id
        self.run_id = run_id
        self.force_lose_after_flush = force_lose_after_flush

    def get_val(self, key):
        return self._state.get(key)

    def set_val(self, key, val):
        self._state[key] = val

    def flush_state(self):
        self._shared.data = dict(self._state)
        if self.force_lose_after_flush:
            self._shared.data["lease_owner_id"] = "owner_other_won"

    def reload_state(self):
        self._state = dict(self._shared.data)

    def load_known_hashes(self):
        return {}

    def compact_hash_index(self):
        pass

    def compact_reports(self):
        pass

    def log_run(self, *args, **kwargs):
        pass

    def log_error(self, *args, **kwargs):
        pass

    # T-1 fix: stubs needed for a full success-path run_pass1() invocation
    def append_new_hashes(self, records):
        pass

    def append_dedupe_reports(self, records):
        pass

    def flush_duplicate_groups(self, groups):
        pass


class TestParallelRunGuardHelpers(unittest.TestCase):
    def test_active_foreign_lease_blocks_even_when_phase_idle(self):
        recent = datetime.now(timezone.utc).isoformat()
        shared = SharedStateStore(
            {
                "current_phase": "IDLE",
                "lease_owner_id": "owner_a",
                "lease_heartbeat_at": recent,
                "run_id": "run_a",
            }
        )
        state = DummyStateTracker(shared, owner_id="owner_b", run_id="run_b")
        log = mock.Mock()

        self.assertFalse(_acquire_lease_or_abort(state, log, lease_timeout_sec=3600))

    def test_stale_lease_can_be_taken_over(self):
        stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        shared = SharedStateStore(
            {
                "current_phase": "WHATEVER",
                "lease_owner_id": "owner_old",
                "lease_heartbeat_at": stale,
                "run_id": "run_old",
            }
        )
        state = DummyStateTracker(shared, owner_id="owner_new", run_id="run_new")
        log = mock.Mock()

        self.assertTrue(_acquire_lease_or_abort(state, log, lease_timeout_sec=3600))
        self.assertEqual(shared.data.get("lease_owner_id"), "owner_new")
        self.assertEqual(shared.data.get("run_id"), "run_old")
        self.assertEqual(state.run_id, "run_old")

    def test_same_owner_can_continue(self):
        recent = datetime.now(timezone.utc).isoformat()
        shared = SharedStateStore(
            {
                "lease_owner_id": "owner_same",
                "lease_heartbeat_at": recent,
                "run_id": "run_prev",
            }
        )
        state = DummyStateTracker(shared, owner_id="owner_same", run_id="run_new")
        log = mock.Mock()

        self.assertTrue(_acquire_lease_or_abort(state, log, lease_timeout_sec=3600))
        self.assertEqual(shared.data.get("lease_owner_id"), "owner_same")

    def test_second_instance_loses_after_reload_verification(self):
        shared = SharedStateStore({})
        state = DummyStateTracker(
            shared,
            owner_id="owner_candidate",
            run_id="run_candidate",
            force_lose_after_flush=True,
        )
        log = mock.Mock()

        self.assertFalse(_acquire_lease_or_abort(state, log, lease_timeout_sec=3600))
        self.assertEqual(shared.data.get("lease_owner_id"), "owner_other_won")

    def test_touch_lease_does_not_overwrite_foreign_owner(self):
        shared = SharedStateStore(
            {
                "lease_owner_id": "owner_foreign",
                "lease_heartbeat_at": "2026-01-01T00:00:00+00:00",
                "run_id": "run_foreign",
            }
        )
        state = DummyStateTracker(shared, owner_id="owner_local", run_id="run_local")

        result = _touch_lease(state)

        self.assertFalse(result)
        self.assertEqual(shared.data.get("lease_owner_id"), "owner_foreign")
        self.assertEqual(shared.data.get("run_id"), "run_foreign")

    def test_resume_without_lease_adopts_existing_run_id(self):
        shared = SharedStateStore(
            {
                "current_phase": "DELTA_FETCH",
                "lease_owner_id": "",
                "run_id": "run_resume_001",
            }
        )
        state = DummyStateTracker(shared, owner_id="owner_resume", run_id="run_new")
        log = mock.Mock()

        self.assertTrue(_acquire_lease_or_abort(state, log, lease_timeout_sec=3600))
        self.assertEqual(state.run_id, "run_resume_001")
        self.assertEqual(shared.data.get("run_id"), "run_resume_001")


class TestParallelRunGuardIntegration(unittest.TestCase):
    def test_pre_phase_foreign_lease_blocks_run_start(self):
        recent = datetime.now(timezone.utc).isoformat()
        shared = SharedStateStore(
            {
                "current_phase": "IDLE",
                "lease_owner_id": "owner_instance_a",
                "lease_heartbeat_at": recent,
                "run_id": "run_instance_a",
            }
        )
        state_b = DummyStateTracker(shared, owner_id="owner_instance_b", run_id="run_instance_b")

        old_creds = main_pass1.get_user_credentials
        old_build = main_pass1.build
        old_state_tracker = main_pass1.StateTracker
        old_sheet_mgr = main_pass1.SheetManager
        old_drive_mgr = main_pass1.DriveManager
        old_control_sheet = main_pass1.CONTROL_SHEET_ID

        main_pass1.get_user_credentials = lambda: None
        main_pass1.build = lambda *args, **kwargs: object()
        main_pass1.SheetManager = lambda *args, **kwargs: mock.Mock()
        main_pass1.StateTracker = lambda *args, **kwargs: state_b
        mocked_drive_mgr = mock.Mock()
        main_pass1.DriveManager = lambda *args, **kwargs: mocked_drive_mgr
        main_pass1.CONTROL_SHEET_ID = "123"

        try:
            self.assertIsNone(run_pass1())
            mocked_drive_mgr.walk_recursive_chunked.assert_not_called()
            mocked_drive_mgr.fetch_delta_chunk.assert_not_called()
        finally:
            main_pass1.get_user_credentials = old_creds
            main_pass1.build = old_build
            main_pass1.StateTracker = old_state_tracker
            main_pass1.SheetManager = old_sheet_mgr
            main_pass1.DriveManager = old_drive_mgr
            main_pass1.CONTROL_SHEET_ID = old_control_sheet


def _patch_pass1(state, mocked_drive_mgr):
    """Return a dict of {attr: old_val} for monkey-patching main_pass1 and a restore callable."""
    saved = {
        "get_user_credentials": main_pass1.get_user_credentials,
        "build": main_pass1.build,
        "StateTracker": main_pass1.StateTracker,
        "SheetManager": main_pass1.SheetManager,
        "DriveManager": main_pass1.DriveManager,
        "CONTROL_SHEET_ID": main_pass1.CONTROL_SHEET_ID,
    }
    main_pass1.get_user_credentials = lambda: None
    main_pass1.build = lambda *a, **kw: object()
    def _make_sheet_mock(*a, **kw):
        m = mock.Mock()
        m.read_all_rows.return_value = []
        return m
    main_pass1.SheetManager = _make_sheet_mock
    main_pass1.StateTracker = lambda *a, **kw: state
    main_pass1.DriveManager = lambda *a, **kw: mocked_drive_mgr
    main_pass1.CONTROL_SHEET_ID = "sheet_test"
    return saved


def _restore_pass1(saved):
    for k, v in saved.items():
        setattr(main_pass1, k, v)


class TestPass1SuccessPath(unittest.TestCase):
    """T-1: verify BUG-1+2 fix — state values survive _release_lease() after a successful run."""

    def test_initial_scan_state_persisted_after_run(self):
        shared = SharedStateStore({})
        state = DummyStateTracker(shared, owner_id="owner_t1", run_id="run_t1")

        mocked_drive_mgr = mock.Mock()
        mocked_drive_mgr.get_initial_token.return_value = "token_initial_123"
        mocked_drive_mgr.walk_recursive_chunked.return_value = 0

        saved = _patch_pass1(state, mocked_drive_mgr)
        try:
            main_pass1.run_pass1()
        finally:
            _restore_pass1(saved)

        self.assertEqual(shared.data.get("current_phase"), "PASS1_DONE",
                         "current_phase must be PASS1_DONE in the sheet after a successful run")
        self.assertEqual(shared.data.get("ready_for_pass2_run_id"), "run_t1",
                         "ready_for_pass2_run_id must be persisted so Pass 2 can pick it up")
        self.assertEqual(shared.data.get("last_successful_run_id"), "run_t1",
                         "last_successful_run_id must be persisted")
        self.assertFalse(shared.data.get("lease_owner_id"),
                         "lease_owner_id must be cleared after release")

    def test_failed_run_persists_failed_phase(self):
        shared = SharedStateStore({})
        state = DummyStateTracker(shared, owner_id="owner_t1f", run_id="run_t1f")

        mocked_drive_mgr = mock.Mock()
        mocked_drive_mgr.get_initial_token.return_value = "tok"
        mocked_drive_mgr.walk_recursive_chunked.side_effect = RuntimeError("simulated failure")

        saved = _patch_pass1(state, mocked_drive_mgr)
        try:
            with self.assertRaises(RuntimeError):
                main_pass1.run_pass1()
        finally:
            _restore_pass1(saved)

        self.assertEqual(shared.data.get("current_phase"), "PASS1_FAILED",
                         "current_phase must be PASS1_FAILED in the sheet after a failed run")
        self.assertFalse(shared.data.get("lease_owner_id"),
                         "lease_owner_id must be cleared even on failure")


class TestPass1DeltaTokenPersistence(unittest.TestCase):
    """T-2: verify BUG-2 fix — drive_start_page_token is advanced after a delta run."""

    def test_delta_run_advances_page_token(self):
        shared = SharedStateStore({"drive_start_page_token": "old_token"})
        state = DummyStateTracker(shared, owner_id="owner_t2", run_id="run_t2")

        mocked_drive_mgr = mock.Mock()
        # One delta chunk: no file changes, returns newStartPageToken="new_token"
        mocked_drive_mgr.fetch_delta_chunk.return_value = ([], None, "new_token")

        saved = _patch_pass1(state, mocked_drive_mgr)
        try:
            main_pass1.run_pass1()
        finally:
            _restore_pass1(saved)

        self.assertEqual(shared.data.get("drive_start_page_token"), "new_token",
                         "drive_start_page_token must be advanced to the new token")
        self.assertEqual(shared.data.get("in_progress_page_token"), "",
                         "in_progress_page_token must be cleared after a completed delta run")
        self.assertEqual(shared.data.get("current_phase"), "PASS1_DONE")


if __name__ == "__main__":
    unittest.main()
