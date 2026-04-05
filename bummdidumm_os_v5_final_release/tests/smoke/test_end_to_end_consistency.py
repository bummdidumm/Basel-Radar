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
            sources = [json.loads(line) for line in (out / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(sources), 1)

            # Move and rename
            item_v2 = dict(item_v1)
            item_v2["source_path"] = "/drive/folderB/renamed_chat.json"
            item_v2["source_path_rel"] = "folderB/renamed_chat.json"
            item_v2["original_filename"] = "renamed_chat.json"

            runtime.process_sources([item_v2])

            sources2 = [json.loads(line) for line in (out / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(sources2), 1, "Duplicate source created instead of merge.")

            master_index = out / "CURRENT_personal_brain_master_index.json"
            self.assertTrue(master_index.exists())

            master_data = json.loads(master_index.read_text(encoding="utf-8"))
            self.assertEqual(len(master_data["sources"]), 1)
            self.assertEqual(master_data["sources"][0]["source_path_rel"], "folderB/renamed_chat.json")

    def test_e2e_no_temp_paths_leaked(self):
        import os
        from main_pass2 import _build_personal_brain_sources
        from shared.models import FileRecord

        class DummyDrive:
            def files(self):
                return self
            def get_media(self, **kwargs):
                class DummyMedia:
                    def next_chunk(self): return None, True
                return DummyMedia()

        rec = FileRecord(
            file_id="123",
            name="test_bundle.zip",
            path_display="/drive/test_bundle.zip",
            mime_type="application/zip",
            size_bytes=1000,
            status="scanned",
            run_utc="2025-03-15T12:00:00Z"
        )

        # For simplicity, we create a real ZIP file
        import zipfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as zf:
            with zipfile.ZipFile(zf, "w") as z:
                z.writestr("test_sub.json", '{"name": "test data"}')
            temp_zip_path = zf.name

        try:
            # Override _download_drive_file_to_tmp locally to return our temp zip
            import main_pass2
            original_download = main_pass2._download_drive_file_to_tmp
            main_pass2._download_drive_file_to_tmp = lambda *args: temp_zip_path

            try:
                sources = _build_personal_brain_sources([rec], DummyDrive(), False)
            finally:
                main_pass2._download_drive_file_to_tmp = original_download

            self.assertTrue(len(sources) > 0)

            # The outer bundle
            bundle_source = next((s for s in sources if s["original_filename"] == "test_bundle.zip"), None)
            self.assertIsNotNone(bundle_source)
            self.assertEqual(bundle_source["source_path"], "/drive/test_bundle.zip")
            self.assertEqual(bundle_source["content"]["title"], "test_bundle.zip")
            self.assertNotIn("tmp", bundle_source["source_path"])

            # The inner file
            inner_source = next((s for s in sources if s["original_filename"] == "test_sub.json"), None)
            self.assertIsNotNone(inner_source)
            self.assertEqual(inner_source["source_path"], "/drive/test_bundle.zip/test_sub.json")
            self.assertEqual(inner_source["content"]["title"], "test_sub.json")
            self.assertNotIn("tmp", inner_source["source_path"])
            self.assertNotIn("tmp", inner_source["content"].get("title", ""))

            # Verify no path traversal in inner source paths
            for s in sources:
                self.assertNotIn("..", s["source_path"], "Path traversal found in source_path")
                self.assertNotIn("..", s["source_path_rel"], "Path traversal found in source_path_rel")
                self.assertNotIn("..", s["file_id"], "Path traversal found in file_id")

        finally:
            if os.path.exists(temp_zip_path):
                os.remove(temp_zip_path)

if __name__ == "__main__":
    unittest.main()
