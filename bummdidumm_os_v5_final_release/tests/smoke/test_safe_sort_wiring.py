import unittest
import tempfile
import json
import os
from pathlib import Path
from unittest.mock import patch
import main_safe_sort

class TestSafeSortWiring(unittest.TestCase):
    def test_safe_sort_wires_semantic_hints(self):
        # We mock sheet_mgr and test if `determine_target` receives the `semantic_topic_hint`
        class MockSheetMgr:
            def __init__(self):
                self.appended = []
            def read_all_rows(self, tab, *args):
                if tab == "Folder_Registry":
                    return [["1", "1", "1", "1", "1"]] # dummy
                return []
            def read_rows_chunked(self, tab, *args, **kwargs):
                # run_utc, run_id, path, name, file_id, mime_type, eff_mime, size, md5, sha, status, change_type, dup_of, archive, sug, link, notes
                row = ["u", "r1", "path/invoice.pdf", "invoice.pdf", "file-123", "application/pdf", "", "0", "", "", "ORIGINAL", "NEW", "", "", "", "", ""]
                yield [row]
            def append_rows(self, tab, rows):
                self.appended.extend(rows)

        class MockState:
            def get_val(self, key):
                if key == "last_successful_run_id":
                    return "r1"
                return None
            def load_known_hashes(self):
                return {}
            def log_error(self, *args):
                pass
            def log_run(self, *args):
                pass

        with tempfile.TemporaryDirectory() as td:
            brain_root = Path(td)
            os.environ["BRAIN_INDEX_ROOT"] = str(brain_root)
            os.environ["CONTROL_SHEET_ID"] = "dummy"

            # Write a dummy semantic hint
            pub_dir = brain_root / "20_index" / "published"
            pub_dir.mkdir(parents=True)
            source = {"file_id": "file-123", "topics": ["invoice"]}
            (pub_dir / "01_record_index.jsonl").write_text(json.dumps(source) + "\n")

            with patch("main_safe_sort.get_user_credentials"), \
                 patch("main_safe_sort.build"), \
                 patch("main_safe_sort.CONTROL_SHEET_ID", "dummy"), \
                 patch("main_safe_sort.SheetManager", return_value=MockSheetMgr()), \
                 patch("main_safe_sort.StateTracker", return_value=MockState()), \
                 patch("main_safe_sort.SortingRules.determine_target", return_value=("40b_referenzen", "reason", "name", "id", "path")) as mock_det:

                main_safe_sort.run_safe_sort()

                mock_det.assert_called_once()
                call_arg = mock_det.call_args[0][0]
                self.assertEqual(call_arg["semantic_topic_hint"], "invoice", "Semantic hint not wired to determine_target")

if __name__ == "__main__":
    unittest.main()
