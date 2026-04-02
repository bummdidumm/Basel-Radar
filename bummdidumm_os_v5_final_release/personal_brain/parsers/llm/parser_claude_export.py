from __future__ import annotations

from ..base import BaseParser


class ClaudeExportParser(BaseParser):
    parser_name = "parser_claude_export"
    parser_version = "1.0.0"
    source_system = "llm"
    source_service = "claude"
    source_app = "claude"
    source_kind = "export"
    source_format = "claude"
    default_record_type = "llm_conversation"
    default_entity_type = "topic"
    match_tokens = ('claude',)

