from __future__ import annotations

import re

from ..base import BaseParser


# European format: [15.03.2025, 14:00:00] Name: Message
_EU = re.compile(
    r"^\[(\d{2})\.(\d{2})\.(\d{4}),\s*(\d{2}):(\d{2}):(\d{2})\]\s+([^:]+):\s(.+)$",
    re.MULTILINE,
)
# US format: 3/15/25, 2:00 PM - Name: Message
_US = re.compile(
    r"^(\d{1,2})/(\d{1,2})/(\d{2,4}),\s*(\d{1,2}):(\d{2})\s*(AM|PM)\s*-\s*([^:]+):\s(.+)$",
    re.MULTILINE,
)


def _eu_to_iso(dd: str, mm: str, yyyy: str, hh: str, mi: str, ss: str) -> str:
    return f"{yyyy}-{mm}-{dd}T{hh}:{mi}:{ss}Z"


def _us_to_iso(mo: str, dd: str, yy: str, hh: str, mi: str, ampm: str) -> str:
    year = int(yy)
    if year < 100:
        year += 2000
    hour = int(hh)
    if ampm.upper() == "PM" and hour != 12:
        hour += 12
    elif ampm.upper() == "AM" and hour == 12:
        hour = 0
    return f"{year:04d}-{int(mo):02d}-{int(dd):02d}T{hour:02d}:{int(mi):02d}:00Z"


class WhatsAppExportParser(BaseParser):
    """Parser for WhatsApp chat text exports (.txt or .zip containing .txt).

    Supports both the European date format used in Germany/Switzerland:
        [DD.MM.YYYY, HH:MM:SS] Sender: Message
    and the US format:
        MM/DD/YY, H:MM AM/PM - Sender: Message

    Each message line becomes one message_event record.
    """

    parser_name = "parser_whatsapp_export"
    parser_version = "2.0.0"
    source_system = "messaging"
    source_service = "whatsapp"
    source_app = "whatsapp"
    source_kind = "export"
    source_format = "txt"
    default_record_type = "message_event"
    match_tokens = ("whatsapp",)

    def can_handle(self, source_meta: dict, preview) -> bool:
        haystack = f"{preview.path} {preview.name}".lower()
        if "whatsapp" in haystack:
            return True
        text = preview.text_preview or ""
        if text and (_EU.search(text) or _US.search(text)):
            return True
        return False

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        raw = content.get("raw_text", "")
        if not raw:
            return super().parse_to_records(source_meta, content)

        records = []
        senders: set[str] = set()

        # Try European format first
        for m in _EU.finditer(raw):
            dd, mm, yyyy, hh, mi, ss, sender, text = m.groups()
            ts = _eu_to_iso(dd, mm, yyyy, hh, mi, ss)
            date = f"{yyyy}-{mm}-{dd}"
            sender = sender.strip()
            senders.add(sender)
            records.append({
                "record_type": "message_event",
                "subtype": "whatsapp_text",
                "event_time_start": ts,
                "event_date": date,
                "title": f"{sender}: {text[:60]}",
                "summary": text[:200],
                "raw_text": text,
                "normalized_text": text.lower(),
                "people": [sender],
                "apps": ["whatsapp"],
                "topics": ["messaging"],
                "external_id": f"{ts}:{sender}",
                "confidence": 0.92,
                "importance_score": 0.5,
            })

        # US format fallback if no EU matches
        if not records:
            for m in _US.finditer(raw):
                mo, dd, yy, hh, mi, ampm, sender, text = m.groups()
                ts = _us_to_iso(mo, dd, yy, hh, mi, ampm)
                date = ts[:10]
                sender = sender.strip()
                senders.add(sender)
                records.append({
                    "record_type": "message_event",
                    "subtype": "whatsapp_text",
                    "event_time_start": ts,
                    "event_date": date,
                    "title": f"{sender}: {text[:60]}",
                    "summary": text[:200],
                    "raw_text": text,
                    "normalized_text": text.lower(),
                    "people": [sender],
                    "apps": ["whatsapp"],
                    "topics": ["messaging"],
                    "external_id": f"{ts}:{sender}",
                    "confidence": 0.9,
                    "importance_score": 0.5,
                })

        return records or super().parse_to_records(source_meta, content)

    def extract_entities(self, records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(records, source_meta)
        entities.append({"entity_type": "app", "canonical_name": "whatsapp", "display_name": "WhatsApp"})
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}
        return list(dedup.values())

    def build_relations(self, records: list[dict], entities: list[dict], source_meta: dict) -> list[dict]:
        rels = []
        entity_names = {e["canonical_name"]: e["entity_type"] for e in entities}
        for record in records:
            for person in record.get("people", []):
                key = person.lower()
                if key in entity_names:
                    rels.append({
                        "subject": key,
                        "subject_type": "person",
                        "predicate": "sent_message",
                        "object": "whatsapp",
                        "object_type": "app",
                        "time_start": record.get("event_time_start", ""),
                        "confidence": 0.9,
                        "status": "active",
                        "evidence_external_id": record.get("external_id", ""),
                    })
        return rels
