import unittest
from shared.change_type_logic import check_md5_size_prefilter

class TestChangeTypeLogic(unittest.TestCase):

    def test_prefilter_not_in_known_details(self):
        f = {"id": "new-file"}
        known = {}
        self.assertFalse(check_md5_size_prefilter(f, known))

    def test_prefilter_google_apps_mime(self):
        f = {
            "id": "doc-1",
            "mimeType": "application/vnd.google-apps.document",
            "md5Checksum": "hash1",
            "size": "100"
        }
        known = {
            "doc-1": {"md5": "hash1", "size_bytes": "100"}
        }
        # Native formats should return False (no MD5 available for them normally)
        self.assertFalse(check_md5_size_prefilter(f, known))

    def test_prefilter_exact_match(self):
        f = {
            "id": "file-1",
            "md5Checksum": "hash1",
            "size": "100"
        }
        known = {
            "file-1": {"md5": "hash1", "size_bytes": "100"}
        }
        self.assertTrue(check_md5_size_prefilter(f, known))

    def test_prefilter_md5_mismatch(self):
        f = {
            "id": "file-1",
            "md5Checksum": "hash-new",
            "size": "100"
        }
        known = {
            "file-1": {"md5": "hash-old", "size_bytes": "100"}
        }
        self.assertFalse(check_md5_size_prefilter(f, known))

    def test_prefilter_size_mismatch(self):
        f = {
            "id": "file-1",
            "md5Checksum": "hash1",
            "size": "200"
        }
        known = {
            "file-1": {"md5": "hash1", "size_bytes": "100"}
        }
        self.assertFalse(check_md5_size_prefilter(f, known))

    def test_prefilter_missing_current_md5(self):
        f = {
            "id": "file-1",
            "size": "100"
            # md5Checksum missing
        }
        known = {
            "file-1": {"md5": "hash1", "size_bytes": "100"}
        }
        self.assertFalse(check_md5_size_prefilter(f, known))

    def test_prefilter_missing_cached_md5(self):
        f = {
            "id": "file-1",
            "md5Checksum": "hash1",
            "size": "100"
        }
        known = {
            "file-1": {"size_bytes": "100"}
            # md5 missing
        }
        self.assertFalse(check_md5_size_prefilter(f, known))

    def test_prefilter_size_string_int_flexibility(self):
        f = {
            "id": "file-1",
            "md5Checksum": "hash1",
            "size": 100 # int
        }
        known = {
            "file-1": {"md5": "hash1", "size_bytes": "100"} # str
        }
        self.assertTrue(check_md5_size_prefilter(f, known))

        f2 = {
            "id": "file-2",
            "md5Checksum": "hash2",
            "size": "500" # str
        }
        known2 = {
            "file-2": {"md5": "hash2", "size_bytes": 500} # int
        }
        self.assertTrue(check_md5_size_prefilter(f2, known2))

if __name__ == "__main__":
    unittest.main()
