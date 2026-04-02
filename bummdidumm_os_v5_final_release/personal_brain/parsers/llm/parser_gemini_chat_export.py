from __future__ import annotations

from ..base import BaseParser


class GeminiChatExportParser(BaseParser):
    parser_name = "parser_gemini_chat_export"
    parser_version = "1.0.0"
    source_system = "llm"
    source_service = "gemini"
    source_app = "gemini"
    source_kind = "export"
    source_format = "gemini"
    default_record_type = "llm_conversation"
    default_entity_type = "topic"
    match_tokens = ('gemini chat', 'gemini')

