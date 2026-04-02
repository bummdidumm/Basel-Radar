from __future__ import annotations

from ..base import BaseParser


class GeminiExportsParser(BaseParser):
    parser_name = "parser_gemini_exports"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "gemini"
    source_app = "gemini"
    source_kind = "export"
    source_format = "gemini"
    default_record_type = "llm_conversation"
    default_entity_type = "app"
    match_tokens = ('gemini export', 'gemini')

