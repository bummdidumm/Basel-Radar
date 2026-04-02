from __future__ import annotations

from ..base import BaseParser


class TelegramExportParser(BaseParser):
    parser_name = "parser_telegram_export"
    parser_version = "1.0.0"
    source_system = "messaging"
    source_service = "telegram"
    source_app = "telegram"
    source_kind = "export"
    source_format = "telegram"
    default_record_type = "message_event"
    default_entity_type = "topic"
    match_tokens = ('telegram',)
