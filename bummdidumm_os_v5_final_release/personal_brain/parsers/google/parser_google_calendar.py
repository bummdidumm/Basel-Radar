from __future__ import annotations

import re

from ..base import BaseParser


def _ics_dt_to_iso(val: str) -> str:
    """Convert ICS datetime string to ISO-8601.

    Handles:
    - 20250315T120000Z  -> 2025-03-15T12:00:00Z
    - 20250315T120000   -> 2025-03-15T12:00:00
    - 20250315          -> 2025-03-15
    """
    val = val.strip()
    # Strip VALUE=DATE-TIME: or TZID=... prefix
    if ":" in val:
        val = val.split(":")[-1].strip()
    if "T" in val:
        base = val.rstrip("Z")
        suffix = "Z" if val.endswith("Z") else ""
        if len(base) >= 15:
            return f"{base[0:4]}-{base[4:6]}-{base[6:8]}T{base[9:11]}:{base[11:13]}:{base[13:15]}{suffix}"
    elif len(val) == 8 and val.isdigit():
        return f"{val[0:4]}-{val[4:6]}-{val[6:8]}"
    return val


def _ics_field(event_text: str, name: str) -> str:
    """Extract a simple single-line field from an ICS VEVENT block."""
    m = re.search(rf"^{re.escape(name)}[;:][^\r\n]*$", event_text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return ""
    raw = m.group(0)
    # Field value is everything after the first colon
    colon = raw.index(":")
    return raw[colon + 1:].strip()


def _ics_multiline(event_text: str, name: str) -> str:
    """Extract a possibly folded multi-line ICS field."""
    pattern = re.compile(
        rf"^{re.escape(name)}[;:](.*?)(?=\r?\n[^\s]|\Z)",
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(event_text)
    if not m:
        return ""
    # Un-fold: continuation lines start with whitespace
    folded = m.group(1)
    unfolded = re.sub(r"\r?\n[ \t]", "", folded)
    return unfolded.strip()


class GoogleCalendarParser(BaseParser):
    """Parser for Google Calendar exports in iCalendar (.ics) format.

    Each VEVENT block becomes one calendar_event record.
    Also handles a simplified JSON format from Google Takeout
    ({"events": [{"summary": ..., "start": {"dateTime": ...}, ...}]}).
    """

    parser_name = "parser_google_calendar"
    parser_version = "2.0.0"
    source_system = "google"
    source_service = "calendar"
    source_app = "google-calendar"
    source_kind = "export"
    source_format = "ics"
    default_record_type = "calendar_event"
    match_tokens = ("calendar", ".ics")

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        raw = content.get("raw_text", "")
        records = []

        # --- ICS text path ---
        if raw and "BEGIN:VEVENT" in raw:
            event_blocks = re.findall(
                r"BEGIN:VEVENT(.*?)END:VEVENT", raw, re.DOTALL | re.IGNORECASE
            )
            for block in event_blocks:
                dtstart_raw = _ics_field(block, "DTSTART")
                dtend_raw = _ics_field(block, "DTEND")
                dtstart = _ics_dt_to_iso(dtstart_raw) if dtstart_raw else ""
                dtend = _ics_dt_to_iso(dtend_raw) if dtend_raw else ""
                summary = _ics_field(block, "SUMMARY")
                description = _ics_multiline(block, "DESCRIPTION")
                location = _ics_field(block, "LOCATION")
                uid = _ics_field(block, "UID")

                records.append({
                    "record_type": "calendar_event",
                    "subtype": "icalendar",
                    "event_time_start": dtstart,
                    "event_time_end": dtend,
                    "event_date": dtstart[:10] if dtstart else "",
                    "title": summary or "Calendar event",
                    "summary": description[:200] if description else summary,
                    "raw_text": block.strip(),
                    "normalized_text": f"{summary} {description} {location}".strip(),
                    "places": [location] if location else [],
                    "place_name": location,
                    "apps": ["google-calendar"],
                    "topics": ["calendar", "event"],
                    "external_id": uid,
                    "confidence": 0.95,
                    "importance_score": 0.7,
                })
            if records:
                return records

        # --- JSON path (Google Takeout calendar.json) ---
        events = content.get("events", [])
        for evt in events:
            start = evt.get("start", {})
            end = evt.get("end", {})
            ts = start.get("dateTime", start.get("date", ""))
            te = end.get("dateTime", end.get("date", ""))
            location = evt.get("location", "")
            records.append({
                "record_type": "calendar_event",
                "subtype": "google_takeout",
                "event_time_start": ts,
                "event_time_end": te,
                "event_date": ts[:10] if ts else "",
                "title": evt.get("summary", "Calendar event"),
                "summary": evt.get("description", "")[:200],
                "raw_text": evt.get("description", ""),
                "normalized_text": f"{evt.get('summary', '')} {evt.get('description', '')} {location}".strip(),
                "places": [location] if location else [],
                "place_name": location,
                "apps": ["google-calendar"],
                "topics": ["calendar", "event"],
                "external_id": evt.get("id", evt.get("iCalUID", "")),
                "confidence": 0.95,
                "importance_score": 0.7,
            })

        return records or super().parse_to_records(source_meta, content)

    def extract_entities(self, records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(records, source_meta)
        entities.append({"entity_type": "app", "canonical_name": "google-calendar", "display_name": "Google Calendar"})
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}
        return list(dedup.values())
