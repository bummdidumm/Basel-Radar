from __future__ import annotations

from collections import defaultdict


def build_daily_memory(records: list[dict]) -> dict[str, dict]:
    by_day: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        event_date = record.get("event_date")
        if event_date:
            by_day[event_date].append(record)

    result: dict[str, dict] = {}
    for day, day_records in sorted(by_day.items()):
        result[day] = {
            "date": day,
            "title": f"Daily Memory {day}",
            "summary": f"{len(day_records)} records on {day}",
            "key_events": [r.get("compact_title", r.get("title", "")) for r in day_records[:20]],
            "people": sorted({p for r in day_records for p in r.get("people", [])}),
            "places": sorted({p for r in day_records for p in r.get("places", [])}),
            "apps": sorted({a for r in day_records for a in r.get("apps", [])}),
            "purchases": [r["record_id"] for r in day_records if "purchase" in r.get("record_type", "")],
            "subscriptions": [r["record_id"] for r in day_records if "subscription" in r.get("record_type", "")],
            "tasks": [r["record_id"] for r in day_records if "task" in r.get("record_type", "")],
            "calendar_events": [r["record_id"] for r in day_records if "calendar" in r.get("record_type", "")],
            "messages": [r["record_id"] for r in day_records if "message" in r.get("record_type", "")],
            "llm_activity": [r["record_id"] for r in day_records if r.get("record_type", "").startswith("llm_")],
            "media_refs": [r.get("url") for r in day_records if r.get("url")],
            "source_ids": sorted({r.get("source_id", "") for r in day_records}),
            "record_ids": [r["record_id"] for r in day_records],
            "importance_score": round(sum(float(r.get("importance_score", 0.0)) for r in day_records), 3),
        }
    return result
