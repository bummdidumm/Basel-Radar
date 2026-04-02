from __future__ import annotations

from ..base import BaseParser


class GenericTxtExportParser(BaseParser):
    parser_name = "parser_generic_txt_export"
    parser_version = "1.0.0"
    source_system = "generic"
    source_service = "txt"
    source_app = "txt"
    source_kind = "export"
    source_format = "txt"
    default_record_type = "generic_txt_export"
    default_entity_type = "topic"
    match_tokens = ('.txt', 'export')
