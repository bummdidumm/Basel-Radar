from __future__ import annotations

from ..base import BaseParser


class PromptBundleParser(BaseParser):
    parser_name = "parser_prompt_bundle"
    parser_version = "1.0.0"
    source_system = "llm"
    source_service = "prompt-bundle"
    source_app = "prompt-bundle"
    source_kind = "export"
    source_format = "bundle"
    default_record_type = "llm_prompt"
    default_entity_type = "topic"
    match_tokens = ('prompt bundle', 'prompts')

