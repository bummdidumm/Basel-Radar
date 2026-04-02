from __future__ import annotations

from ..base import BaseParser


class GoogleDriveExportParser(BaseParser):
    parser_name = "parser_google_drive_export"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "drive"
    source_app = "google-drive"
    source_kind = "export"
    source_format = "drive"
    default_record_type = "drive_export_event"
    default_entity_type = "app"
    match_tokens = ('drive export', 'docs')
