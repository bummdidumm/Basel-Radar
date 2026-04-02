import unittest
import tempfile
import json
from pathlib import Path
from personal_brain.runtime import PersonalBrainRuntime

class TestEndToEndConsistency(unittest.TestCase):
    def test_e2e_rename_no_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))

            item_v1 = {
                "file_id": "file-123",
                "checksum_sha256": "abc",
                "source_path": "/drive/folderA/chat.json",
                "source_path_rel": "folderA/chat.json",
                "original_filename": "chat.json",
                "mime": "application/json",
                "ext": ".json",
                "content": {"items": [{"title": "test", "record_type": "generic_json_export"}]}
            }

            runtime.process_sources([item_v1])

            out = Path(td) / "20_index" / "published"
            sources = [json.loads(l) for l in (out / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(sources), 1)

            # Move and rename
            item_v2 = dict(item_v1)
            item_v2["source_path"] = "/drive/folderB/renamed_chat.json"
            item_v2["source_path_rel"] = "folderB/renamed_chat.json"
            item_v2["original_filename"] = "renamed_chat.json"

            runtime.process_sources([item_v2])

            sources2 = [json.loads(l) for l in (out / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(sources2), 1, "Duplicate source created instead of merge.")

            master_index = out / "CURRENT_personal_brain_master_index.json"
            self.assertTrue(master_index.exists())

            master_data = json.loads(master_index.read_text(encoding="utf-8"))
            self.assertEqual(len(master_data["sources"]), 1)
            self.assertEqual(master_data["sources"][0]["source_path_rel"], "folderB/renamed_chat.json")

if __name__ == "__main__":
    unittest.main()
