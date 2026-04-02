from __future__ import annotations

from ..base import BaseParser


class GenericZipBundleParser(BaseParser):
    parser_name = "parser_generic_zip_bundle"
    parser_version = "1.0.0"
    source_system = "generic"
    source_service = "zip"
    source_app = "zip"
    source_kind = "export"
    source_format = "zip"
    default_record_type = "generic_zip_bundle"
    default_entity_type = "topic"
    match_tokens = ('.zip', 'takeout')
