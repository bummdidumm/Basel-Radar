from __future__ import annotations

from ..base import BaseParser


class GoogleTimelineParser(BaseParser):
    parser_name = "parser_google_timeline"
    parser_version = "2.0.0"
    source_system = "google"
    source_service = "timeline"
    source_app = "google-maps"
    source_kind = "export"
    source_format = "json"
    default_record_type = "place_visit"
    match_tokens = ("timeline", "location history", "semantic location")
    required_json_keys = ("timeline_objects",)

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        records = []
        for obj in content.get("timeline_objects", []):
            if "placeVisit" in obj:
                visit = obj["placeVisit"]
                loc = visit.get("location", {})
                duration = visit.get("duration", {})
                ts = duration.get("startTimestamp", "")
                records.append({
                    "record_type": "place_visit",
                    "subtype": "timeline_place_visit",
                    "event_time_start": ts,
                    "event_time_end": duration.get("endTimestamp", ""),
                    "event_date": ts[:10],
                    "title": f"Visited {loc.get('name', 'Unknown Place')}",
                    "summary": loc.get("address", ""),
                    "places": [loc.get("name", "")],
                    "place_name": loc.get("name", ""),
                    "geo_lat": loc.get("latitudeE7", 0) / 1e7 if loc.get("latitudeE7") else None,
                    "geo_lon": loc.get("longitudeE7", 0) / 1e7 if loc.get("longitudeE7") else None,
                    "topics": ["visit", "timeline"],
                    "confidence": 0.96,
                    "importance_score": 0.8,
                })
        return records or super().parse_to_records(source_meta, content)
