import json
import tempfile
import unittest
from pathlib import Path
from personal_brain.writers import JsonlWriter

class TestWritersOutput(unittest.TestCase):
    def test_writers_output(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            writer = JsonlWriter(root)

            # Write some dummy data so the load functions work
            writer.write_source_record_entity_relation(
                [{"source_id": "s1", "parser_name": "parser_generic_txt_export", "source_path": "instagram.txt"}],
                [{"record_id": "r1"}],
                [{"entity_id": "e1"}],
                [{"relation_id": "rel1"}]
            )

            # Setup dummy daily memory and search views directory
            writer.daily_dir.mkdir(parents=True, exist_ok=True)
            (writer.daily_dir / "2025-01-01.json").write_text('{"test": "day"}', encoding="utf-8")

            search_dir = writer.published / "12_search_views"
            search_dir.mkdir(parents=True, exist_ok=True)
            (search_dir / "by_date.jsonl").write_text('{"search_id": "v1"}', encoding="utf-8")

            # Run the report writer which now also builds the master index and quality report
            # Crucially: we pass no arguments to prove it loads from disk rather than using memory inputs.
            writer.write_reports()

            master_file = writer.published / "CURRENT_personal_brain_master_index.json"
            quality_file = writer.published / "CURRENT_personal_brain_quality_report.json"

            self.assertTrue(master_file.exists(), "Master index missing")
            self.assertTrue(quality_file.exists(), "Quality report missing")

            master_data = json.loads(master_file.read_text(encoding="utf-8"))
            self.assertIn("sources", master_data)
            self.assertEqual(len(master_data["sources"]), 1, f"Expected 1 source, got {len(master_data['sources'])}")
            self.assertEqual(master_data["sources"][0]["source_id"], "s1")

            self.assertIn("records", master_data)
            self.assertEqual(len(master_data["records"]), 1)
            self.assertEqual(master_data["records"][0]["record_id"], "r1")

            self.assertIn("entities", master_data)
            self.assertEqual(len(master_data["entities"]), 1)
            self.assertEqual(master_data["entities"][0]["entity_id"], "e1")

            self.assertIn("relations", master_data)
            self.assertEqual(len(master_data["relations"]), 1)
            self.assertEqual(master_data["relations"][0]["relation_id"], "rel1")

            self.assertIn("daily_memory", master_data)
            self.assertIn("2025-01-01", master_data["daily_memory"])
            self.assertIn("search_views", master_data)
            self.assertIn("by_date", master_data["search_views"])

            quality_data = json.loads(quality_file.read_text(encoding="utf-8"))
            self.assertIn("missing_important_parser_families", quality_data)
            self.assertIn("instagram", quality_data["missing_important_parser_families"])
            self.assertEqual(quality_data["generic_fallback_sources"], 1)

    def test_no_internal_keys_in_entity_jsonl(self):
        from personal_brain.runtime import PersonalBrainRuntime
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            # Just create a dummy payload dict directly instead of using a fixture we don't have here.
            payload = {
                "file_id": "dummy-1",
                "original_filename": "dummy.txt",
                "mime": "text/plain",
                "content": {"raw_text": "dummy text"},
                "status": "ORIGINAL",
                "source_path": "dummy.txt"
            }
            runtime.process_sources([payload])
            out = Path(td) / "20_index" / "published"
            for line in (out / "02_entity_index.jsonl").read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                entity = json.loads(line)
                for key in entity:
                    self.assertFalse(key.startswith("_"), f"Internal key '{key}' leaked into entity JSONL")

if __name__ == "__main__":
    unittest.main()
