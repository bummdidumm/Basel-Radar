from __future__ import annotations

from ..base import BaseParser

class TelegramExportParser(BaseParser):
    parser_name = "parser_telegram_export"
    parser_version = "2.0.0"
    source_system = "telegram"
    source_service = "telegram"
    source_app = "telegram"
    source_kind = "export"
    source_format = "json"
    default_record_type = "message_event"
    match_tokens = ("telegram", "result.json")

    def can_handle(self, source_meta: dict, preview: dict) -> bool:
        if "telegram" in source_meta.get("original_filename", "").lower() or "result.json" in source_meta.get("original_filename", "").lower():
            content_preview = getattr(preview, "content_preview", preview)
            if isinstance(content_preview, dict) and ("chats" in content_preview or "about" in content_preview):
                return True
        return False

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        records = []
        chats = content.get("chats", {}).get("list", [])
        if not chats:
            return super().parse_to_records(source_meta, content)

        for chat in chats:
            chat_name = chat.get("name", "Unknown Chat")
            for msg in chat.get("messages", []):
                if msg.get("type") == "message":
                    ts = msg.get("date", "")
                    sender = msg.get("from", "Unknown")
                    text = msg.get("text", "")
                    if isinstance(text, list):
                        text = "".join([t if isinstance(t, str) else t.get("text", "") for t in text])

                    records.append({
                        "record_type": "message_event",
                        "subtype": "telegram_message",
                        "event_time_start": ts,
                        "event_date": ts[:10] if ts else "",
                        "title": f"Message from {sender} in {chat_name}",
                        "summary": text[:200],
                        "raw_text": text,
                        "people": [sender],
                        "external_id": str(msg.get("id", "")),
                        "conversation_id": str(chat.get("id", ""))
                    })
        return records

    def extract_entities(self, normalized_records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(normalized_records, source_meta)
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}

        # Add Telegram app entity
        if ("app", "telegram") not in dedup:
            ent = {"entity_type": "app", "canonical_name": "telegram", "display_name": "Telegram"}
            dedup[("app", "telegram")] = ent
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
