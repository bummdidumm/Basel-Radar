from __future__ import annotations

from ..base import BaseParser


class LlmMarkdownBundleParser(BaseParser):
    parser_name = "parser_llm_markdown_bundle"
    parser_version = "1.0.0"
    source_system = "llm"
    source_service = "markdown-bundle"
    source_app = "markdown"
    source_kind = "export"
    source_format = "markdown"
    default_record_type = "llm_response"
    default_entity_type = "topic"
    # "llm" alone conflicts with LlmJsonTranscriptParser and other LLM parsers.
    # Match only explicit bundle identifiers; bare ".md" is handled by GenericTxt.
    match_tokens = ('llm_markdown', 'llm-markdown', 'llm_bundle')
