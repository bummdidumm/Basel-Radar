from __future__ import annotations

SOURCE_REQUIRED_FIELDS = [
    "project_id","source_id","source_key","bundle_id","parent_bundle_id","source_system","source_service",
    "source_subservice","source_app","source_kind","source_format","source_path","source_path_rel","original_filename",
    "normalized_filename","mime","ext","checksum_sha256","semantic_hash","parser_name","parser_version","parser_status",
    "parse_error","parse_warning","export_time","coverage_start","coverage_end","created_at","modified_at","scanned_at",
    "llm_readiness","sensitivity","status","sot_status","canonical_format","is_export","is_bundle","is_archive","is_incremental",
    "contains_pii","contains_geo","contains_financial","contains_messages","contains_media_refs","record_count","entity_count",
    "relation_count","source_url","raw_ref"
]

RECORD_REQUIRED_FIELDS = [
    "record_id","source_id","source_key","record_type","subtype","source_system","source_service","source_app",
    "event_time_start","event_time_end","event_date","ingestion_time","title","compact_title","summary","compact_summary",
    "raw_text","normalized_text","status","confidence","importance_score","people","places","apps","devices","accounts",
    "topics","tags","geo_lat","geo_lon","place_name","amount","currency","quantity","url","external_id","conversation_id",
    "message_id","thread_id","related_entity_ids","related_record_ids","raw_ref","checksum_sha256"
]

ENTITY_REQUIRED_FIELDS = [
    "entity_id",
    "knowledge_tier",
    "staleness_days",
    "is_stale",
    "exclude_from_context",
    "aliases",
    "merge_status",
    "canonical_entity_id","entity_type","canonical_name","display_name","aliases","first_seen","last_seen","source_systems","source_ids",
    "tags","importance_score","current_status","related_record_count","related_relation_count","summary","compact_summary"
]

RELATION_REQUIRED_FIELDS = [
    "relation_id","subject_entity_id","predicate","object_entity_id","time_start","time_end","evidence_record_ids",
    "source_ids","confidence","status"
]

DAILY_REQUIRED_FIELDS = [
    "date","title","summary","key_events","people","places","apps","purchases","subscriptions","tasks","calendar_events",
    "messages","llm_activity","media_refs","source_ids","record_ids","importance_score"
]

SEARCH_REQUIRED_FIELDS = [
    "search_id","primary_date","compact_title","compact_summary","record_type","source_system","source_service","source_app",
    "related_people","related_places","related_apps","related_topics","related_entities","importance_score","confidence",
    "source_ids","record_ids","deep_link_hint","source_path"
]
