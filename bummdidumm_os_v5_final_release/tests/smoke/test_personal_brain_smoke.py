from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from personal_brain.runtime import PersonalBrainRuntime
from personal_brain.source_ingestion import inspect_source


class PersonalBrainSmokeTest(unittest.TestCase):
    def setUp(self):
        self.fixture_dir = Path(__file__).resolve().parents[1] / "fixtures" / "sources"

    def _source_payload(self, filename: str, mime: str = "application/json") -> dict:
        source_path = self.fixture_dir / filename
        detected = inspect_source(str(source_path), mime=mime, ext=source_path.suffix.lower())
        return {
            "source_path": str(source_path),
            "source_path_rel": f"fixtures/{filename}",
            "original_filename": filename,
            "mime": mime,
            "ext": source_path.suffix.lower(),
            "checksum_sha256": f"sha-{filename}",
            "preview": detected["preview"],
            "text_preview": detected["text_preview"],
            "content": detected["content"],
            "is_bundle": detected["is_bundle"],
            "is_archive": detected["is_archive"],
            "is_export": detected["is_export"],
            "raw_ref": str(source_path),
        }

    def test_required_parsers_and_outputs(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            payloads = [
                self._source_payload("google_play_installs.json"),
                self._source_payload("google_my_activity.json"),
                self._source_payload("google_timeline.json"),
                self._source_payload("chatgpt_export.json"),
                self._source_payload("generic_export.json"),
            ]
            stats = runtime.process_sources(payloads)

            self.assertEqual(stats["total_sources"], 5)
            self.assertGreaterEqual(stats["total_records"], 6)
            self.assertGreaterEqual(stats["total_entities"], 6)
            self.assertGreaterEqual(stats["total_relations"], 4)

            out = Path(td) / "20_index" / "published"
            self.assertTrue((out / "00_source_registry.jsonl").exists())
            self.assertTrue((out / "01_record_index.jsonl").exists())
            self.assertTrue((out / "02_entity_index.jsonl").exists())
            self.assertTrue((out / "03_relation_index.jsonl").exists())
            self.assertTrue((out / "04_daily_memory" / "2025-03-15.json").exists())
            self.assertTrue((out / "CURRENT_personal_brain_search_view.jsonl").exists())

            examples = Path(__file__).resolve().parents[1] / "fixtures" / "expected_outputs"
            examples.mkdir(parents=True, exist_ok=True)
            for file_name in [
                "00_source_registry.jsonl",
                "01_record_index.jsonl",
                "02_entity_index.jsonl",
                "03_relation_index.jsonl",
                "CURRENT_personal_brain_search_view.jsonl",
            ]:
                shutil.copy2(out / file_name, examples / file_name)
            shutil.copy2(out / "04_daily_memory" / "2025-03-15.json", examples / "04_daily_memory_2025-03-15.json")

    def test_idempotent_second_run_no_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            payloads = [self._source_payload("google_play_installs.json")]
            first = runtime.process_sources(payloads)
            second = runtime.process_sources(payloads)
            self.assertEqual(first["total_sources"], second["total_sources"])
            self.assertEqual(first["total_records"], second["total_records"])

            out = Path(td) / "20_index" / "published"
            source_lines = (out / "00_source_registry.jsonl").read_text(encoding="utf-8").strip().splitlines()
            record_lines = (out / "01_record_index.jsonl").read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(source_lines), 1)
            self.assertEqual(len(record_lines), 1)

            src = json.loads(source_lines[0])
            rec = json.loads(record_lines[0])
            self.assertTrue(src["source_id"].startswith("src::"))
            self.assertTrue(rec["record_id"].startswith("rec::"))


if __name__ == "__main__":
    unittest.main()
