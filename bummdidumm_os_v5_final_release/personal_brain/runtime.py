from __future__ import annotations

from pathlib import Path
from typing import Any

from .id_builder import entity_id, record_id, relation_id, source_id, stable_hash
from .parser_registry import ParserRegistry
from .parsers.base import SourcePreview
from .utils import norm_filename, utc_now
from .writers import JsonlWriter


class PersonalBrainRuntime:
    def __init__(self, project_id: str, out_root: Path):
        self.project_id = project_id
        self.registry = ParserRegistry()
        self.writer = JsonlWriter(out_root)

    def process_sources(self, sources: list[dict[str, Any]], exclusions: dict | None = None) -> dict[str, int]:
        if exclusions is None:
            exclusions = {}
        # BUG-4 fix: collect file_ids whose Brain-index entries must be tombstone-deleted.
        # PURGED sources are skipped below (continue), so they never appear in source_rows.
        # Without this set the old JSONL entries stream through _write_jsonl unchanged.
        purged_file_ids: set[str] = {
            fid for fid, status in exclusions.items() if status == "PURGED"
        }
        source_rows: dict[str, dict] = {}
        record_rows: dict[str, dict] = {}
        entity_rows: dict[str, dict] = {}
        relation_rows: dict[str, dict] = {}

        for item in sources:
            file_id = item.get("file_id", "")
            parent_file_id = item.get("bundle_id", "")
            knowledge_status = exclusions.get(file_id, exclusions.get(parent_file_id, "ACTIVE"))
            item["knowledge_status"] = knowledge_status

            if knowledge_status in ["EXCLUDED", "PURGED"]:
                continue

            preview = SourcePreview(
                path=item["source_path"],
                name=item["original_filename"],
                mime=item.get("mime", "application/octet-stream"),
                ext=item.get("ext", ""),
                content_preview=item.get("preview", {}),
                text_preview=item.get("text_preview", ""),
            )
            parser = self.registry.resolve(item, preview)
            md = parser.extract_source_metadata(item["source_path"], preview)
            source = self._build_source(item, parser, md)
            source_rows[source["source_id"]] = source

            parsed_records = parser.parse_to_records(source, item.get("content", {}))
            normalized_records = [self._build_record(source, r) for r in parsed_records]
            for rec in normalized_records:
                record_rows[rec["record_id"]] = rec

            parsed_entities = parser.extract_entities(normalized_records, source)
            normalized_entities = [self._build_entity(source, e, normalized_records) for e in parsed_entities]
            # Build lookup: (entity_type, canonical_name) -> entity_id
            # Prevents _build_relation from hardcoding "topic" as entity type.
            entity_map: dict[tuple[str, str], str] = {
                (ent["entity_type"], ent["canonical_name"]): ent["entity_id"]
                for ent in normalized_entities
            }

            # Bidirektionales Entity-Record-Linking
            # Alle Entity-IDs dieser Source den zugehörigen Records zuweisen
            source_entity_ids = [ent["entity_id"] for ent in normalized_entities]
            for rec in normalized_records:
                rec["related_entity_ids"] = source_entity_ids

            for ent in normalized_entities:
                entity_rows[ent["entity_id"]] = ent

            parsed_relations = parser.build_relations(normalized_records, normalized_entities, source)
            normalized_relations = [
                self._build_relation(source, rel, normalized_records, normalized_entities, entity_map)
                for rel in parsed_relations
            ]
            for rel in normalized_relations:
                relation_rows[rel["relation_id"]] = rel

            summary = parser.summarize_source(normalized_records, normalized_entities, normalized_relations, source)
            source["record_count"] = summary["record_count"]
            source["entity_count"] = summary["entity_count"]
            source["relation_count"] = summary["relation_count"]

        source_list = list(source_rows.values())
        record_list = list(record_rows.values())
        entity_list = list(entity_rows.values())
        relation_list = list(relation_rows.values())

        self.writer.write_source_record_entity_relation(
            source_list, record_list, entity_list, relation_list,
            purged_file_ids=purged_file_ids,
        )
        self.writer.write_daily_memory(record_list)
        self.writer.write_weekly_memory(record_list)
        views = self.writer.write_search_views(record_list)
        self.writer.write_reports()

        return {
            "total_sources": len(source_list),
            "total_records": len(record_list),
            "total_entities": len(entity_list),
            "total_relations": len(relation_list),
            "total_search_entries": len(views["CURRENT_personal_brain_search_view.jsonl"]),
        }

    def _build_source(self, item: dict, parser, md: dict) -> dict:
        # Prioritize file_id or checksum over path to ensure renames/moves maintain identity.
        # Fallback to hashing only immutable content (not mutable paths) if both are missing.
        stable_id = item.get("file_id") or item.get("checksum_sha256") or stable_hash(item.get("content", {}))
        source_key = f"{self.project_id}:{stable_id}:{parser.parser_name}:{parser.parser_version}"
        source_id_value = source_id(self.project_id, source_key)

        # Unify field identity (source_path, source_path_rel, raw_ref, checksum_sha256, status, sot_status, canonical_format)
        s_path = item.get("source_path", "")
        s_path_rel = item.get("source_path_rel", s_path)
        raw_ref = item.get("raw_ref", item.get("web_link", s_path_rel))
        chk_sum = item.get("checksum_sha256") or stable_hash(item.get("content", {}))

        export_t = md.get("export_time") or item.get("created_at", "")
        coverage_s = md.get("coverage_start") or item.get("created_at", "")
        coverage_e = md.get("coverage_end") or item.get("modified_at", "")

        md_overrides = dict(md)
        md_overrides["export_time"] = export_t
        md_overrides["coverage_start"] = coverage_s
        md_overrides["coverage_end"] = coverage_e

        return {
            "project_id": self.project_id,
            "source_id": source_id_value,
            "source_key": source_key,
            "file_id": item.get("file_id", ""),
            "bundle_id": item.get("bundle_id", ""),
            "parent_bundle_id": item.get("parent_bundle_id", ""),
            **md_overrides,
            "source_path": s_path,
            "source_path_rel": s_path_rel,
            "original_filename": item["original_filename"],
            "normalized_filename": norm_filename(item["original_filename"]),
            "mime": item.get("mime", ""),
            "ext": item.get("ext", ""),
            "checksum_sha256": chk_sum,
            "semantic_hash": stable_hash(item.get("content", {})),
            "parser_name": parser.parser_name,
            "parser_version": parser.parser_version,
            "parser_status": "success",
            "parse_error": "",
            "parse_warning": "",
            "created_at": item.get("created_at", ""),
            "modified_at": item.get("modified_at", ""),
            "scanned_at": utc_now(),
            "llm_readiness": item.get("llm_readiness", "medium"),
            "sensitivity": item.get("sensitivity", "unknown"),
            "status": item.get("status", "indexed"),
            "sot_status": item.get("sot_status", "derived"),
            "canonical_format": item.get("canonical_format") or md.get("source_format", "unknown"),
            "is_export": item.get("is_export", True),
            "is_bundle": item.get("is_bundle", False),
            "is_archive": item.get("is_archive", False),
            "is_incremental": item.get("is_incremental", False),
            "contains_pii": item.get("contains_pii", False),
            "contains_geo": item.get("contains_geo", False),
            "contains_financial": item.get("contains_financial", False),
            "contains_messages": item.get("contains_messages", False),
            "contains_media_refs": item.get("contains_media_refs", False),
            "record_count": 0,
            "entity_count": 0,
            "relation_count": 0,
            "source_url": item.get("source_url", ""),
            "raw_ref": raw_ref,
        }

    def _build_record(self, source: dict, record: dict) -> dict:
        rid = record_id(
            source_id_value=source["source_id"],
            record_type=record.get("record_type", "generic_record"),
            external_id=record.get("external_id", ""),
            event_time_start=record.get("event_time_start", ""),
            title=record.get("title", source["original_filename"]),
        )
        event_date = record.get("event_date") or record.get("event_time_start", "")[:10]
        return {
            "record_id": rid,
            "source_id": source["source_id"],
            "source_key": source["source_key"],
            "file_id": source.get("file_id", ""),
            "record_type": record.get("record_type", "generic_record"),
            "subtype": record.get("subtype", "default"),
            "source_system": source["source_system"],
            "source_service": source["source_service"],
            "source_app": source["source_app"],
            "event_time_start": record.get("event_time_start", ""),
            "event_time_end": record.get("event_time_end", ""),
            "event_date": event_date,
            "ingestion_time": utc_now(),
            "title": record.get("title", source["original_filename"]),
            "compact_title": record.get("title", source["original_filename"])[:120],
            "summary": record.get("summary", ""),
            "compact_summary": record.get("summary", "")[:240],
            "raw_text": record.get("raw_text", ""),
            "normalized_text": record.get("normalized_text", ""),
            "status": record.get("status", "active"),
            "confidence": record.get("confidence", 0.8),
            "importance_score": record.get("importance_score", 0.5),
            "people": record.get("people", []),
            "places": record.get("places", []),
            "apps": record.get("apps", []),
            "devices": record.get("devices", []),
            "accounts": record.get("accounts", []),
            "topics": record.get("topics", []),
            "tags": record.get("tags", []),
            "geo_lat": record.get("geo_lat"),
            "geo_lon": record.get("geo_lon"),
            "place_name": record.get("place_name", ""),
            "amount": record.get("amount"),
            "currency": record.get("currency"),
            "quantity": record.get("quantity"),
            "url": record.get("url", ""),
            "external_id": record.get("external_id", ""),
            "conversation_id": record.get("conversation_id", ""),
            "message_id": record.get("message_id", ""),
            "thread_id": record.get("thread_id", ""),
            "related_entity_ids": [],
            "related_record_ids": [],
            "raw_ref": source["raw_ref"],
            "checksum_sha256": stable_hash(record),
        }

    def _build_entity(self, source: dict, entity: dict, records: list[dict]) -> dict:
        canonical = entity.get("canonical_name", entity.get("display_name", "unknown")).lower()
        eid = entity_id(entity.get("entity_type", "topic"), canonical)
        first_seen = min((r.get("event_date", "") for r in records if r.get("event_date")), default="")
        last_seen = max((r.get("event_date", "") for r in records if r.get("event_date")), default="")
        return {
            "entity_id": eid,
            "entity_type": entity.get("entity_type", "topic"),
            "canonical_name": canonical,
            "display_name": entity.get("display_name", canonical),
            "aliases": entity.get("aliases", []),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "source_systems": [source["source_system"]],
            "source_ids": [source["source_id"]],
            "tags": entity.get("tags", []),
            "importance_score": entity.get("importance_score", 0.5),
            "current_status": "active",
            "related_record_count": len(records),
            "related_relation_count": 0,
            "summary": f"Derived from {source['source_app']}",
            "compact_summary": f"Derived from {source['source_app']}",
        }

    def _build_relation(
        self,
        source: dict,
        relation: dict,
        records: list[dict],
        entities: list[dict],
        entity_map: dict[tuple[str, str], str],
    ) -> dict:
        subject_name = relation.get("subject", "unknown").lower()
        object_name = relation.get("object", "unknown").lower()
        # Parsers now emit subject_type / object_type; fall back to "topic" for legacy output.
        subject_type = relation.get("subject_type", "topic")
        object_type = relation.get("object_type", "topic")

        # Resolve entity IDs via the per-source entity_map so that types are correct.
        # Falls back to constructing a new deterministic ID with the declared type
        # rather than blindly hardcoding "topic" for every relation endpoint.
        subject_eid = entity_map.get((subject_type, subject_name)) or entity_id(subject_type, subject_name)
        object_eid = entity_map.get((object_type, object_name)) or entity_id(object_type, object_name)

        evidence = [
            r["record_id"] for r in records
            if relation.get("evidence_external_id") and
               relation["evidence_external_id"] == r.get("external_id", "")
        ]

        rid = relation_id(subject_eid, relation.get("predicate", "relates_to"), object_eid, evidence)
        return {
            "relation_id": rid,
            "subject_entity_id": subject_eid,
            "predicate": relation.get("predicate", "relates_to"),
            "object_entity_id": object_eid,
            "time_start": relation.get("time_start", ""),
            "time_end": relation.get("time_end", ""),
            "evidence_record_ids": evidence,
            "source_ids": [source["source_id"]],
            "confidence": relation.get("confidence", 0.8),
            "status": relation.get("status", "active"),
        }
