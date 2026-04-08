from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SourcePreview:
    path: str
    name: str
    mime: str
    ext: str
    content_preview: dict[str, Any]
    text_preview: str = ""


class BaseParser:
    parser_name = "base"
    parser_version = "2.0.0"
    source_system = "generic"
    source_service = "generic"
    source_app = "generic"
    source_kind = "export"
    source_format = "unknown"
    match_tokens: tuple[str, ...] = tuple()
    required_json_keys: tuple[str, ...] = tuple()
    default_record_type = "generic_record"
    default_entity_type = "topic"

    def can_handle(self, source_meta: dict, preview: SourcePreview) -> bool:
        haystack = f"{preview.path} {preview.name} {preview.text_preview}".lower()
        token_match = any(t in haystack for t in self.match_tokens)
        key_match = bool(self.required_json_keys) and all(k in preview.content_preview for k in self.required_json_keys)
        return token_match or key_match

    def extract_source_metadata(self, path: str, preview: SourcePreview) -> dict:
        return {
            "source_system": self.source_system,
            "source_service": self.source_service,
            "source_subservice": "",
            "source_app": self.source_app,
            "source_kind": self.source_kind,
            "source_format": self.source_format,
            "export_time": preview.content_preview.get("export_time", ""),
            "coverage_start": preview.content_preview.get("coverage_start", ""),
            "coverage_end": preview.content_preview.get("coverage_end", ""),
        }

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        event_time = content.get("event_time_start", "")
        event_date = content.get("event_date") or event_time[:10] or source_meta.get("coverage_start", "")[:10]
        return [{
            "record_type": self.default_record_type,
            "subtype": content.get("subtype", "default"),
            "event_time_start": event_time,
            "event_time_end": content.get("event_time_end", ""),
            "event_date": event_date,
            "title": content.get("title", source_meta.get("original_filename", "")),
            "summary": content.get("summary", ""),
            "raw_text": content.get("raw_text", ""),
            "normalized_text": content.get("normalized_text", content.get("raw_text", "")),
            "people": content.get("people", []),
            "places": content.get("places", []),
            "apps": content.get("apps", []),
            "devices": content.get("devices", []),
            "accounts": content.get("accounts", []),
            "topics": content.get("topics", []),
            "tags": content.get("tags", []),
            "url": content.get("url", ""),
            "external_id": content.get("external_id", ""),
            "conversation_id": content.get("conversation_id", ""),
            "message_id": content.get("message_id", ""),
            "thread_id": content.get("thread_id", ""),
            "amount": content.get("amount"),
            "currency": content.get("currency"),
            "quantity": content.get("quantity"),
            "geo_lat": content.get("geo_lat"),
            "geo_lon": content.get("geo_lon"),
            "place_name": content.get("place_name", ""),
            "confidence": content.get("confidence", 0.8),
            "importance_score": content.get("importance_score", 0.5),
            "status": content.get("status", "active"),
        }]

    def extract_entities(self, records: list[dict], source_meta: dict) -> list[dict]:
        entities: list[dict] = []
        for record in records:
            for app in record.get("apps", []):
                entities.append({"entity_type": "app", "canonical_name": app.lower(), "display_name": app})
            for topic in record.get("topics", []):
                entities.append({"entity_type": "topic", "canonical_name": topic.lower(), "display_name": topic})
            for person in record.get("people", []):
                entities.append({"entity_type": "person", "canonical_name": person.lower(), "display_name": person})
            if record.get("place_name"):
                entities.append({"entity_type": "place", "canonical_name": record["place_name"].lower(), "display_name": record["place_name"]})

        dedup: dict[tuple[str, str], dict] = {}
        for ent in entities:
            dedup[(ent["entity_type"], ent["canonical_name"])] = ent
        return list(dedup.values())

    def _make_rel(
        self,
        subject: str, subject_type: str,
        predicate: str,
        obj: str, object_type: str,
        record: dict,
        confidence: float = 0.75,
    ) -> dict:
        return {
            "subject": subject.lower().strip(),
            "subject_type": subject_type,
            "predicate": predicate,
            "object": obj.lower().strip(),
            "object_type": object_type,
            "time_start": record.get("event_time_start", ""),
            "time_end": record.get("event_time_end", ""),
            "confidence": confidence,
            "status": "active",
            "evidence_external_id": record.get("external_id", ""),
        }

    def build_relations(self, records: list[dict], entities: list[dict], source_meta: dict) -> list[dict]:
        rels: list[dict] = []
        entity_names = {e["canonical_name"]: e for e in entities}

        for record in records:
            # Topic → Record (bestehend, beibehalten)
            for topic in record.get("topics", []):
                if topic.lower() in entity_names:
                    rels.append(self._make_rel(topic, "topic", "mentions",
                        record.get("title", "")[:80], "topic", record, confidence=0.8))

            # Person → Place
            place = record.get("place_name", "")
            if place:
                for person in record.get("people", []):
                    rels.append(self._make_rel(person, "person", "visited", place, "place", record))

            # Person → App
            for person in record.get("people", []):
                for app in record.get("apps", []):
                    rels.append(self._make_rel(person, "person", "used_app", app, "app", record))

            # Person ↔ Person (kommuniziert mit — wenn mehrere Personen)
            people = record.get("people", [])
            for i, p1 in enumerate(people):
                for p2 in people[i + 1:]:
                    rels.append(self._make_rel(p1, "person", "communicated_with", p2, "person", record, confidence=0.7))

        # Duplikate entfernen
        seen: set[tuple[str, str, str]] = set()
        unique: list[dict] = []
        for r in rels:
            key = (r["subject"], r["predicate"], r["object"])
            if key not in seen and r["subject"] and r["object"]:
                seen.add(key)
                unique.append(r)
        return unique

    def build_profile_fragments(self, records: list[dict], entities: list[dict], source_meta: dict) -> dict:
        return {
            "apps": sorted({a for r in records for a in r.get("apps", [])}),
            "topics": sorted({t for r in records for t in r.get("topics", [])}),
        }

    def summarize_source(self, records: list[dict], entities: list[dict], relations: list[dict], source_meta: dict) -> dict:
        return {
            "record_count": len(records),
            "entity_count": len(entities),
            "relation_count": len(relations),
        }
