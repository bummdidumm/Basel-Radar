from __future__ import annotations

from ..base import BaseParser


class GooglePlayDevicesParser(BaseParser):
    def populate_profile_layer(self, records: list[dict], profile_dir: Path):
        pass # To implement full logic based on specific records

    parser_name = "parser_google_play_devices"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "play"
    source_app = "google-play"
    source_kind = "export"
    source_format = "play"
    default_record_type = "device_event"
    default_entity_type = "app"
    match_tokens = ('play', 'device')
