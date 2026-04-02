import unittest
import tempfile
import json
import os
import zipfile
from pathlib import Path
from shared.models import FileRecord
from main_pass2 import _build_personal_brain_sources
from personal_brain.runtime import PersonalBrainRuntime

class DummyDriveService:
    def files(self):
        return self
    def get_media(self, fileId, **kwargs):
        class MockRequest:
            def execute(self):
                pass
        return MockRequest()

from googleapiclient.http import MediaIoBaseDownload
import io

# We need to mock _download_drive_file_to_tmp because the real one uses googleapiclient.http
def mock_download(drive_service, file_id, size_bytes, enable_shared_drives):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip" if file_id == "zip-123" else ".json") as tf:
        if file_id == "zip-123":
            with zipfile.ZipFile(tf.name, "w") as z:
                # the IG parser specifically matches "instagram" and "messages"
                z.writestr("instagram/messages.json", json.dumps({"messages": [{"sender_name": "Bob", "content": "Hi", "timestamp_ms": 1600000000000}]}))
        else:
            tf.write(b'{"title": "dummy", "record_type": "generic_json_export"}')
        return tf.name

from unittest.mock import patch

class TestPipelineE2E(unittest.TestCase):
    @patch("main_pass2._download_drive_file_to_tmp", side_effect=mock_download)
    def test_pipeline_e2e_rename_and_zip(self, mock_dl):
        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td)

            # V1: Initial scan (plain json + a zip archive)
            rec1 = FileRecord(
                file_id="file-1",
                name="chat.json",
                path_display="dir/chat.json",
                mime_type="application/json",
                sha256="hash1",
                size_bytes=100,
                status="ORIGINAL"
            )
            rec2 = FileRecord(
                file_id="zip-123",
                name="takeout.zip",
                path_display="dir/takeout.zip",
                mime_type="application/zip",
                sha256="hash2",
                size_bytes=5000,
                status="ORIGINAL"
            )

            drive_service = DummyDriveService()
            sources_v1 = _build_personal_brain_sources([rec1, rec2], drive_service, False)

            # Sub-files from zip should be extracted
            self.assertGreater(len(sources_v1), 2)

            # Assert that no temporary paths leak into the source dict paths
            for s in sources_v1:
                self.assertNotIn("/tmp/", s["source_path"])
                self.assertNotIn("/tmp/", s["source_path_rel"])

            # Find the inner zip source correctly
            inner_src = next(s for s in sources_v1 if s["file_id"] == "zip-123_instagram/messages.json")
            self.assertEqual(inner_src["source_path"], "dir/takeout.zip/instagram/messages.json")
            self.assertEqual(inner_src["source_path_rel"], "dir/takeout.zip/instagram/messages.json")

            runtime = PersonalBrainRuntime(project_id="test-project", out_root=out_root)
            runtime.process_sources(sources_v1)

            pub = out_root / "20_index" / "published"
            sources_disk = [json.loads(l) for l in (pub / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(sources_disk), len(sources_v1))

            # V2: Rename file-1
            rec1_v2 = FileRecord(
                file_id="file-1",
                name="renamed_chat.json",
                path_display="new_dir/renamed_chat.json",
                mime_type="application/json",
                sha256="hash1",
                size_bytes=100,
                status="RENAMED"
            )

            sources_v2 = _build_personal_brain_sources([rec1_v2], drive_service, False)
            runtime.process_sources(sources_v2)

            sources_disk_v2 = [json.loads(l) for l in (pub / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

            # The rename shouldn't duplicate file-1
            self.assertEqual(len(sources_disk_v2), len(sources_v1))

            # Find file-1
            file1_src = next(s for s in sources_disk_v2 if s["checksum_sha256"] == "hash1")
            self.assertEqual(file1_src["source_path_rel"], "new_dir/renamed_chat.json")

            # Master index must be fully generated
            master_idx = pub / "CURRENT_personal_brain_master_index.json"
            self.assertTrue(master_idx.exists())
            master_data = json.loads(master_idx.read_text(encoding="utf-8"))
            self.assertEqual(len(master_data["sources"]), len(sources_disk_v2))

            # Verify the inner zip message got parsed
            records = master_data["records"]
            # The payload we provided is `{"messages": [{"sender_name": "Bob", "content": "Hi", "timestamp_ms": 1600000000000}]}`
            # which might map to message_event (Instagram parser) or llm_conversation (NotebookLM/etc).
            # In our specific test, it hit a fallback or the instagram parser correctly.
            parsed_records = [r for r in records if r.get("record_type") in ("message_event", "llm_conversation", "llm_turn")]
            self.assertGreaterEqual(len(parsed_records), 1)

if __name__ == "__main__":
    unittest.main()
