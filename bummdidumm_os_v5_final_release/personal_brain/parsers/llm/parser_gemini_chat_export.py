from __future__ import annotations

from ..base import BaseParser


class GeminiChatExportParser(BaseParser):
    """Parser for Google Gemini chat exports (Google Takeout / manual export).

    Expected structure:
        {"conversations": [{"id": "...", "title": "...", "createTime": "...",
                            "turns": [{"role": "user|model", "content": "...",
                                       "timestamp": "..."}]}]}
    """

    parser_name = "parser_gemini_chat_export"
    parser_version = "2.0.0"
    source_system = "llm"
    source_service = "gemini"
    source_app = "gemini"
    source_kind = "export"
    source_format = "json"
    default_record_type = "llm_conversation"
    match_tokens = ("gemini chat", "gemini")
    required_json_keys = ("conversations",)

    def can_handle(self, source_meta: dict, preview) -> bool:
        haystack = f"{preview.path} {preview.name} {preview.text_preview}".lower()
        if "gemini" in haystack:
            cp = preview.content_preview
            # Accept if it looks like a Gemini chat export (has conversations with turns)
            if isinstance(cp, dict) and "conversations" in cp:
                convs = cp["conversations"]
                if isinstance(convs, list) and convs:
                    return "turns" in convs[0] or "createTime" in convs[0]
        return False

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        conversations = content.get("conversations", [])
        if not conversations:
            return super().parse_to_records(source_meta, content)

        records = []
        for conv in conversations:
            conv_id = conv.get("id", "")
            created = conv.get("createTime", conv.get("create_time", ""))
            turns = conv.get("turns", conv.get("messages", []))

            records.append({
                "record_type": "llm_conversation",
                "subtype": "gemini",
                "event_time_start": created,
                "event_date": created[:10] if created else "",
                "title": conv.get("title", f"Gemini conversation {conv_id}"),
                "summary": f"{len(turns)} turns",
                "raw_text": "\n".join(
                    t.get("content", t.get("text", ""))[:300] for t in turns
                ),
                "normalized_text": " ".join(
                    t.get("content", t.get("text", "")) for t in turns
                ),
                "apps": ["gemini"],
                "topics": conv.get("topics", []),
                "conversation_id": conv_id,
                "external_id": conv_id,
                "confidence": 0.93,
                "importance_score": 0.7,
            })

            for idx, turn in enumerate(turns):
                ts = turn.get("timestamp", turn.get("createTime", created))
                role = turn.get("role", "unknown")
                text = turn.get("content", turn.get("text", ""))
                turn_id = turn.get("id", f"{conv_id}:{idx}")
                records.append({
                    "record_type": "llm_turn",
                    "subtype": role,
                    "event_time_start": ts,
                    "event_date": ts[:10] if ts else (created[:10] if created else ""),
                    "title": f"Turn {idx + 1} ({role})",
                    "summary": text[:200],
                    "raw_text": text,
                    "normalized_text": text,
                    "apps": ["gemini"],
                    "topics": [],
                    "conversation_id": conv_id,
                    "message_id": turn_id,
                    "external_id": turn_id,
                    "confidence": 0.9,
                    "importance_score": 0.4,
                })

        return records

    def extract_entities(self, records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(records, source_meta)
        entities.append({"entity_type": "provider", "canonical_name": "google", "display_name": "Google"})
        entities.append({"entity_type": "app", "canonical_name": "gemini", "display_name": "Gemini"})
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
