from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable_payload(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(_stable_payload(value).encode("utf-8")).hexdigest()


def source_id(project_id: str, source_key: str) -> str:
    return f"src::{stable_hash({'project_id': project_id, 'source_key': source_key})[:20]}"


def record_id(source_id_value: str, record_type: str, external_id: str, event_time_start: str, title: str) -> str:
    payload = {
        "source_id": source_id_value,
        "record_type": record_type,
        "external_id": external_id,
        "event_time_start": event_time_start,
        "title": title,
    }
    return f"rec::{stable_hash(payload)[:20]}"


def entity_id(entity_type: str, canonical_name: str) -> str:
    return f"ent::{stable_hash({'entity_type': entity_type, 'canonical_name': canonical_name.lower()})[:20]}"


def relation_id(subject_entity_id: str, predicate: str, object_entity_id: str, evidence_record_ids: list[str]) -> str:
    payload = {
        "subject": subject_entity_id,
        "predicate": predicate,
        "object": object_entity_id,
        "evidence": sorted(evidence_record_ids),
    }
    return f"rel::{stable_hash(payload)[:20]}"
