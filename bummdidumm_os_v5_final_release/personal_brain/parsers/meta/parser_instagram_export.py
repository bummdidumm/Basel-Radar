from __future__ import annotations

from ..base import BaseParser


class InstagramExportParser(BaseParser):
    parser_name = "parser_instagram_export"
    parser_version = "1.0.0"
    source_system = "meta"
    source_service = "instagram"
    source_app = "instagram"
    source_kind = "export"
    source_format = "instagram"
    default_record_type = "social_event"
    default_entity_type = "app"
    match_tokens = ('instagram',)
