from __future__ import annotations

from ..base import BaseParser


class WhatsAppExportParser(BaseParser):
    parser_name = "parser_whatsapp_export"
    parser_version = "1.0.0"
    source_system = "messaging"
    source_service = "whatsapp"
    source_app = "whatsapp"
    source_kind = "export"
    source_format = "whatsapp"
    default_record_type = "message_event"
    default_entity_type = "topic"
    match_tokens = ('whatsapp',)

