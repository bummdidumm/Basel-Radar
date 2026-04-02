from __future__ import annotations

from ..base import BaseParser


class GoogleMapsPlacesParser(BaseParser):
    parser_name = "parser_google_maps_places"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "maps"
    source_app = "google-maps"
    source_kind = "export"
    source_format = "maps"
    default_record_type = "place_visit"
    default_entity_type = "app"
    match_tokens = ('maps', 'places')
