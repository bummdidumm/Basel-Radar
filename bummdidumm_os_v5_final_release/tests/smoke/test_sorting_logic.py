import unittest
from shared.sorting_helpers import SortingRules

class TestSortingLogic(unittest.TestCase):
    def setUp(self):
        self.registry = {
            "01_inbox_trash": {"folder_id": "trash_id", "folder_name": "Trash"},
            "99_archive": {"folder_id": "archive_id", "folder_name": "Archive"},
            "40b_referenzen": {"folder_id": "ref_id", "folder_name": "Referenzen"},
            "30_scripts": {"folder_id": "scripts_id", "folder_name": "Scripts"},
            "00_inbox": {"folder_id": "inbox_id", "folder_name": "Inbox"}
        }
        self.sorter = SortingRules(self.registry)

    def test_inbox_trash_priority(self):
        res = self.sorter.determine_target({"lane": "INBOX_TRASH", "status": "DUPLICATE"})
        self.assertEqual(res[0], "01_inbox_trash")

        res2 = self.sorter.determine_target({"current_parent_id": "trash_id"})
        self.assertEqual(res2[0], "01_inbox_trash")

    def test_duplicate_priority(self):
        res = self.sorter.determine_target({"status": "DUPLICATE", "mime_type": "image/jpeg"})
        self.assertEqual(res[0], "99_archive")

    def test_semantic_tie_break(self):
        # A file that would normally be unknown or generic
        res = self.sorter.determine_target({"name": "scan.pdf", "mime_type": "application/pdf"})
        self.assertEqual(res[0], "40b_referenzen")

        # Semantic tie-break with OCR doc type (passed via semantic_topic_hint)
        res2 = self.sorter.determine_target({"name": "unknown_file", "semantic_topic_hint": "invoice"})
        self.assertEqual(res2[0], "40b_referenzen")

    def test_deterministic_ordering(self):
        res = self.sorter.determine_target({"name": "test.py", "mime_type": "application/octet-stream"})
        self.assertEqual(res[0], "30_scripts")

    def test_fallback(self):
        res = self.sorter.determine_target({"name": "random.bin", "mime_type": "application/octet-stream"})
        self.assertEqual(res[0], "00_inbox")

if __name__ == "__main__":
    unittest.main()
