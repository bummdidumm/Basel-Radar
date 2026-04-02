from __future__ import annotations

from ..base import BaseParser


class ClaudeExportParser(BaseParser):
    """Parser for claude.ai conversation exports.

    Supported structures:
    - List of conversation objects: [{"uuid": ..., "chat_messages": [...]}]
    - Wrapped: {"conversations": [...]}
    - Single conversation: {"uuid": ..., "chat_messages": [...]}
    """

    parser_name = "parser_claude_export"
    parser_version = "2.0.0"
    source_system = "llm"
    source_service = "claude"
    source_app = "claude"
    source_kind = "export"
    source_format = "json"
    default_record_type = "llm_conversation"
    match_tokens = ("claude",)

    def can_handle(self, source_meta: dict, preview) -> bool:
        haystack = f"{preview.path} {preview.name}".lower()
        if "claude" in haystack:
            return True
        cp = preview.content_preview
        # List of convs
        if isinstance(cp, list) and cp and "chat_messages" in cp[0]:
            return True
        # Wrapped
        if isinstance(cp, dict):
            convs = cp.get("conversations", [])
            if convs and isinstance(convs, list) and "chat_messages" in (convs[0] if convs else {}):
                return True
            if "chat_messages" in cp:
                return True
        return False

    def parse_to_records(self, source_meta: dict, content) -> list[dict]:
        if isinstance(content, list):
            conversations = content
        elif isinstance(content, dict):
            conversations = content.get("conversations", [])
            if not conversations and "chat_messages" in content:
                conversations = [content]
        else:
            conversations = []

        if not conversations:
            return super().parse_to_records(source_meta, content if isinstance(content, dict) else {})

        records = []
        for conv in conversations:
            conv_id = conv.get("uuid", conv.get("id", ""))
            created = conv.get("created_at", conv.get("create_time", ""))
            updated = conv.get("updated_at", "")
            messages = conv.get("chat_messages", conv.get("messages", []))

            records.append({
                "record_type": "llm_conversation",
                "subtype": "claude",
                "event_time_start": created,
                "event_time_end": updated,
                "event_date": created[:10] if created else "",
                "title": conv.get("name", conv.get("title", f"Claude conversation {conv_id}")),
                "summary": f"{len(messages)} messages",
                "raw_text": "\n".join(
                    m.get("text", m.get("content", ""))[:300] for m in messages
                ),
                "normalized_text": " ".join(
                    m.get("text", m.get("content", "")) for m in messages
                ),
                "apps": ["claude"],
                "topics": conv.get("topics", []),
                "conversation_id": conv_id,
                "external_id": conv_id,
                "confidence": 0.95,
                "importance_score": 0.75,
            })

            for idx, msg in enumerate(messages):
                ts = msg.get("created_at", msg.get("timestamp", created))
                sender = msg.get("sender", msg.get("role", "unknown"))
                text = msg.get("text", msg.get("content", ""))
                msg_id = msg.get("uuid", msg.get("id", f"{conv_id}:{idx}"))
                records.append({
                    "record_type": "llm_turn",
                    "subtype": sender,
                    "event_time_start": ts,
                    "event_date": ts[:10] if ts else (created[:10] if created else ""),
                    "title": f"Turn {idx + 1} ({sender})",
                    "summary": text[:200],
                    "raw_text": text,
                    "normalized_text": text,
                    "apps": ["claude"],
                    "topics": [],
                    "conversation_id": conv_id,
                    "message_id": msg_id,
                    "external_id": msg_id,
                    "confidence": 0.9,
                    "importance_score": 0.45,
                })

        return records

    def extract_entities(self, records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(records, source_meta)
        entities.append({"entity_type": "provider", "canonical_name": "anthropic", "display_name": "Anthropic"})
        entities.append({"entity_type": "app", "canonical_name": "claude", "display_name": "Claude"})
        seen_convs: set[str] = set()
        for r in records:
            cid = r.get("conversation_id", "")
            if cid and cid not in seen_convs:
                seen_convs.add(cid)
                entities.append({
                    "entity_type": "conversation",
                    "canonical_name": cid.lower(),
                    "display_name": cid,
                })
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}
        return list(dedup.values())
