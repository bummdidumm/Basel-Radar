from __future__ import annotations

from ..base import BaseParser


class GenericHtmlExportParser(BaseParser):
    parser_name = "parser_generic_html_export"
    parser_version = "1.0.0"
    source_system = "generic"
    source_service = "html"
    source_app = "html"
    source_kind = "export"
    source_format = "html"
    default_record_type = "generic_html_export"
    default_entity_type = "topic"
    match_tokens = ('.html', 'export')

