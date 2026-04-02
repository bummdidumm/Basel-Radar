from __future__ import annotations

from ..base import BaseParser


class LlmJsonTranscriptParser(BaseParser):
    """Generic parser for LLM JSON transcripts that don't match a specific provider.

    Handles any JSON with a top-level "messages" array whose items have
    at minimum a "role" and "content" (or "text") field.  Also handles
    a "turns" array with the same structure.

    This acts as the catch-all for Perplexity, NotebookLM, custom API
    logs, and any other LLM interaction logs that emit message arrays.
    """

    parser_name = "parser_llm_json_transcript"
    parser_version = "2.0.0"
    source_system = "llm"
    source_service = "json-transcript"
    source_app = "json"
    source_kind = "export"
    source_format = "json"
    default_record_type = "llm_turn"
    match_tokens = ("transcript", "conversation_log", "llm_json")
    required_json_keys = ("messages",)

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        messages = content.get("messages", content.get("turns", []))
        if not messages or not isinstance(messages, list):
            return super().parse_to_records(source_meta, content)

        meta = content.get("metadata", {})
        model = meta.get("model", content.get("model", "unknown"))
        conv_id = meta.get("id", content.get("id", ""))
        conv_created = meta.get("created_at", content.get("created_at", ""))

        records = []

        # Session-level record
        records.append({
            "record_type": "llm_conversation",
            "subtype": model,
            "event_time_start": conv_created,
            "event_date": conv_created[:10] if conv_created else "",
            "title": meta.get("title", content.get("title", f"LLM transcript ({model})")),
            "summary": f"{len(messages)} messages, model: {model}",
            "raw_text": "\n".join(
                m.get("content", m.get("text", ""))[:300] for m in messages
            ),
            "normalized_text": " ".join(
                m.get("content", m.get("text", "")) for m in messages
            ),
            "apps": [model] if model != "unknown" else [],
            "topics": content.get("topics", []),
            "conversation_id": conv_id,
            "external_id": conv_id,
            "confidence": 0.85,
            "importance_score": 0.6,
        })

        for idx, msg in enumerate(messages):
            role = msg.get("role", "unknown")
            text = msg.get("content", msg.get("text", ""))
            ts = msg.get("timestamp", msg.get("created_at", conv_created))
            msg_id = msg.get("id", f"{conv_id}:{idx}" if conv_id else str(idx))
            records.append({
                "record_type": "llm_turn",
                "subtype": role,
                "event_time_start": ts,
                "event_date": ts[:10] if ts else (conv_created[:10] if conv_created else ""),
                "title": f"Turn {idx + 1} ({role})",
                "summary": text[:200],
                "raw_text": text,
                "normalized_text": text,
                "apps": [model] if model != "unknown" else [],
                "topics": msg.get("topics", []),
                "conversation_id": conv_id,
                "message_id": msg_id,
                "external_id": msg_id,
                "confidence": 0.8,
                "importance_score": 0.4,
            })

        return records

    def extract_entities(self, records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(records, source_meta)
        # Extract model as entity if determinable
        for r in records:
            if r.get("record_type") == "llm_conversation" and r.get("subtype") and r["subtype"] != "unknown":
                entities.append({
                    "entity_type": "model",
                    "canonical_name": r["subtype"].lower(),
                    "display_name": r["subtype"],
                })
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}
        return list(dedup.values())
