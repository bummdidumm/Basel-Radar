from __future__ import annotations

from ..base import BaseParser


class LlmHtmlExportParser(BaseParser):
    parser_name = "parser_llm_html_export"
    parser_version = "1.0.0"
    source_system = "llm"
    source_service = "html-export"
    source_app = "html"
    source_kind = "export"
    source_format = "html"
    default_record_type = "llm_response"
    default_entity_type = "topic"
    match_tokens = ('conversation', '.html')

