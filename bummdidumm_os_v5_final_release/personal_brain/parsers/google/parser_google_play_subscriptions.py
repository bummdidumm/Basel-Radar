from __future__ import annotations

from ..base import BaseParser


class GooglePlaySubscriptionsParser(BaseParser):
    parser_name = "parser_google_play_subscriptions"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "play"
    source_app = "google-play"
    source_kind = "export"
    source_format = "play"
    default_record_type = "subscription_event"
    default_entity_type = "app"
    match_tokens = ('play', 'subscription')
