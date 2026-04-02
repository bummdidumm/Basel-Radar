from __future__ import annotations

from ..base import BaseParser


class LlmJsonTranscriptParser(BaseParser):
    parser_name = "parser_llm_json_transcript"
    parser_version = "2.0.0"
    source_system = "llm"
    source_service = "json-transcript"
    source_app = "json"
    source_kind = "export"
    source_format = "json"
    default_record_type = "llm_turn"
    default_entity_type = "topic"
    match_tokens = ("transcript", "conversation_log", "llm_json")
    required_json_keys = ("messages",)
