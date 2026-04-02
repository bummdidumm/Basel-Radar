from __future__ import annotations

from ..base import BaseParser


class GoogleCalendarParser(BaseParser):
    parser_name = "parser_google_calendar"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "calendar"
    source_app = "google-calendar"
    source_kind = "export"
    source_format = "calendar"
    default_record_type = "calendar_event"
    default_entity_type = "app"
    match_tokens = ('calendar', '.ics')

