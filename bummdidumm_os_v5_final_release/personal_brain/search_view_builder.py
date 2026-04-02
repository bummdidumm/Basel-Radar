from __future__ import annotations


def build_search_views(records: list[dict]) -> dict[str, list[dict]]:
    entries: list[dict] = []
    for rec in records:
        entries.append({
            "search_id": f"search::{rec['record_id']}",
            "primary_date": rec.get("event_date", ""),
            "compact_title": rec.get("compact_title", ""),
            "compact_summary": rec.get("compact_summary", ""),
            "record_type": rec.get("record_type", ""),
            "source_system": rec.get("source_system", ""),
            "source_service": rec.get("source_service", ""),
            "source_app": rec.get("source_app", ""),
            "related_people": rec.get("people", []),
            "related_places": rec.get("places", []),
            "related_apps": rec.get("apps", []),
            "related_topics": rec.get("topics", []),
            "related_entities": rec.get("related_entity_ids", []),
            "importance_score": rec.get("importance_score", 0.0),
            "confidence": rec.get("confidence", 0.0),
            "source_ids": [rec.get("source_id", "")],
            "record_ids": [rec.get("record_id", "")],
            "deep_link_hint": rec.get("url", ""),
            "source_path": rec.get("raw_ref", ""),
        })

    return {
        "CURRENT_personal_brain_search_view.jsonl": entries,
        "by_date.jsonl": sorted(entries, key=lambda x: (x["primary_date"], x["search_id"])),
        # Sorted by first related_entity_id so entries are grouped by entity.
        # Records with no entity assignments sort to the end.
        "by_entity.jsonl": sorted(
            entries,
            key=lambda x: (x["related_entities"][0] if x["related_entities"] else "\xff", x["search_id"]),
        ),
        "by_service.jsonl": sorted(entries, key=lambda x: (x["source_service"], x["search_id"])),
        "by_topic.jsonl": sorted(entries, key=lambda x: ("|".join(x["related_topics"]), x["search_id"])),
        "llm_conversations.jsonl": [e for e in entries if e["record_type"].startswith("llm_")],
    }
