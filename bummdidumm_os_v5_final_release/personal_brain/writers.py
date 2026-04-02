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

    def _dedup_by_key(self, rows: list[dict], key: str) -> list[dict]:
        unique: dict[str, dict] = {}
        for row in rows:
            unique[row[key]] = row
        return [unique[k] for k in sorted(unique)]

    def _write_jsonl(self, path: Path, rows: list[dict], key: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        deduped = self._dedup_by_key(rows, key)
        with path.open("w", encoding="utf-8") as f:
            for row in deduped:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def write_source_record_entity_relation(self, sources: list[dict], records: list[dict], entities: list[dict], relations: list[dict]) -> None:
        self._write_jsonl(self.published / "00_source_registry.jsonl", sources, "source_id")
        self._write_jsonl(self.published / "01_record_index.jsonl", records, "record_id")
        self._write_jsonl(self.published / "02_entity_index.jsonl", entities, "entity_id")
        self._write_jsonl(self.published / "03_relation_index.jsonl", relations, "relation_id")

    def write_daily_memory(self, records: list[dict]) -> dict[str, dict]:
        daily = build_daily_memory(records)
        for day, payload in daily.items():
            with (self.daily_dir / f"{day}.json").open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        return daily

    def write_search_views(self, records: list[dict]) -> dict[str, list[dict]]:
        views = build_search_views(records)
        self._write_jsonl(self.published / "CURRENT_personal_brain_search_view.jsonl", views["CURRENT_personal_brain_search_view.jsonl"], "search_id")
        self._write_jsonl(self.published / "12_search_views" / "by_date.jsonl", views["by_date.jsonl"], "search_id")
        self._write_jsonl(self.published / "12_search_views" / "by_entity.jsonl", views["by_entity.jsonl"], "search_id")
        self._write_jsonl(self.published / "12_search_views" / "by_service.jsonl", views["by_service.jsonl"], "search_id")
        self._write_jsonl(self.published / "12_search_views" / "by_topic.jsonl", views["by_topic.jsonl"], "search_id")
        self._write_jsonl(self.published / "12_search_views" / "llm_conversations.jsonl", views["llm_conversations.jsonl"], "search_id")
        return views

    def write_reports(self, sources: list[dict], records: list[dict], entities: list[dict], relations: list[dict]) -> None:
        stats = {
            "total_sources": len({s["source_id"] for s in sources}),
            "total_records": len({r["record_id"] for r in records}),
            "total_entities": len({e["entity_id"] for e in entities}),
            "total_relations": len({r["relation_id"] for r in relations}),
            "sources_by_system": dict(Counter(s.get("source_system", "unknown") for s in sources)),
            "records_by_type": dict(Counter(r.get("record_type", "unknown") for r in records)),
            "entities_by_type": dict(Counter(e.get("entity_type", "unknown") for e in entities)),
            "coverage_min_date": min((r.get("event_date", "") for r in records if r.get("event_date")), default=""),
            "coverage_max_date": max((r.get("event_date", "") for r in records if r.get("event_date")), default=""),
            "llm_export_count": sum(1 for s in sources if s.get("source_system") == "llm"),
            "parse_errors": sum(1 for s in sources if s.get("parse_error")),
            "parse_warnings": sum(1 for s in sources if s.get("parse_warning")),
            "ocr_files_count": sum(1 for s in sources if s.get("source_format") == "image"),
            "high_sensitivity_sources": [s["source_id"] for s in sources if s.get("sensitivity") == "high"],
        }
        (self.published / "CURRENT_personal_brain_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
        (self.published / "CURRENT_personal_brain_summary.md").write_text(
            f"# Personal Brain Summary\n\nSources: {stats['total_sources']}\nRecords: {stats['total_records']}\nEntities: {stats['total_entities']}\nRelations: {stats['total_relations']}\n",
            encoding="utf-8",
        )
        (self.published / "CURRENT_personal_brain_index.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self._dedup_by_key(records, "record_id")), encoding="utf-8")
