from __future__ import annotations

from collections import defaultdict
import datetime as _dt

def _is_review_due(day: str) -> bool:
    """Spaced-Repetition: True nach 1, 7, 30, 90 Tagen."""
    try:
        delta = (_dt.date.today() - _dt.date.fromisoformat(day)).days
        return delta in {1, 7, 30, 90}
    except ValueError:
        return False

def _top_events(records: list[dict], n: int = 15) -> list[str]:
    """Importance-gewichtete Top-Events ohne Duplikate."""
    seen: set[str] = set()
    result: list[str] = []
    for r in sorted(records, key=lambda x: float(x.get("importance_score", 0.5)), reverse=True):
        title = r.get("compact_title") or r.get("title", "")
        if title and title not in seen:
            seen.add(title)
            result.append(title)
        if len(result) >= n:
            break
    return result


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
            "key_events": _top_events(day_records),
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
            "review_due": _is_review_due(day),
        }
    return result
