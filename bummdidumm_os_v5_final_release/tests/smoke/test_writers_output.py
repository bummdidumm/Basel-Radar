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

    def test_exclusion_inheritance(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            from personal_brain.runtime import PersonalBrainRuntime
            runtime = PersonalBrainRuntime("proj", root)
            sources = [
                {"file_id": "p1", "checksum_sha256": "h1", "original_filename": "parent.zip", "mime": "application/zip", "content": {}},
                {"file_id": "c1", "bundle_id": "p1", "checksum_sha256": "h2", "original_filename": "child.txt", "mime": "text/plain", "content": {}}
            ]
            exclusions = {"p1": "EXCLUDED"}
            runtime.process_sources(sources, exclusions)

            master_file = root / "20_index" / "published" / "CURRENT_personal_brain_master_index.json"
            data = json.loads(master_file.read_text(encoding="utf-8"))
            self.assertEqual(len(data["sources"]), 0, "Child should be excluded because parent is excluded")

    def test_writer_merge_durability_partial_reruns(self):
        """Tests atomic writes, count preservation, and partial rerun preservation."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            writer = JsonlWriter(root)

            # Initial run
            writer.write_source_record_entity_relation(
                [{"source_id": "s1", "parser_name": "p1"}, {"source_id": "s2", "parser_name": "p2"}],
                [{"record_id": "r1", "source_id": "s1"}, {"record_id": "r2", "source_id": "s2"}],
                [{"entity_id": "e1", "sources": [{"source_id": "s1"}], "mentions": 5}],
                [{"relation_id": "rel1", "source_id": "s1"}]
            )
            writer.write_reports()

            master_file = writer.published / "CURRENT_personal_brain_master_index.json"
            data = json.loads(master_file.read_text(encoding="utf-8"))
            self.assertEqual(len(data["sources"]), 2)
            self.assertEqual(len(data["entities"]), 1)
            self.assertEqual(data["entities"][0]["mentions"], 5)

            # Partial rerun (only s2 changes, s1 is missing from this delta but should be preserved)
            writer2 = JsonlWriter(root)
            writer2.write_source_record_entity_relation(
                [{"source_id": "s2", "parser_name": "p2_v2"}],
                [{"record_id": "r2", "source_id": "s2", "content": "updated"}],
                [{"entity_id": "e1", "sources": [{"source_id": "s2"}], "mentions": 3}],
                []
            )
            writer2.write_reports()

            data2 = json.loads(master_file.read_text(encoding="utf-8"))
            self.assertEqual(len(data2["sources"]), 2, "s1 should be preserved")

            s2_source = next(s for s in data2["sources"] if s["source_id"] == "s2")
            self.assertEqual(s2_source["parser_name"], "p2_v2", "s2 should be updated")

            r2_record = next(r for r in data2["records"] if r["record_id"] == "r2")
            self.assertEqual(r2_record.get("content"), "updated", "r2 should be updated")

            e1_entity = next(e for e in data2["entities"] if e["entity_id"] == "e1")
            self.assertEqual(e1_entity["mentions"], 8, "Entity mentions should be merged (5 + 3)")
            self.assertEqual(len(e1_entity["sources"]), 2, "Entity sources should be merged")

            self.assertEqual(len(data2["relations"]), 1, "Relation from s1 should be preserved")

if __name__ == "__main__":
    unittest.main()
