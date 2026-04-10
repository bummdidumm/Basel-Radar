import unittest
import main_pass1

class DummyDriveMgr:
    def get_parent_and_name_path(self, f_id, name, parents):
        return "/".join(parents) + "/" + name if parents else name
    def _base_params(self):
        return {}
    def archive_duplicate(self, file_id, parents, archive_folder_id):
        return "SUCCESS_MOCK"

class DummyStateTracker:
    def log_error(self, *args):
        pass
    def append_new_hashes(self, *args):
        pass
    def append_dedupe_reports(self, *args):
        pass
    def flush_duplicate_groups(self, *args):
        pass

class DummyDriveService:
    pass

class TestPass1Incremental(unittest.TestCase):
    def test_incremental_metadata_and_skip(self):
        known_file_details = {}
        state = DummyStateTracker()
        drive_mgr = DummyDriveMgr()
        drive_service = DummyDriveService()
        main_pass1.SKIP_OVER_MB = 1

        # Mock calculate_sha256_streaming
        def mock_calc(*args):
            return "dummy_hash", False
        main_pass1.calculate_sha256_streaming = mock_calc

        # Mock sha lookup
        sha_to_primary_file_id = {}

        # Original insertion
        f1 = {"id": "1", "name": "a.txt", "parents": ["root"], "size": 100, "mimeType": "text/plain"}
        main_pass1.determine_change_type = lambda *args: "NEW"
        main_pass1._process_file_batch(drive_service, drive_mgr, state, [f1], known_file_details, True, "", None, sha_to_primary_file_id)
        self.assertEqual(known_file_details["1"]["name"], "a.txt")

        # Moved
        f1_moved = {"id": "1", "name": "b.txt", "parents": ["sub"], "size": 100, "mimeType": "text/plain"}
        main_pass1.determine_change_type = lambda *args: "UNCHANGED_CONTENT_METADATA_ONLY"
        main_pass1._process_file_batch(drive_service, drive_mgr, state, [f1_moved], known_file_details, False, "", None, sha_to_primary_file_id)
        self.assertEqual(known_file_details["1"]["name"], "b.txt")
        self.assertEqual(known_file_details["1"]["path_display"], "sub/b.txt")
        self.assertEqual(known_file_details["1"]["parent_ids_sorted"], "sub", "ORIGINAL -> MOVED should update parents")
        self.assertIn("effective_mime_type", known_file_details["1"], "ORIGINAL metadata dict must be fully standard")

        # Cross-batch Duplicate
        f1_dup = {"id": "1_dup", "name": "a_copy.txt", "parents": ["root"], "size": 100, "mimeType": "text/plain"}
        main_pass1.determine_change_type = lambda *args: "NEW"
        main_pass1._process_file_batch(drive_service, drive_mgr, state, [f1_dup], known_file_details, False, "", None, sha_to_primary_file_id)
        self.assertEqual(sha_to_primary_file_id.get("dummy_hash"), "1", "Duplicate should correctly map back to the original file_id")

        # Skipped size
        f_large = {"id": "2", "name": "big.bin", "parents": [], "size": 2000000, "mimeType": "application/octet-stream"}
        main_pass1.determine_change_type = lambda *args: "NEW"
        main_pass1._process_file_batch(drive_service, drive_mgr, state, [f_large], known_file_details, False, "", None, sha_to_primary_file_id)
        self.assertEqual(known_file_details["2"]["sha"], "HASH_SKIPPED_SIZE")

        # Second hit of skipped size should be UNCHANGED_CONTENT
        f_large_again = {"id": "2", "name": "big.bin", "parents": [], "size": 2000000, "mimeType": "application/octet-stream"}
        main_pass1.determine_change_type = lambda *args: "UNCHANGED_CONTENT_METADATA_ONLY"
        main_pass1._process_file_batch(drive_service, drive_mgr, state, [f_large_again], known_file_details, False, "", None, sha_to_primary_file_id)
        self.assertEqual(known_file_details["2"]["sha"], "HASH_SKIPPED_SIZE")

if __name__ == "__main__":
    unittest.main()
