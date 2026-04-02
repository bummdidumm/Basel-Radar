from __future__ import annotations

from ..base import BaseParser


class PerplexityExportParser(BaseParser):
    parser_name = "parser_perplexity_export"
    parser_version = "1.0.0"
    source_system = "llm"
    source_service = "perplexity"
    source_app = "perplexity"
    source_kind = "export"
    source_format = "perplexity"
    default_record_type = "llm_conversation"
    default_entity_type = "topic"
    match_tokens = ('perplexity',)
