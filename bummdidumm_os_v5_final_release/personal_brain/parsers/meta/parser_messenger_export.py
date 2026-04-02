from __future__ import annotations

from ..base import BaseParser


class MessengerExportParser(BaseParser):
    parser_name = "parser_messenger_export"
    parser_version = "1.0.0"
    source_system = "meta"
    source_service = "messenger"
    source_app = "messenger"
    source_kind = "export"
    source_format = "messenger"
    default_record_type = "message_event"
    default_entity_type = "app"
    match_tokens = ('messenger',)

