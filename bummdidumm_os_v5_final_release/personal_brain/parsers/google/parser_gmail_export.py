from __future__ import annotations

from ..base import BaseParser


class GmailExportParser(BaseParser):
    parser_name = "parser_gmail_export"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "gmail"
    source_app = "gmail"
    source_kind = "export"
    source_format = "gmail"
    default_record_type = "message_event"
    default_entity_type = "app"
    match_tokens = ('gmail', '.mbox')
