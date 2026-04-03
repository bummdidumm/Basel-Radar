import json
from pathlib import Path

class EntityMerger:
    def __init__(self, alias_map_path: Path):
        """Loads entity_aliases.json. Safe if file does not exist."""
        self.alias_groups = []
        if alias_map_path.exists():
            try:
                data = json.loads(alias_map_path.read_text(encoding="utf-8"))
                self.alias_groups = data.get("alias_groups", [])
            except json.JSONDecodeError:
                pass

    def resolve_canonical(self, name: str, entity_type: str) -> str | None:
        """Returns canonical name if this name is a known alias, else None."""
        for group in self.alias_groups:
            if group.get("entity_type") == entity_type:
                if name == group.get("canonical_name") or name in group.get("aliases", []):
                    return group.get("canonical_name")
        return None

    def apply_merge(self, entity_index: list[dict]) -> list[dict]:
        """
        - Finds entity rows that are aliases of each other per alias_groups
        - Sets merge_status = "alias_of" and canonical_entity_id on duplicates
        - Aggregates source_ids and record counts onto the canonical entity row
        - Does NOT delete rows: alias rows remain with merge_status = "alias_of"
        - Returns the full updated list
        """
        canonical_map = {}
        for entity in entity_index:
            canon_name = self.resolve_canonical(entity["display_name"], entity["entity_type"])
            if canon_name and canon_name == entity["display_name"]:
                canonical_map[(canon_name, entity["entity_type"])] = entity

        for entity in entity_index:
            canon_name = self.resolve_canonical(entity["display_name"], entity["entity_type"])
            if canon_name and canon_name != entity["display_name"]:
                canon_entity = canonical_map.get((canon_name, entity["entity_type"]))
                if canon_entity:
                    entity["merge_status"] = "alias_of"
                    entity["canonical_entity_id"] = canon_entity["entity_id"]
                    canon_sources = set(canon_entity.get("source_ids", []))
                    canon_sources.update(entity.get("source_ids", []))
                    canon_entity["source_ids"] = list(canon_sources)
                    canon_entity["record_count"] = canon_entity.get("record_count", 0) + entity.get("record_count", 0)

        return entity_index
