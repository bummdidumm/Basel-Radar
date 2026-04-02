from __future__ import annotations

from ..base import BaseParser


class FacebookExportParser(BaseParser):
    parser_name = "parser_facebook_export"
    parser_version = "1.0.0"
    source_system = "meta"
    source_service = "facebook"
    source_app = "facebook"
    source_kind = "export"
    source_format = "facebook"
    default_record_type = "social_event"
    default_entity_type = "app"
    match_tokens = ('facebook',)

