from __future__ import annotations

from ..base import BaseParser


class GenericJsonExportParser(BaseParser):
    parser_name = "parser_generic_json_export"
    parser_version = "2.0.0"
    source_system = "generic"
    source_service = "json"
    source_app = "json"
    source_kind = "export"
    source_format = "json"
    default_record_type = "generic_json_export"
    match_tokens = (".json", "export")

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        if isinstance(content, dict) and "items" in content and isinstance(content["items"], list):
            records = []
            for item in content["items"]:
                ts = item.get("timestamp", "")
                records.append({
                    "record_type": item.get("record_type", "generic_json_export"),
                    "subtype": item.get("subtype", "item"),
                    "event_time_start": ts,
                    "event_date": ts[:10] if ts else "",
                    "title": item.get("title", "Generic JSON Item"),
                    "summary": item.get("summary", ""),
                    "raw_text": item.get("raw_text", ""),
                    "normalized_text": item.get("raw_text", ""),
                    "topics": item.get("topics", []),
                    "apps": item.get("apps", []),
                    "people": item.get("people", []),
                    "url": item.get("url", ""),
                    "external_id": item.get("id", ""),
                    "confidence": item.get("confidence", 0.6),
                    "importance_score": item.get("importance_score", 0.4),
                })
            return records
        return super().parse_to_records(source_meta, content)
