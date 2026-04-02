from __future__ import annotations

from ..base import BaseParser


class GenericCsvExportParser(BaseParser):
    parser_name = "parser_generic_csv_export"
    parser_version = "1.0.0"
    source_system = "generic"
    source_service = "csv"
    source_app = "csv"
    source_kind = "export"
    source_format = "csv"
    default_record_type = "generic_csv_export"
    default_entity_type = "topic"
    match_tokens = ('.csv', 'export')
