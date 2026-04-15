from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Iterator

from .daily_memory_builder import build_daily_memory
from .search_view_builder import build_search_views

# Warn when a single JSONL index file exceeds this size — indicative of
# potential RAM pressure on the Read-Merge-Write path.
_LARGE_FILE_WARN_BYTES = 50 * 1024 * 1024  # 50 MB

_log = logging.getLogger("bummdidumm.writers")


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
        """Load an existing JSONL file into a dict keyed by `key`. Returns {} if absent.

        Emits a warning when the file exceeds _LARGE_FILE_WARN_BYTES so that
        operators are alerted to potential RAM pressure before it becomes a problem.
        """
        if not path.exists():
            return {}
        existing: dict[str, dict] = {}

        file_size = path.stat().st_size
        if file_size > _LARGE_FILE_WARN_BYTES:
            _log.warning(
                "Large JSONL index file detected — RAM pressure possible on merge",
                extra={"path": str(path), "size_mb": round(file_size / 1024 / 1024, 1)},
            )

        try:
            # Stream line-by-line to avoid a single large string allocation
            with path.open(encoding="utf-8") as fh:
                for line_num, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                        if key in row:
                            existing[row[key]] = row
                    except Exception as e:
                        _log.warning(
                            "Skipping corrupt line in JSONL",
                            extra={"path": str(path), "line": line_num, "error": str(e)},
                        )
        except Exception as e:
            _log.error("Failed to read JSONL file", extra={"path": str(path), "error": str(e)})
        return existing

    def _stream_jsonl(self, path: Path) -> Iterator[dict]:
        """Yield parsed dicts from a JSONL file one line at a time without buffering.

        Use this for aggregation-only passes where no full join is needed.
        Prefer _read_existing() when a dedup-by-key dict is required.
        """
        if not path.exists():
            return
        try:
            with path.open(encoding="utf-8") as fh:
                for line_num, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except Exception as e:
                        _log.warning(
                            "Skipping corrupt line in JSONL",
                            extra={"path": str(path), "line": line_num, "error": str(e)},
                        )
        except Exception as e:
            _log.error("Failed to read JSONL file", extra={"path": str(path), "error": str(e)})

    def _load_full_records(self) -> list[dict]:
        """Return the complete merged record index from disk.

        Full load is unavoidable for callers that need all records simultaneously
        (e.g. build_daily_memory, build_search_views). Use _stream_jsonl() for
        aggregation-only passes.
        """
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
        """Streaming-Merge-Write: new rows overwrite existing rows by stable ID.

        Existing rows absent from `rows` are streamed directly to the temp file
        without being buffered in RAM. Only the incoming `rows` (O(m)) are held
        in memory, avoiding the previous O(n) full-load for large indices.

        Tombstone support: if a row in `rows` carries ``_deleted: True``, the
        existing entry with the same key is *removed* from the output and the
        tombstone row itself is NOT written. This enables callers to explicitly
        delete entries from the index without rebuilding it from scratch.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        new_lookup = {row[key]: row for row in rows}

        if path.exists():
            file_size = path.stat().st_size
            if file_size > _LARGE_FILE_WARN_BYTES:
                _log.warning(
                    "Large JSONL index file detected — RAM pressure possible on merge",
                    extra={"path": str(path), "size_mb": round(file_size / 1024 / 1024, 1)},
                )

        tmp_path = path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as out:
            if path.exists():
                with path.open(encoding="utf-8") as fh:
                    for line_num, line in enumerate(fh, 1):
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            row = json.loads(stripped)
                            k = row.get(key)
                            if k not in new_lookup:
                                out.write(stripped + "\n")
                        except Exception as e:
                            _log.warning(
                                "Skipping corrupt line in JSONL",
                                extra={"path": str(path), "line": line_num, "error": str(e)},
                            )
            for k in sorted(new_lookup):
                row = new_lookup[k]
                if not row.get("_deleted"):
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
        tmp_path.replace(path)

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

        # Accumulate mentions
        merged["mentions"] = merged.get("mentions", 0) + new_entity.get("mentions", 0)

        # Merge sources array containing mentions
        existing_sources = {s["source_id"]: s for s in merged.get("sources", [])}
        for s in new_entity.get("sources", []):
            sid = s["source_id"]
            if sid in existing_sources:
                existing_sources[sid]["mentions"] = existing_sources[sid].get("mentions", 0) + s.get("mentions", 0)
            else:
                existing_sources[sid] = s
        merged["sources"] = list(existing_sources.values())

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

        # Custom merge logic for entities — single-pass streaming to keep RAM at O(m).
        # Existing entities that match an incoming entity_id are merged in place and
        # written out; all others are streamed through without buffering.
        entity_path = self.published / "02_entity_index.jsonl"
        entity_path.parent.mkdir(parents=True, exist_ok=True)
        new_entity_lookup = {e["entity_id"]: e for e in entities}

        tmp_entity_path = entity_path.with_suffix(".tmp")
        with tmp_entity_path.open("w", encoding="utf-8") as out:
            if entity_path.exists():
                with entity_path.open(encoding="utf-8") as fh:
                    for line_num, line in enumerate(fh, 1):
                        stripped = line.strip()
                        if not stripped:
                            continue
                        try:
                            existing_ent = json.loads(stripped)
                            eid = existing_ent.get("entity_id")
                            if eid in new_entity_lookup:
                                self._merge_entities(existing_ent, new_entity_lookup.pop(eid))
                                clean = {ek: ev for ek, ev in existing_ent.items()
                                         if not ek.startswith("_") or ek == "_counts_by_source"}
                                out.write(json.dumps(clean, ensure_ascii=False) + "\n")
                            else:
                                out.write(stripped + "\n")
                        except Exception as e:
                            _log.warning(
                                "Skipping corrupt entity line",
                                extra={"path": str(entity_path), "line": line_num, "error": str(e)},
                            )
            for k in sorted(new_entity_lookup):
                clean = {ek: ev for ek, ev in new_entity_lookup[k].items()
                         if not ek.startswith("_") or ek == "_counts_by_source"}
                out.write(json.dumps(clean, ensure_ascii=False) + "\n")
        tmp_entity_path.replace(entity_path)

        self._write_jsonl(self.published / "03_relation_index.jsonl", relations, "relation_id")
        self._write_topic_hints(records)

    def _write_topic_hints(self, records: list[dict]) -> None:
        """Maintain a compact file_id→topic lookup used by main_safe_sort.py.

        Merges with existing hints so partial re-runs don't erase previous data.
        The resulting file_topics.json is orders of magnitude smaller than the
        full record index, making Safe Sort startup much faster.
        """
        hint_path = self.published / "file_topics.json"
        existing: dict[str, str] = {}
        if hint_path.exists():
            try:
                existing = json.loads(hint_path.read_text(encoding="utf-8"))
            except Exception as e:
                _log.warning("Could not load existing topic hints", extra={"error": str(e)})
        for rec in records:
            fid = rec.get("file_id")
            topics = rec.get("topics", [])
            if fid and topics:
                existing[fid] = topics[0]
        tmp = hint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        tmp.replace(hint_path)

    def write_daily_memory(self, _records: list[dict]) -> dict[str, dict]:
        """Rebuild daily memory from the full merged record index.

        `_records` is accepted for API compatibility but the rebuild is always
        performed from the on-disk record index so that partial re-index runs
        do not erase previous days.
        """
        # Full load is unavoidable: build_daily_memory() needs all records in
        # memory at once to group them by date across the entire history.
        all_records = self._load_full_records()
        daily = build_daily_memory(all_records)
        for day, payload in daily.items():
            target_path = self.daily_dir / f"{day}.json"
            tmp_path = target_path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            tmp_path.replace(target_path)
        return daily

    def write_weekly_memory(self, _records: list[dict]) -> dict[str, dict]:
        """Rebuild weekly memory from the full daily memory index."""
        from .weekly_memory_builder import build_weekly_memory
        daily_dir = self.daily_dir
        daily_memories: dict[str, dict] = {}
        if daily_dir.exists():
            import json as _json
            for f in daily_dir.glob("*.json"):
                if f.is_file():
                    try:
                        daily_memories[f.stem] = _json.loads(f.read_text(encoding="utf-8"))
                    except Exception as e:
                        _log.debug("Skipping unreadable daily memory file", extra={"file": str(f), "error": str(e)})
        weekly = build_weekly_memory(daily_memories)
        weekly_dir = self.published / "04_weekly_memory"
        weekly_dir.mkdir(parents=True, exist_ok=True)
        import json as _json
        for week_key, payload in weekly.items():
            target = weekly_dir / f"{week_key}.json"
            tmp = target.with_suffix(".tmp")
            with tmp.open("w", encoding="utf-8") as wf:
                _json.dump(payload, wf, ensure_ascii=False, indent=2)
            tmp.replace(target)
        return weekly

    def write_search_views(self, _records: list[dict]) -> dict[str, list[dict]]:
        """Rebuild all search views from the full merged record index."""
        # Full load is unavoidable: build_search_views() performs multi-dimensional
        # cross-record joins (by entity, service, date, topic) that require all
        # records in memory simultaneously.
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
        self._write_jsonl(
            self.published / "12_search_views" / "fulltext_index.jsonl",
            views["fulltext_index.jsonl"],
            "search_id",
        )
        return views

    def write_reports(self) -> None:
        """Write stats and summary from the full merged indices.

        All aggregation stats are computed via single streaming passes to keep
        peak RAM proportional to one row at a time rather than the full index.
        The master index sections are also written by streaming directly from the
        on-disk JSONL files, avoiding any full-load into RAM.
        """
        sources_path = self.published / "00_source_registry.jsonl"
        records_path = self.published / "01_record_index.jsonl"
        entities_path = self.published / "02_entity_index.jsonl"
        relations_path = self.published / "03_relation_index.jsonl"

        # ------------------------------------------------------------------
        # Streaming pass — sources (all values are aggregations, no full load)
        # ------------------------------------------------------------------
        total_sources = 0
        sources_by_system: Counter[str] = Counter()
        llm_export_count = 0
        parse_errors = 0
        parse_warnings = 0
        ocr_files_count = 0
        high_sensitivity_sources: list[str] = []
        dedicated_parsers = 0
        generic_sources = 0
        ocr_only_sources = 0
        shallow_archive_count = 0
        unmatched: set[str] = set()
        _SYSTEMS = ["instagram", "facebook", "telegram", "whatsapp", "messenger", "perplexity"]

        for s in self._stream_jsonl(sources_path):
            total_sources += 1
            sources_by_system[s.get("source_system", "unknown")] += 1
            if s.get("source_system") == "llm":
                llm_export_count += 1
            if s.get("parse_error"):
                parse_errors += 1
            if s.get("parse_warning"):
                parse_warnings += 1
            if s.get("source_format") == "image":
                ocr_files_count += 1
            if s.get("sensitivity") == "high":
                high_sensitivity_sources.append(s["source_id"])
            parser_name = s.get("parser_name", "")
            if not parser_name.startswith("parser_generic"):
                dedicated_parsers += 1
            else:
                generic_sources += 1
            if "event_only_no_content_processing" in str(s.get("notes", "")):
                ocr_only_sources += 1
            if s.get("is_archive") and not s.get("record_count", 0):
                shallow_archive_count += 1
            src_path = s.get("source_path", "").lower()
            parser_lower = parser_name.lower()
            for system in _SYSTEMS:
                if system in src_path and system not in parser_lower:
                    unmatched.add(system)

        # ------------------------------------------------------------------
        # Streaming pass — records (all values are aggregations, no full load)
        # ------------------------------------------------------------------
        total_records = 0
        records_by_type: Counter[str] = Counter()
        coverage_min_date = ""
        coverage_max_date = ""

        for r in self._stream_jsonl(records_path):
            total_records += 1
            records_by_type[r.get("record_type", "unknown")] += 1
            d = r.get("event_date", "")
            if d:
                if not coverage_min_date or d < coverage_min_date:
                    coverage_min_date = d
                if not coverage_max_date or d > coverage_max_date:
                    coverage_max_date = d

        # ------------------------------------------------------------------
        # Streaming pass — entities (count + type breakdown only)
        # ------------------------------------------------------------------
        total_entities = 0
        entities_by_type: Counter[str] = Counter()

        for e in self._stream_jsonl(entities_path):
            total_entities += 1
            entities_by_type[e.get("entity_type", "unknown")] += 1

        # ------------------------------------------------------------------
        # Streaming pass — relations (count only)
        # ------------------------------------------------------------------
        total_relations = sum(1 for _ in self._stream_jsonl(relations_path))

        stats = {
            "total_sources": total_sources,
            "total_records": total_records,
            "total_entities": total_entities,
            "total_relations": total_relations,
            "sources_by_system": dict(sources_by_system),
            "records_by_type": dict(records_by_type),
            "entities_by_type": dict(entities_by_type),
            "coverage_min_date": coverage_min_date,
            "coverage_max_date": coverage_max_date,
            "llm_export_count": llm_export_count,
            "parse_errors": parse_errors,
            "parse_warnings": parse_warnings,
            "ocr_files_count": ocr_files_count,
            "high_sensitivity_sources": high_sensitivity_sources,
            "dedicated_parsers": dedicated_parsers,
            "generic_sources": generic_sources,
            "ocr_only_sources": ocr_only_sources,
            "shallow_archive_count": shallow_archive_count,
            "missing_parser_families": sorted(list(unmatched)),
        }

        def atomic_write_text(path: Path, content: str) -> None:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)

        atomic_write_text(
            self.published / "CURRENT_personal_brain_stats.json",
            json.dumps(stats, ensure_ascii=False, indent=2)
        )
        atomic_write_text(
            self.published / "CURRENT_personal_brain_quality_report.json",
            json.dumps({
                "dedicated_parsers_used": stats["dedicated_parsers"],
                "generic_fallback_sources": stats["generic_sources"],
                "ocr_or_placeholder_only": stats["ocr_only_sources"],
                "shallow_archives": stats["shallow_archive_count"],
                "missing_important_parser_families": stats["missing_parser_families"]
            }, ensure_ascii=False, indent=2)
        )
        atomic_write_text(
            self.published / "CURRENT_personal_brain_summary.md",
            f"# Personal Brain Summary\n\n"
            f"Sources: {stats['total_sources']}\n"
            f"Records: {stats['total_records']}\n"
            f"Entities: {stats['total_entities']}\n"
            f"Relations: {stats['total_relations']}\n"
        )

        # Stream record index directly from disk — avoids building a full list in RAM
        index_path = self.published / "CURRENT_personal_brain_index.jsonl"
        index_tmp = index_path.with_suffix(".tmp")
        with index_tmp.open("w", encoding="utf-8") as out:
            for r in self._stream_jsonl(records_path):
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
        index_tmp.replace(index_path)

        # Write master index by streaming each section directly from the on-disk
        # JSONL files — no full-load of any index into RAM.
        master_path = self.published / "CURRENT_personal_brain_master_index.json"
        master_tmp = master_path.with_suffix(".tmp")
        with master_tmp.open("w", encoding="utf-8") as mf:
            # Sources
            mf.write('{\n"sources":[')
            first = True
            for obj in self._stream_jsonl(sources_path):
                if not first:
                    mf.write(",")
                mf.write(json.dumps(obj, ensure_ascii=False))
                first = False
            mf.write(']')

            # Records
            mf.write(',\n"records":[')
            first = True
            for obj in self._stream_jsonl(records_path):
                if not first:
                    mf.write(",")
                mf.write(json.dumps(obj, ensure_ascii=False))
                first = False
            mf.write(']')

            # Entities
            mf.write(',\n"entities":[')
            first = True
            for obj in self._stream_jsonl(entities_path):
                if not first:
                    mf.write(",")
                mf.write(json.dumps(obj, ensure_ascii=False))
                first = False
            mf.write(']')

            # Relations
            mf.write(',\n"relations":[')
            first = True
            for obj in self._stream_jsonl(relations_path):
                if not first:
                    mf.write(",")
                mf.write(json.dumps(obj, ensure_ascii=False))
                first = False
            mf.write(']')

            # Daily memory
            mf.write(',\n"daily_memory":{')
            first = True
            if self.daily_dir.exists():
                for f in sorted(self.daily_dir.glob("*.json")):
                    if f.is_file():
                        try:
                            day_data = json.loads(f.read_text(encoding="utf-8"))
                            if not first:
                                mf.write(",")
                            mf.write(json.dumps(f.stem, ensure_ascii=False) + ":")
                            json.dump(day_data, mf, ensure_ascii=False)
                            first = False
                        except Exception as e:
                            _log.debug("Skipping unreadable daily memory entry in master index", extra={"file": str(f), "error": str(e)})
            mf.write("}")

            # Search views
            mf.write(',\n"search_views":{')
            first = True
            search_view_dir = self.published / "12_search_views"
            if search_view_dir.exists():
                for f in sorted(search_view_dir.glob("*.jsonl")):
                    if f.is_file():
                        view_rows = []
                        for line in f.read_text(encoding="utf-8").splitlines():
                            if line.strip():
                                try:
                                    view_rows.append(json.loads(line))
                                except Exception as e:
                                    _log.debug("Skipping corrupt search view line", extra={"file": str(f), "error": str(e)})
                        if not first:
                            mf.write(",")
                        mf.write(json.dumps(f.stem, ensure_ascii=False) + ":")
                        json.dump(view_rows, mf, ensure_ascii=False)
                        first = False
            mf.write("}\n}")
        master_tmp.replace(master_path)
