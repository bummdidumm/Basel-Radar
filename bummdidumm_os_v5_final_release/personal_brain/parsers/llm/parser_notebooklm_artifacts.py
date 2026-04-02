from __future__ import annotations

from ..base import BaseParser


class NotebookLMArtifactsParser(BaseParser):
    parser_name = "parser_notebooklm_artifacts"
    parser_version = "1.0.0"
    source_system = "llm"
    source_service = "notebooklm"
    source_app = "notebooklm"
    source_kind = "export"
    source_format = "notebooklm"
    default_record_type = "llm_artifact_reference"
    default_entity_type = "topic"
    match_tokens = ('notebooklm',)
