from __future__ import annotations

from ..base import BaseParser


class SignalExportParser(BaseParser):
    parser_name = "parser_signal_export"
    parser_version = "1.0.0"
    source_system = "messaging"
    source_service = "signal"
    source_app = "signal"
    source_kind = "export"
    source_format = "signal"
    default_record_type = "message_event"
    default_entity_type = "topic"
    match_tokens = ('signal',)
