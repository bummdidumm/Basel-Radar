from __future__ import annotations

from ..base import BaseParser


class GoogleKeepParser(BaseParser):
    parser_name = "parser_google_keep"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "keep"
    source_app = "google-keep"
    source_kind = "export"
    source_format = "keep"
    default_record_type = "note_event"
    default_entity_type = "app"
    match_tokens = ('keep', 'note')

