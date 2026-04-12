from __future__ import annotations

from ..base import BaseParser

class GoogleContactsParser(BaseParser):
    parser_name = "parser_google_contacts"
    parser_version = "2.0.0"
    source_system = "google"
    source_service = "contacts"
    source_app = "google-contacts"
    source_kind = "export"
    source_format = "json"
    default_record_type = "contacts_export"
    match_tokens = ("contacts", "google")

    from personal_brain.parsers.base import SourcePreview
    def can_handle(self, source_meta: dict, preview: SourcePreview) -> bool:
        if "contacts" in source_meta.get("original_filename", "").lower():
            return True
        return False

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        records = []
        contacts = content.get("contacts", [])
        if not contacts:
            return super().parse_to_records(source_meta, content)

        for contact in contacts:
            raw_name = contact.get("name")
            name = raw_name if raw_name is not None else "Unknown"
            records.append({
                "record_type": "contacts_export",
                "subtype": "contact",
                "title": f"Contact: {name}",
                "people": [name],
                "summary": contact.get("email", ""),
                "external_id": contact.get("id", "")
            })
        return records

    def extract_entities(self, normalized_records: list[dict], source_meta: dict) -> list[dict]:
        entities = super().extract_entities(normalized_records, source_meta)
        dedup = {(e["entity_type"], e["canonical_name"]): e for e in entities}

        for record in normalized_records:
            for person in record.get("people", []):
                canon = person.lower()
                if ("person", canon) not in dedup:
                    ent = {
                        "entity_type": "person",
                        "canonical_name": canon,
                        "display_name": person,
                        "importance_score": 0.8
                    }
                    dedup[("person", canon)] = ent
                    entities.append(ent)
        return list(dedup.values())
