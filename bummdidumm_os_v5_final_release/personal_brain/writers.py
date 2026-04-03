from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .daily_memory_builder import build_daily_memory
from .search_view_builder import build_search_views


from datetime import date

def compute_is_stale(entity: dict) -> bool:
    if entity.get("staleness_days") is None:
        return False
    last_seen = entity.get("last_seen")
    if not last_seen:
        return False
    try:
        return (date.today() - date.fromisoformat(last_seen[:10])).days > entity["staleness_days"]
    except Exception:
        return False

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

    def _merge_entities(self, merged: dict, new_entity: dict) -> None:
        # Min/max bounds for dates
        fs_list = [t for t in (merged.get("first_seen"), new_entity.get("first_seen")) if t]
        if fs_list:
            merged["first_seen"] = min(fs_list)
        ls_list = [t for t in (merged.get("last_seen"), new_entity.get("last_seen")) if t]
        if ls_list:
            merged["last_seen"] = max(ls_list)

        # Merge lists
        merged["source_systems"] = sorted(list(set(merged.get("source_systems", []) + new_entity.get("source_systems", []))))
        merged["source_ids"] = sorted(list(set(merged.get("source_ids", []) + new_entity.get("source_ids", []))))
        merged["aliases"] = sorted(list(set(merged.get("aliases", []) + new_entity.get("aliases", []))))

        # For counts, we avoid blind accumulation to prevent inflation on re-runs.
        # Instead of adding, we keep track of counts mapped by source_id.
        # Initialize dictionary if missing, or backfill from existing flat counts if necessary.
        merged_counts = merged.get("_counts_by_source", {})

        # Backfill legacy flat counts if we have none tracked but there is historical data
        if not merged_counts and (merged.get("related_record_count", 0) > 0 or merged.get("related_relation_count", 0) > 0):
            # Assign the legacy totals to the first known source_id or a generic fallback
            legacy_sid = merged.get("source_ids", ["legacy_unknown"])[0]
            merged_counts[legacy_sid] = {
                "records": merged.get("related_record_count", 0),
                "relations": merged.get("related_relation_count", 0)
            }

        # Determine the source_id driving the current batch update.
        # Usually, an entity in a batch is derived from the single source currently being parsed.
        # If it's a new entity being merged, we record its counts for its source_ids.
        for sid in new_entity.get("source_ids", []):
            merged_counts[sid] = {
                "records": new_entity.get("related_record_count", 0),
                "relations": new_entity.get("related_relation_count", 0)
            }

        merged["_counts_by_source"] = merged_counts

        # Update the top level aggregate counts dynamically based on the dictionary.
        merged["related_record_count"] = sum(v.get("records", 0) for v in merged_counts.values())
        merged["related_relation_count"] = sum(v.get("relations", 0) for v in merged_counts.values())

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

        # Custom merge logic for entities
        entity_path = self.published / "02_entity_index.jsonl"
        entity_path.parent.mkdir(parents=True, exist_ok=True)
        merged_entities = self._read_existing(entity_path, "entity_id")

        for new_ent in entities:
            eid = new_ent["entity_id"]
            if eid in merged_entities:
                self._merge_entities(merged_entities[eid], new_ent)
            else:
                merged_entities[eid] = new_ent

        with entity_path.open("w", encoding="utf-8") as f:
            for k in sorted(merged_entities):
                f.write(json.dumps(merged_entities[k], ensure_ascii=False) + "\n")

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

    def write_reports(self) -> None:
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
            "dedicated_parsers": sum(1 for s in sources if not s.get("parser_name", "").startswith("parser_generic")),
            "generic_sources": sum(1 for s in sources if s.get("parser_name", "").startswith("parser_generic")),
            "ocr_only_sources": sum(1 for s in sources if "event_only_no_content_processing" in str(s.get("notes", ""))),
            "missing_parser_families": list(set(
                system for system in ["instagram", "facebook", "telegram", "whatsapp", "messenger", "perplexity"]
                if any(system in s.get("source_path", "").lower() for s in sources) and
                not any(system in s.get("parser_name", "").lower() for s in sources)
            )),
            "shallow_archive_count": sum(1 for s in sources if s.get("is_archive") and not s.get("record_count", 0)),
        }
        (self.published / "CURRENT_personal_brain_stats.json").write_text(
            json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (self.published / "CURRENT_personal_brain_quality_report.json").write_text(
            json.dumps({
                "dedicated_parsers_used": stats["dedicated_parsers"],
                "generic_fallback_sources": stats["generic_sources"],
                "ocr_or_placeholder_only": stats["ocr_only_sources"],
                "shallow_archives": stats["shallow_archive_count"],
                "missing_important_parser_families": stats["missing_parser_families"]
            }, ensure_ascii=False, indent=2), encoding="utf-8"
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

        # Build Master Output combining all data
        master_output = {
            "sources": sources,
            "records": records,
            "entities": entities,
            "relations": relations,
            "daily_memory": {},
            "search_views": {}
        }

        # Load daily memory
        if self.daily_dir.exists():
            for f in self.daily_dir.glob("*.json"):
                if f.is_file():
                    try:
                        master_output["daily_memory"][f.stem] = json.loads(f.read_text(encoding="utf-8"))
                    except Exception:
                        pass

        # Load search views
        search_view_dir = self.published / "12_search_views"
        if search_view_dir.exists():
            for f in search_view_dir.glob("*.jsonl"):
                if f.is_file():
                    view_name = f.stem
                    master_output["search_views"][view_name] = []
                    for line in f.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            master_output["search_views"][view_name].append(json.loads(line))

        # Write master output
        (self.published / "CURRENT_personal_brain_master_index.json").write_text(
            json.dumps(master_output, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
