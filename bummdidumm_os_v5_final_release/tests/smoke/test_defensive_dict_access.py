import unittest
from main_pass1 import _process_file_batch

class DummyDriveService:
    pass

class DummyDriveMgr:
    def get_parent_and_name_path(self, f_id, name, parents): return name
    def _base_params(self): return {}
    def archive_duplicate(self, *args): return "SUCCESS"

class DummyStateTracker:
    def log_error(self, *args): pass
    def append_new_hashes(self, *args): pass
    def append_dedupe_reports(self, *args): pass
    def flush_duplicate_groups(self, *args): pass

class TestDefensiveDictAccess(unittest.TestCase):
    def test_missing_cache_key_does_not_throw_keyerror(self):
        """If determine_change_type returns UNCHANGED_CONTENT_METADATA_ONLY but known_file_details is missing the key, it shouldn't throw KeyError."""
        state = DummyStateTracker()
        drive_mgr = DummyDriveMgr()
        drive_service = DummyDriveService()
        known_file_details = {}  # Empty cache

        files = [{"id": "123", "name": "test.txt", "size": 100}]

        # Patch determine_change_type to force UNCHANGED_CONTENT_METADATA_ONLY even if not in cache (simulating an edge case or manual sheet edit)
        import main_pass1
        old_func = main_pass1.determine_change_type
        main_pass1.determine_change_type = lambda *args: "UNCHANGED_CONTENT_METADATA_ONLY"

        try:
            _process_file_batch(drive_service, drive_mgr, state, files, known_file_details, False, "")
            # If we reach here without KeyError, the test passes
            self.assertIn("123", known_file_details)
            self.assertEqual(known_file_details["123"]["name"], "test.txt")
        finally:
            main_pass1.determine_change_type = old_func

if __name__ == '__main__':
    unittest.main()
