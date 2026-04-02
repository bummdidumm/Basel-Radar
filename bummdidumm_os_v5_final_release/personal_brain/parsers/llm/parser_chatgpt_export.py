from __future__ import annotations

from ..base import BaseParser


class ChatGPTExportParser(BaseParser):
    parser_name = "parser_chatgpt_export"
    parser_version = "2.0.0"
    source_system = "llm"
    source_service = "chatgpt"
    source_app = "chatgpt"
    source_kind = "export"
    source_format = "json"
    default_record_type = "llm_conversation"
    # "conversations" alone is too generic (also appears in Claude/Gemini exports).
    # Match on explicit service identifiers; key_match is disabled to avoid false positives.
    match_tokens = ("chatgpt", "openai")
    required_json_keys = ()

    def can_handle(self, source_meta: dict, preview) -> bool:
        haystack = f"{preview.path} {preview.name}".lower()
        if any(t in haystack for t in self.match_tokens):
            return True
        # JSON with {"conversations": [{"turns": [...], "model": ...}]} and no "chat_messages"
        # signals ChatGPT format rather than Claude (which uses "chat_messages").
        cp = preview.content_preview
        if isinstance(cp, dict) and "conversations" in cp:
            convs = cp.get("conversations", [])
            if convs and isinstance(convs, list) and "turns" in convs[0] and "chat_messages" not in convs[0]:
                return "model" in convs[0] or "create_time" in convs[0]
        return False

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        records = []
        for conv in content.get("conversations", []):
            conv_id = conv.get("id", "")
            model = conv.get("model", "unknown")
            turns = conv.get("turns", [])
            created = conv.get("create_time", "")
            records.append({
                "record_type": "llm_conversation",
                "subtype": model,
                "event_time_start": created,
                "event_date": created[:10],
                "title": conv.get("title", f"ChatGPT conversation {conv_id}"),
                "summary": f"{len(turns)} turns with model {model}",
                "raw_text": "\n".join(t.get("content", "")[:500] for t in turns),
                "normalized_text": " ".join(t.get("content", "") for t in turns),
                "apps": ["chatgpt"],
                "topics": conv.get("topics", []),
                "conversation_id": conv_id,
                "external_id": conv_id,
                "confidence": 0.95,
                "importance_score": conv.get("personal_relevance_score", 0.7),
            })
            for idx, turn in enumerate(turns):
                ts = turn.get("timestamp", created)
                role = turn.get("role", "unknown")
                records.append({
                    "record_type": "llm_turn",
                    "subtype": role,
                    "event_time_start": ts,
                    "event_date": ts[:10],
                    "title": f"Turn {idx+1} ({role})",
                    "summary": turn.get("content", "")[:200],
                    "raw_text": turn.get("content", ""),
                    "normalized_text": turn.get("content", ""),
                    "apps": ["chatgpt"],
                    "topics": conv.get("topics", []),
                    "conversation_id": conv_id,
                    "message_id": turn.get("id", f"{conv_id}:{idx}"),
                    "external_id": turn.get("id", f"{conv_id}:{idx}"),
                    "confidence": 0.9,
                    "importance_score": 0.45,
                })
        return records or super().parse_to_records(source_meta, content)

    def extract_entities(self, records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(records, source_meta)
        entities.append({"entity_type": "provider", "canonical_name": "openai", "display_name": "OpenAI"})
        for r in records:
            if r.get("conversation_id"):
                entities.append({
                    "entity_type": "conversation",
                    "canonical_name": r["conversation_id"].lower(),
                    "display_name": r["conversation_id"],
                })
            if r.get("subtype") and r["record_type"] == "llm_conversation":
                entities.append({
                    "entity_type": "model",
                    "canonical_name": r["subtype"].lower(),
                    "display_name": r["subtype"],
                })
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}
        return list(dedup.values())
