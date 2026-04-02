from __future__ import annotations

from ..base import BaseParser


class GoogleMyActivityParser(BaseParser):
    parser_name = "parser_google_my_activity"
    parser_version = "2.0.0"
    source_system = "google"
    source_service = "my-activity"
    source_app = "google"
    source_kind = "export"
    source_format = "json"
    default_record_type = "activity_event"
    match_tokens = ("my activity", "my_activity", "google activity")
    required_json_keys = ("activity",)

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        records = []
        for evt in content.get("activity", []):
            ts = evt.get("time", "")
            records.append({
                "record_type": "activity_event",
                "subtype": evt.get("product", "unknown"),
                "event_time_start": ts,
                "event_date": ts[:10],
                "title": evt.get("title", "Google activity"),
                "summary": evt.get("description", ""),
                "raw_text": evt.get("description", ""),
                "apps": [evt.get("product", "")],
                "topics": [evt.get("type", "activity")],
                "url": evt.get("url", ""),
                "external_id": evt.get("id", ""),
                "confidence": 0.9,
                "importance_score": 0.55,
            })
        return records or super().parse_to_records(source_meta, content)
