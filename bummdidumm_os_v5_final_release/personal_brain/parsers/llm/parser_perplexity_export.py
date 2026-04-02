from __future__ import annotations

from ..base import BaseParser


class PerplexityExportParser(BaseParser):
    parser_name = "parser_perplexity_export"
    parser_version = "1.0.0"
    source_system = "llm"
    source_service = "perplexity"
    source_app = "perplexity"
    source_kind = "export"
    source_format = "perplexity"
    default_record_type = "llm_conversation"
    default_entity_type = "topic"
    match_tokens = ('perplexity',)

    def can_handle(self, source_meta: dict, preview: dict) -> bool:
        name = source_meta.get("original_filename", "").lower()
        return "perplexity" in name

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        records = []
        threads = content.get("threads", [])
        if not threads:
            return super().parse_to_records(source_meta, content)

        for thread in threads:
            thread_id = thread.get("id", "")
            title = thread.get("title", "Perplexity Thread")
            ts = thread.get("created_at", "")

            records.append({
                "record_type": "llm_conversation",
                "subtype": "perplexity_thread",
                "event_time_start": ts,
                "event_date": ts[:10] if ts else "",
                "title": title,
                "external_id": str(thread_id),
                "conversation_id": str(thread_id),
                "summary": title
            })

            for turn in thread.get("turns", []):
                role = turn.get("role", "unknown")
                turn_ts = turn.get("timestamp", ts)
                text = turn.get("content", "")

                records.append({
                    "record_type": "llm_turn",
                    "subtype": role,
                    "event_time_start": turn_ts,
                    "event_date": turn_ts[:10] if turn_ts else "",
                    "title": f"Turn ({role}) in {title}",
                    "summary": text[:200],
                    "raw_text": text,
                    "conversation_id": str(thread_id),
                })
        return records

    def extract_entities(self, normalized_records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(normalized_records, source_meta)
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}

        if ("app", "perplexity") not in dedup:
            ent = {"entity_type": "app", "canonical_name": "perplexity", "display_name": "Perplexity"}
            dedup[("app", "perplexity")] = ent
            entities.append(ent)

        return list(dedup.values())
