"""Aggregiert Daily Memories zu Wochen-Zusammenfassungen (Progressive Summarization)."""
from __future__ import annotations
import datetime
from collections import Counter


def build_weekly_memory(daily_memories: dict[str, dict]) -> dict[str, dict]:
    """Gruppiert Daily Memories zu ISO-Wochen (YYYY-WXX)."""
    by_week: dict[str, list[dict]] = {}
    for day_str, memory in daily_memories.items():
        try:
            d = datetime.date.fromisoformat(day_str)
            iso = d.isocalendar()
            week_key = f"{iso.year}-W{iso.week:02d}"
            by_week.setdefault(week_key, []).append(memory)
        except ValueError:
            continue

    result: dict[str, dict] = {}
    for week_key, memories in sorted(by_week.items()):
        all_people = [p for m in memories for p in m.get("people", [])]
        all_apps = [a for m in memories for a in m.get("apps", [])]
        all_events = [e for m in memories for e in m.get("key_events", [])]
        result[week_key] = {
            "week": week_key,
            "days_covered": sorted(m["date"] for m in memories),
            "day_count": len(memories),
            "total_records": sum(len(m.get("record_ids", [])) for m in memories),
            "total_importance": round(sum(m.get("importance_score", 0.0) for m in memories), 2),
            "top_people": [p for p, _ in Counter(all_people).most_common(5)],
            "top_apps": [a for a, _ in Counter(all_apps).most_common(5)],
            "weekly_highlights": list(dict.fromkeys(all_events))[:10],
            "daily_memory_ids": sorted(m["date"] for m in memories),
        }
    return result