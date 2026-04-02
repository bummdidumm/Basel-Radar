from __future__ import annotations

from ..base import BaseParser


class GoogleContactsParser(BaseParser):
    parser_name = "parser_google_contacts"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "contacts"
    source_app = "google-contacts"
    source_kind = "export"
    source_format = "contacts"
    default_record_type = "contact_event"
    default_entity_type = "app"
    match_tokens = ('contacts', '.vcf')
