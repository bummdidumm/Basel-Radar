"""Tests for PURGED lifecycle semantics in the Personal Brain writers layer.

Covers: entity tombstoning, relation tombstoning, topic hints cleanup, and
stale daily/weekly memory file deletion.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from personal_brain.writers import JsonlWriter


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _write_source_reg(writer: JsonlWriter, sources: list[dict]) -> None:
    """Helper: write source registry without touching other indexes."""
    writer._write_jsonl(writer.published / "00_source_registry.jsonl", sources, "source_id")


class TestEntityTombstoning(unittest.TestCase):
    """Gap-C: entities whose ALL source_ids map to purged file_ids must be removed."""

    def test_entity_tombstoned_when_all_sources_purged(self):
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            # Prime the source registry so purged_source_ids can be derived.
            _write_source_reg(writer, [{"source_id": "src_a", "file_id": "file_a"}])

            # Write an entity whose only source_id is src_a.
            writer.write_source_record_entity_relation(
                sources=[],
                records=[],
                entities=[{
                    "entity_id": "ent_alice",
                    "entity_type": "person",
                    "canonical_name": "alice",
                    "source_ids": ["src_a"],
                }],
                relations=[],
            )
            entities_before = _read_jsonl(writer.published / "02_entity_index.jsonl")
            self.assertEqual(len(entities_before), 1)

            # Now purge file_a — the entity's only source must be tombstoned.
            writer.write_source_record_entity_relation(
                sources=[], records=[], entities=[], relations=[],
                purged_file_ids={"file_a"},
            )
            entities_after = _read_jsonl(writer.published / "02_entity_index.jsonl")
            entity_ids = [e["entity_id"] for e in entities_after]
            self.assertNotIn("ent_alice", entity_ids,
                             "Entity must be tombstoned when all its sources are purged")

    def test_entity_preserved_when_only_some_sources_purged(self):
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            _write_source_reg(writer, [
                {"source_id": "src_a", "file_id": "file_a"},
                {"source_id": "src_b", "file_id": "file_b"},
            ])
            # Entity references two sources.
            writer.write_source_record_entity_relation(
                sources=[],
                records=[],
                entities=[{
                    "entity_id": "ent_bob",
                    "entity_type": "person",
                    "canonical_name": "bob",
                    "source_ids": ["src_a", "src_b"],
                }],
                relations=[],
            )
            # Purge only file_a — entity still has src_b → must survive.
            writer.write_source_record_entity_relation(
                sources=[], records=[], entities=[], relations=[],
                purged_file_ids={"file_a"},
            )
            entities_after = _read_jsonl(writer.published / "02_entity_index.jsonl")
            entity_ids = [e["entity_id"] for e in entities_after]
            self.assertIn("ent_bob", entity_ids,
                          "Entity with surviving sources must NOT be tombstoned")

    def test_entity_with_empty_source_ids_not_tombstoned(self):
        """Malformed entity (empty source_ids) must stream through safely."""
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            _write_source_reg(writer, [{"source_id": "src_x", "file_id": "file_x"}])
            writer.write_source_record_entity_relation(
                sources=[], records=[],
                entities=[{"entity_id": "ent_orphan", "source_ids": []}],
                relations=[],
            )
            writer.write_source_record_entity_relation(
                sources=[], records=[], entities=[], relations=[],
                purged_file_ids={"file_x"},
            )
            entities_after = _read_jsonl(writer.published / "02_entity_index.jsonl")
            self.assertTrue(
                any(e["entity_id"] == "ent_orphan" for e in entities_after),
                "Entity with empty source_ids must NOT be silently tombstoned",
            )


class TestRelationTombstoning(unittest.TestCase):
    """Gap-D: relations whose ALL source_ids map to purged files must be removed."""

    def test_relation_tombstoned_when_all_sources_purged(self):
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            _write_source_reg(writer, [{"source_id": "src_r", "file_id": "file_r"}])
            writer.write_source_record_entity_relation(
                sources=[],
                records=[],
                entities=[],
                relations=[{
                    "relation_id": "rel_1",
                    "source_ids": ["src_r"],
                    "predicate": "mentions",
                }],
            )
            rels_before = _read_jsonl(writer.published / "03_relation_index.jsonl")
            self.assertEqual(len(rels_before), 1)

            writer.write_source_record_entity_relation(
                sources=[], records=[], entities=[], relations=[],
                purged_file_ids={"file_r"},
            )
            rels_after = _read_jsonl(writer.published / "03_relation_index.jsonl")
            self.assertEqual(len(rels_after), 0,
                             "Relation must be tombstoned when its only source is purged")

    def test_relation_preserved_when_only_some_sources_purged(self):
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            _write_source_reg(writer, [
                {"source_id": "src_p", "file_id": "file_p"},
                {"source_id": "src_q", "file_id": "file_q"},
            ])
            writer.write_source_record_entity_relation(
                sources=[], records=[], entities=[],
                relations=[{
                    "relation_id": "rel_multi",
                    "source_ids": ["src_p", "src_q"],
                }],
            )
            writer.write_source_record_entity_relation(
                sources=[], records=[], entities=[], relations=[],
                purged_file_ids={"file_p"},
            )
            rels_after = _read_jsonl(writer.published / "03_relation_index.jsonl")
            rel_ids = [r["relation_id"] for r in rels_after]
            self.assertIn("rel_multi", rel_ids,
                          "Relation with surviving sources must NOT be tombstoned")


class TestTopicHintsPurge(unittest.TestCase):
    """Gap-E: purged file_ids must be removed from file_topics.json."""

    def test_purged_file_id_removed_from_hints(self):
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            hint_path = writer.published / "file_topics.json"

            # Prime hint file with two entries.
            hint_path.write_text(
                json.dumps({"keep_file": "finance", "purge_file": "travel"}),
                encoding="utf-8",
            )

            writer._write_topic_hints(records=[], purged_file_ids={"purge_file"})

            hints = json.loads(hint_path.read_text(encoding="utf-8"))
            self.assertIn("keep_file", hints, "Non-purged entry must remain")
            self.assertNotIn("purge_file", hints, "Purged file_id must be removed")

    def test_no_purge_ids_leaves_hints_intact(self):
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            hint_path = writer.published / "file_topics.json"
            hint_path.write_text(json.dumps({"f1": "work", "f2": "home"}), encoding="utf-8")

            writer._write_topic_hints(records=[], purged_file_ids=None)

            hints = json.loads(hint_path.read_text(encoding="utf-8"))
            self.assertEqual(set(hints.keys()), {"f1", "f2"})


class TestStaleDailyMemoryCleanup(unittest.TestCase):
    """Gap-F: day files with zero surviving records must be deleted after a purge."""

    def test_stale_day_file_deleted_when_no_records_remain(self):
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            stale_day = "2020-01-01"
            stale_path = writer.daily_dir / f"{stale_day}.json"
            stale_path.write_text(json.dumps({"date": stale_day, "record_count": 1}),
                                  encoding="utf-8")
            self.assertTrue(stale_path.exists(), "Stale file must exist before the test")

            # write_daily_memory rebuilds from the (empty) record index.
            # 01_record_index.jsonl does not exist → zero records → stale file removed.
            writer.write_daily_memory([])

            self.assertFalse(stale_path.exists(),
                             "Stale daily memory file must be deleted when no records survive")

    def test_active_day_file_kept(self):
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            # Create a record index so write_daily_memory produces at least one entry.
            records_path = writer.published / "01_record_index.jsonl"
            records_path.write_text(
                json.dumps({
                    "record_id": "r1", "file_id": "f1",
                    "event_date": "2025-06-15",
                    "importance_score": 0.8,
                    "title": "Test", "summary": "",
                    "people": [], "places": [], "apps": [],
                    "record_type": "generic_record",
                }) + "\n",
                encoding="utf-8",
            )
            writer.write_daily_memory([])
            day_file = writer.daily_dir / "2025-06-15.json"
            self.assertTrue(day_file.exists(),
                            "Day file for a date with records must NOT be deleted")


class TestStaleWeeklyMemoryCleanup(unittest.TestCase):
    """Gap-F: week files with no surviving days must be deleted."""

    def test_stale_week_file_deleted_when_daily_gone(self):
        with tempfile.TemporaryDirectory() as td:
            writer = JsonlWriter(Path(td))
            weekly_dir = writer.published / "04_weekly_memory"
            weekly_dir.mkdir(parents=True, exist_ok=True)
            stale_week = "2020-W01"
            stale_path = weekly_dir / f"{stale_week}.json"
            stale_path.write_text(json.dumps({"week": stale_week}), encoding="utf-8")
            self.assertTrue(stale_path.exists())

            # No daily files → weekly rebuild produces empty dict → stale week removed.
            writer.write_weekly_memory([])

            self.assertFalse(stale_path.exists(),
                             "Stale weekly memory file must be deleted when its days are gone")


if __name__ == "__main__":
    unittest.main()
