from __future__ import annotations

from ..base import BaseParser

class InstagramExportParser(BaseParser):
    parser_name = "parser_instagram_export"
    parser_version = "2.0.0"
    source_system = "meta"
    source_service = "instagram"
    source_app = "instagram"
    source_kind = "export"
    source_format = "json"
    default_record_type = "message_event"
    match_tokens = ("instagram", "messages")

    def can_handle(self, source_meta: dict, preview: dict) -> bool:
        filename = source_meta.get("original_filename", "").lower()
        if "instagram" in filename or "messages" in filename:
            content_preview = getattr(preview, "content_preview", preview)
            if isinstance(content_preview, dict) and ("messages" in content_preview or "participants" in content_preview):
                return True
        return False

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        records = []
        messages = content.get("messages", [])
        if not messages:
            return super().parse_to_records(source_meta, content)

        for msg in messages:
            ts = msg.get("timestamp_ms", 0)
            if ts:
                import datetime
                ts_iso = datetime.datetime.fromtimestamp(ts/1000.0, tz=datetime.timezone.utc).isoformat().replace("+00:00", "Z")
            else:
                ts_iso = ""

            sender = msg.get("sender_name", "Unknown")
            text = msg.get("content", "")

            records.append({
                "record_type": "message_event",
                "subtype": "instagram_message",
                "event_time_start": ts_iso,
                "event_date": ts_iso[:10] if ts_iso else "",
                "title": f"Instagram message from {sender}",
                "summary": text[:200],
                "raw_text": text,
                "people": [sender]
            })
        return records

    def extract_entities(self, normalized_records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(normalized_records, source_meta)
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}

        if ("app", "instagram") not in dedup:
            ent = {"entity_type": "app", "canonical_name": "instagram", "display_name": "Instagram"}
            dedup[("app", "instagram")] = ent
            entities.append(ent)

        for record in normalized_records:
            for person in record.get("people", []):
                canon = person.lower()
                if ("person", canon) not in dedup:
                    ent = {
                        "entity_type": "person",
                        "canonical_name": canon,
                        "display_name": person,
                        "importance_score": 0.8
                    }
                    dedup[("person", canon)] = ent
                    entities.append(ent)
        return list(dedup.values())
