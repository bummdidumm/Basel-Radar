from __future__ import annotations

from ..base import BaseParser


class ThreadsExportParser(BaseParser):
    parser_name = "parser_threads_export"
    parser_version = "1.0.0"
    source_system = "meta"
    source_service = "threads"
    source_app = "threads"
    source_kind = "export"
    source_format = "threads"
    default_record_type = "social_event"
    default_entity_type = "app"
    match_tokens = ('threads',)
