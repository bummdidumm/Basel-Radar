from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .daily_memory_builder import build_daily_memory
from .search_view_builder import build_search_views


class JsonlWriter:
    def __init__(self, out_root: Path):
        self.out_root = out_root
        self.published = out_root / "20_index" / "published"
        self.daily_dir = self.published / "04_daily_memory"
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        for d in [
            "05_profiles/apps", "06_profiles/people", "07_profiles/places", "08_profiles/topics",
            "09_profiles/services", "10_profiles/devices", "11_profiles/accounts", "12_search_views",
            "13_llm_context_packs", "14_reports", "15_logs",
        ]:
            (self.published / d).mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    def _read_existing(self, path: Path, key: str) -> dict[str, dict]:
        """Load an existing JSONL file into a dict keyed by `key`. Returns {} if absent."""
        if not path.exists():
            return {}
        existing: dict[str, dict] = {}
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            import logging
            logging.error(f"Failed to read file {path}: {e}")
            return existing

        for line_num, line in enumerate(content.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
                if key in row:
                    existing[row[key]] = row
            except Exception as e:
                import logging
                logging.warning(f"Skipping corrupt line {line_num} in {path}: {e}")
        return existing

    def _load_full_records(self) -> list[dict]:
        """Return the complete merged record index from disk."""
        return list(self._read_existing(self.published / "01_record_index.jsonl", "record_id").values())

    def _load_full_sources(self) -> list[dict]:
        return list(self._read_existing(self.published / "00_source_registry.jsonl", "source_id").values())

    def _load_full_entities(self) -> list[dict]:
        return list(self._read_existing(self.published / "02_entity_index.jsonl", "entity_id").values())

    def _load_full_relations(self) -> list[dict]:
        return list(self._read_existing(self.published / "03_relation_index.jsonl", "relation_id").values())

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def _write_jsonl(self, path: Path, rows: list[dict], key: str) -> None:
        """Read-Merge-Write: new rows overwrite existing rows by stable ID.
        Entries absent from `rows` but present on disk are preserved.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        merged = self._read_existing(path, key)
        for row in rows:
            merged[row[key]] = row
        with path.open("w", encoding="utf-8") as f:
            for k in sorted(merged):
                f.write(json.dumps(merged[k], ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # Public write methods
    # ------------------------------------------------------------------

    def write_source_record_entity_relation(
        self,
        sources: list[dict],
        records: list[dict],
        entities: list[dict],
        relations: list[dict],
    ) -> None:
        self._write_jsonl(self.published / "00_source_registry.jsonl", sources, "source_id")
        self._write_jsonl(self.published / "01_record_index.jsonl", records, "record_id")
        self._write_jsonl(self.published / "02_entity_index.jsonl", entities, "entity_id")
        self._write_jsonl(self.published / "03_relation_index.jsonl", relations, "relation_id")

    def write_daily_memory(self, _records: list[dict]) -> dict[str, dict]:
        """Rebuild daily memory from the full merged record index.

        `_records` is accepted for API compatibility but the rebuild is always
        performed from the on-disk record index so that partial re-index runs
        do not erase previous days.
        """
        all_records = self._load_full_records()
        daily = build_daily_memory(all_records)
        for day, payload in daily.items():
            with (self.daily_dir / f"{day}.json").open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        return daily

    def write_search_views(self, _records: list[dict]) -> dict[str, list[dict]]:
        """Rebuild all search views from the full merged record index."""
        all_records = self._load_full_records()
        views = build_search_views(all_records)
        self._write_jsonl(
            self.published / "CURRENT_personal_brain_search_view.jsonl",
            views["CURRENT_personal_brain_search_view.jsonl"],
            "search_id",
        )
        self._write_jsonl(self.published / "12_search_views" / "by_date.jsonl", views["by_date.jsonl"], "search_id")
        self._write_jsonl(self.published / "12_search_views" / "by_entity.jsonl", views["by_entity.jsonl"], "search_id")
        self._write_jsonl(self.published / "12_search_views" / "by_service.jsonl", views["by_service.jsonl"], "search_id")
        self._write_jsonl(self.published / "12_search_views" / "by_topic.jsonl", views["by_topic.jsonl"], "search_id")
        self._write_jsonl(
            self.published / "12_search_views" / "llm_conversations.jsonl",
            views["llm_conversations.jsonl"],
            "search_id",
        )
        return views

    def write_reports(
        self,
        _sources: list[dict],
        _records: list[dict],
        _entities: list[dict],
        _relations: list[dict],
    ) -> None:
        """Write stats and summary from the full merged indices."""
        sources = self._load_full_sources()
        records = self._load_full_records()
        entities = self._load_full_entities()
        relations = self._load_full_relations()

        stats = {
            "total_sources": len(sources),
            "total_records": len(records),
            "total_entities": len(entities),
            "total_relations": len(relations),
            "sources_by_system": dict(Counter(s.get("source_system", "unknown") for s in sources)),
            "records_by_type": dict(Counter(r.get("record_type", "unknown") for r in records)),
            "entities_by_type": dict(Counter(e.get("entity_type", "unknown") for e in entities)),
            "coverage_min_date": min(
                (r.get("event_date", "") for r in records if r.get("event_date")), default=""
            ),
            "coverage_max_date": max(
                (r.get("event_date", "") for r in records if r.get("event_date")), default=""
            ),
            "llm_export_count": sum(1 for s in sources if s.get("source_system") == "llm"),
            "parse_errors": sum(1 for s in sources if s.get("parse_error")),
            "parse_warnings": sum(1 for s in sources if s.get("parse_warning")),
            "ocr_files_count": sum(1 for s in sources if s.get("source_format") == "image"),
            "high_sensitivity_sources": [s["source_id"] for s in sources if s.get("sensitivity") == "high"],
        }
        (self.published / "CURRENT_personal_brain_stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.published / "CURRENT_personal_brain_summary.md").write_text(
            f"# Personal Brain Summary\n\n"
            f"Sources: {stats['total_sources']}\n"
            f"Records: {stats['total_records']}\n"
            f"Entities: {stats['total_entities']}\n"
            f"Relations: {stats['total_relations']}\n",
            encoding="utf-8",
        )
        (self.published / "CURRENT_personal_brain_index.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8",
        )
