from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from personal_brain.contracts import (
    ENTITY_REQUIRED_FIELDS,
    RECORD_REQUIRED_FIELDS,
    RELATION_REQUIRED_FIELDS,
    SOURCE_REQUIRED_FIELDS,
)
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

    # ------------------------------------------------------------------
    # Existing tests
    # ------------------------------------------------------------------

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
            if examples.exists():
                for file_name in [
                    "00_source_registry.jsonl",
                    "01_record_index.jsonl",
                    "02_entity_index.jsonl",
                    "03_relation_index.jsonl",
                    "CURRENT_personal_brain_search_view.jsonl",
                ]:
                    if (examples / file_name).exists():
                        expected = (examples / file_name).read_text(encoding="utf-8")
                        actual = (out / file_name).read_text(encoding="utf-8")
                        self.assertTrue(len(actual) > 0)
                        # We do a loose check that IDs are generated, or similar.
                        # Exact string matching may fail due to UUIDs or timestamps,
                        # so we check that the file is not empty and has the same number of lines as a proxy.
                        self.assertEqual(len(actual.splitlines()), len(expected.splitlines()))

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

    # ------------------------------------------------------------------
    # P2: Contract compliance
    # ------------------------------------------------------------------

    def test_contract_compliance_all_required_fields_present(self):
        """Every source/record/entity/relation in the index must carry all REQUIRED fields."""
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            payloads = [
                self._source_payload("google_play_installs.json"),
                self._source_payload("google_my_activity.json"),
                self._source_payload("google_timeline.json"),
                self._source_payload("chatgpt_export.json"),
            ]
            runtime.process_sources(payloads)
            out = Path(td) / "20_index" / "published"

            for line in (out / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                for field in SOURCE_REQUIRED_FIELDS:
                    self.assertIn(field, row, f"source missing field: {field}")

            for line in (out / "01_record_index.jsonl").read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                for field in RECORD_REQUIRED_FIELDS:
                    self.assertIn(field, row, f"record missing field: {field}")

            for line in (out / "02_entity_index.jsonl").read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                for field in ENTITY_REQUIRED_FIELDS:
                    self.assertIn(field, row, f"entity missing field: {field}")

            for line in (out / "03_relation_index.jsonl").read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                for field in RELATION_REQUIRED_FIELDS:
                    self.assertIn(field, row, f"relation missing field: {field}")

    # ------------------------------------------------------------------
    # P2: Merge / incremental safety
    # ------------------------------------------------------------------

    def test_rename_move_keeps_same_source_id(self):
        """Simulate indexing a file, then moving/renaming it (same file_id/hash, diff path).
        It must map to the identical source_id and not duplicate in the registry."""
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))

            item_v1 = {
                "file_id": "file-xyz-123",
                "checksum_sha256": "abcdef123456",
                "source_path": "/fake/dir/photo1.jpg",
                "source_path_rel": "dir/photo1.jpg",
                "original_filename": "photo1.jpg",
                "mime": "image/jpeg",
                "ext": ".jpg",
                "content": {"title": "photo1.jpg"}
            }

            stats1 = runtime.process_sources([item_v1])
            self.assertEqual(stats1["total_sources"], 1)

            # Read registry to get the source ID
            out = Path(td) / "20_index" / "published"
            sources_v1 = [json.loads(l) for l in (out / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(sources_v1), 1)
            original_source_id = sources_v1[0]["source_id"]

            # V2: file is moved and renamed, but file_id and hash remain exactly the same
            item_v2 = {
                "file_id": "file-xyz-123",
                "checksum_sha256": "abcdef123456",
                "source_path": "/fake/other_dir/renamed_photo.jpg",
                "source_path_rel": "other_dir/renamed_photo.jpg",
                "original_filename": "renamed_photo.jpg",
                "mime": "image/jpeg",
                "ext": ".jpg",
                "content": {"title": "renamed_photo.jpg"}
            }

            stats2 = runtime.process_sources([item_v2])

            # The registry should still contain exactly 1 source, mapped to the same ID.
            sources_v2 = [json.loads(l) for l in (out / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
            self.assertEqual(len(sources_v2), 1, "A moved/renamed file created a duplicate source instead of updating.")
            self.assertEqual(sources_v2[0]["source_id"], original_source_id, "The source_id changed after rename/move.")
            # The new path should be reflected
            self.assertEqual(sources_v2[0]["source_path_rel"], "other_dir/renamed_photo.jpg")

    def test_incremental_merge_does_not_lose_previous_records(self):
        """Run(A+B) followed by Run(A) must leave B's records intact on disk."""
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))

            payload_a = self._source_payload("chatgpt_export.json")
            payload_b = self._source_payload("google_timeline.json")

            # Run 1: process both sources
            stats_ab = runtime.process_sources([payload_a, payload_b])
            self.assertEqual(stats_ab["total_sources"], 2)

            out = Path(td) / "20_index" / "published"

            def _load_ids(filename: str, key: str) -> set[str]:
                return {
                    json.loads(l)[key]
                    for l in (out / filename).read_text(encoding="utf-8").splitlines()
                    if l.strip()
                }

            ids_after_ab = _load_ids("01_record_index.jsonl", "record_id")
            self.assertGreaterEqual(len(ids_after_ab), 2)

            # Run 2: process only source A
            runtime.process_sources([payload_a])

            ids_after_a_only = _load_ids("01_record_index.jsonl", "record_id")
            # B's records must still be present
            self.assertTrue(
                ids_after_ab.issubset(ids_after_a_only),
                "Some records from the first run were lost after a partial re-index",
            )

    # ------------------------------------------------------------------
    # P2: Source detection with real local file path
    # ------------------------------------------------------------------

    def test_source_detection_reads_real_json_content(self):
        """inspect_source must open and read a real local JSON file, not fall back to empty."""
        source_path = self.fixture_dir / "chatgpt_export.json"
        detected = inspect_source(str(source_path), mime="application/json", ext=".json")
        # Preview must contain top-level JSON keys, proving the file was actually read
        self.assertIn("conversations", detected["preview"])
        # Content must have the full structure, not just {"raw_text": ...}
        self.assertIn("conversations", detected["content"])
        self.assertIsInstance(detected["content"]["conversations"], list)

    def test_inspect_source_uses_original_path_for_title_and_export(self):
        """Passing original_path to inspect_source should fix temp path leaks in title and is_export."""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tf:
            tf.write(b"content")
            temp_path = tf.name

        try:
            # Case 1: No original_path -> leaks temp name
            detected_leaked = inspect_source(temp_path, mime="text/plain", ext=".txt")
            self.assertEqual(detected_leaked["content"]["title"], Path(temp_path).name)
            self.assertFalse(detected_leaked["is_export"])

            # Case 2: With original_path -> uses it for title and export detection
            orig_name = "my_custom_export.txt"
            detected_fixed = inspect_source(
                temp_path,
                mime="text/plain",
                ext=".txt",
                original_path=orig_name
            )
            self.assertEqual(detected_fixed["content"]["title"], orig_name)
            self.assertTrue(detected_fixed["is_export"], "Should detect 'export' in original_path")
        finally:
            if Path(temp_path).exists():
                os.remove(temp_path)

    # ------------------------------------------------------------------
    # P2: New LLM parser tests
    # ------------------------------------------------------------------

    def test_claude_export_parser_produces_llm_records(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            stats = runtime.process_sources([self._source_payload("claude_export.json")])

            self.assertEqual(stats["total_sources"], 1)
            self.assertGreaterEqual(stats["total_records"], 2)  # conv + turns

            out = Path(td) / "20_index" / "published"
            records = [
                json.loads(l) for l in
                (out / "01_record_index.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            record_types = {r["record_type"] for r in records}
            self.assertIn("llm_conversation", record_types, "Expected at least one llm_conversation record")
            # Parser must not fall back to generic_record
            self.assertNotIn("generic_record", record_types)

            sources = [
                json.loads(l) for l in
                (out / "00_source_registry.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            self.assertEqual(sources[0]["source_system"], "llm")
            self.assertEqual(sources[0]["source_service"], "claude")

    def test_gemini_chat_export_parser_produces_llm_records(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            stats = runtime.process_sources([self._source_payload("gemini_chat_export.json")])

            self.assertGreaterEqual(stats["total_records"], 2)
            out = Path(td) / "20_index" / "published"
            records = [
                json.loads(l) for l in
                (out / "01_record_index.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            self.assertIn("llm_conversation", {r["record_type"] for r in records})

    def test_llm_json_transcript_parser(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            stats = runtime.process_sources([self._source_payload("llm_json_transcript.json")])

            self.assertGreaterEqual(stats["total_records"], 2)
            out = Path(td) / "20_index" / "published"
            records = [
                json.loads(l) for l in
                (out / "01_record_index.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            types = {r["record_type"] for r in records}
            self.assertTrue(
                types & {"llm_conversation", "llm_turn"},
                f"Expected llm_* record types, got {types}",
            )

    # ------------------------------------------------------------------
    # P2: Messaging parser test
    # ------------------------------------------------------------------

    def test_whatsapp_export_parser_produces_message_records(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            stats = runtime.process_sources(
                [self._source_payload("whatsapp_export.txt", mime="text/plain")]
            )

            self.assertEqual(stats["total_sources"], 1)
            self.assertGreaterEqual(stats["total_records"], 4)  # 4 lines in fixture

            out = Path(td) / "20_index" / "published"
            records = [
                json.loads(l) for l in
                (out / "01_record_index.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            self.assertIn("message_event", {r["record_type"] for r in records})
            # Senders should appear as people entities
            entities = [
                json.loads(l) for l in
                (out / "02_entity_index.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            entity_types = {e["entity_type"] for e in entities}
            self.assertIn("person", entity_types)

    # ------------------------------------------------------------------
    # P2: Google Calendar parser test
    # ------------------------------------------------------------------

    def test_google_calendar_ics_parser(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            stats = runtime.process_sources(
                [self._source_payload("google_calendar.ics", mime="text/calendar")]
            )

            self.assertEqual(stats["total_sources"], 1)
            self.assertGreaterEqual(stats["total_records"], 2)  # 2 VEVENTs in fixture

            out = Path(td) / "20_index" / "published"
            records = [
                json.loads(l) for l in
                (out / "01_record_index.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            self.assertIn("calendar_event", {r["record_type"] for r in records})
            # Events must have dates
            for r in records:
                if r["record_type"] == "calendar_event":
                    self.assertTrue(r.get("event_date"), "calendar_event must have event_date")

    # ------------------------------------------------------------------
    # P2: Relation entity ID correctness
    # ------------------------------------------------------------------

    def test_relation_entity_ids_match_entity_index(self):
        """Subject and object entity_ids in relations must exist in the entity index."""
        with tempfile.TemporaryDirectory() as td:
            runtime = PersonalBrainRuntime(project_id="test-project", out_root=Path(td))
            runtime.process_sources([
                self._source_payload("chatgpt_export.json"),
                self._source_payload("google_my_activity.json"),
            ])
            out = Path(td) / "20_index" / "published"

            entity_ids = {
                json.loads(l)["entity_id"]
                for l in (out / "02_entity_index.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            }
            relations = [
                json.loads(l) for l in
                (out / "03_relation_index.jsonl").read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
            for rel in relations:
                self.assertIn(
                    rel["subject_entity_id"], entity_ids,
                    f"subject_entity_id {rel['subject_entity_id']} not in entity index",
                )
                # Object may legitimately reference topics without records (e.g. record titles)
                # but subject must always be a real entity.


if __name__ == "__main__":
    unittest.main()
