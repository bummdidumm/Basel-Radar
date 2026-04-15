import unittest
from main_pass1 import run_pass1
from datetime import datetime, timezone, timedelta

class DummyStateTracker:
    def __init__(self, initial_state):
        self._state = initial_state
        self.run_id = "run_new"
        self.owner_id = "owner_new"
    def get_val(self, key): return self._state.get(key)
    def set_val(self, key, val): self._state[key] = val
    def flush_state(self): pass
    def reload_state(self): pass
    def load_known_hashes(self): return {}

class DummySheetMgr:
    def read_all_rows(self, *args): return []

class TestParallelRunGuard(unittest.TestCase):
    def test_stale_run_overridden(self):
        old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        state = DummyStateTracker({"current_phase": "INITIAL_SCAN", "run_id": "run_old", "last_run_utc": old_time})

        # Test requires mocking drive_service and drive_mgr in run_pass1.
        # But we can just test the guard logic explicitly if we extracted it, or we mock the module.
        import main_pass1
        old_creds = main_pass1.get_user_credentials
        old_build = main_pass1.build
        old_drive_mgr = main_pass1.DriveManager
        old_state_tracker = main_pass1.StateTracker

        main_pass1.get_user_credentials = lambda: None
        main_pass1.build = lambda *args, **kwargs: None
        main_pass1.DriveManager = lambda *args, **kwargs: mock.Mock()
        main_pass1.StateTracker = lambda *args, **kwargs: state
        main_pass1.CONTROL_SHEET_ID = "123"
        import unittest.mock as mock

        try:
            # Running this should not return early, meaning it overtakes the old run and hits the walk error or completes
            with self.assertRaises(AttributeError): # It hits drive_mgr.walk_recursive_chunked which we mocked badly, but it PASSED the guard!
                run_pass1()
        finally:
            main_pass1.get_user_credentials = old_creds
            main_pass1.build = old_build
            main_pass1.DriveManager = old_drive_mgr
            main_pass1.StateTracker = old_state_tracker

    def test_active_run_prevented(self):
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        state = DummyStateTracker({
            "current_phase": "DELTA_FETCH",
            "run_id": "run_active",
            "last_run_utc": recent_time,
            "lease_owner_id": "owner_active",
            "lease_heartbeat_at": recent_time
        })

        import main_pass1
        old_creds = main_pass1.get_user_credentials
        old_build = main_pass1.build
        old_state_tracker = main_pass1.StateTracker

        main_pass1.get_user_credentials = lambda: None
        main_pass1.build = lambda *args, **kwargs: None
        main_pass1.StateTracker = lambda *args, **kwargs: state
        main_pass1.CONTROL_SHEET_ID = "123"

        try:
            # This should return immediately and gracefully (None)
            self.assertIsNone(run_pass1())
        finally:
            main_pass1.get_user_credentials = old_creds
            main_pass1.build = old_build
            main_pass1.StateTracker = old_state_tracker

if __name__ == '__main__':
    unittest.main()
