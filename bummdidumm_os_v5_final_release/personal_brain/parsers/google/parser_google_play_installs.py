from __future__ import annotations

from ..base import BaseParser


class GooglePlayInstallsParser(BaseParser):
    def populate_profile_layer(self, records: list[dict], profile_dir: Path):
        pass # To implement full logic based on specific records

    parser_name = "parser_google_play_installs"
    parser_version = "2.0.0"
    source_system = "google"
    source_service = "play"
    source_app = "google-play"
    source_kind = "export"
    source_format = "json"
    default_record_type = "app_install"
    match_tokens = ("play", "installs", "installed_apps")
    required_json_keys = ("installed_apps",)

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        rows = content.get("installed_apps", [])
        records = []
        for row in rows:
            installed_at = row.get("installed_at", "")
            records.append({
                "record_type": "app_install",
                "subtype": row.get("install_source", "google_play"),
                "event_time_start": installed_at,
                "event_date": installed_at[:10],
                "title": f"Install {row.get('app_name','Unknown App')}",
                "summary": f"{row.get('app_name','Unknown')} on {row.get('device','unknown device')}",
                "raw_text": row.get("raw", ""),
                "apps": [row.get("app_name", "")],
                "devices": [row.get("device", "")] if row.get("device") else [],
                "accounts": [row.get("account", "")] if row.get("account") else [],
                "topics": ["install", "google_play"],
                "external_id": row.get("package_name", ""),
                "confidence": 0.95,
                "importance_score": 0.7,
            })
        return records or super().parse_to_records(source_meta, content)

    def extract_entities(self, records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(records, source_meta)
        for record in records:
            if record.get("external_id"):
                entities.append({
                    "entity_type": "app",
                    "canonical_name": record["external_id"].lower(),
                    "display_name": record["external_id"],
                    "package_name": record["external_id"],
                })
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}
        return list(dedup.values())
