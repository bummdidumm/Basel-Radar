import json
from pathlib import Path

class ExclusionManager:
    def __init__(self, exclusions_path: Path):
        """Loads exclusions.json. Safe if file does not exist."""
        self.excluded_entity_ids = set()
        self.excluded_record_ids = set()
        self.excluded_source_ids = set()
        self.excluded_topics = set()

        if exclusions_path.exists():
            try:
                data = json.loads(exclusions_path.read_text(encoding="utf-8"))
                self.excluded_entity_ids = set(data.get("excluded_entity_ids", []))
                self.excluded_record_ids = set(data.get("excluded_record_ids", []))
                self.excluded_source_ids = set(data.get("excluded_source_ids", []))
                self.excluded_topics = set(data.get("excluded_topics", []))
            except json.JSONDecodeError:
                pass

    def is_excluded(self, entity_id: str = None, record_id: str = None,
                    source_id: str = None, topics: list[str] = None) -> bool:
        """Returns True if any provided ID or topic is in exclusion lists."""
        if entity_id and entity_id in self.excluded_entity_ids:
            return True
        if record_id and record_id in self.excluded_record_ids:
            return True
        if source_id and source_id in self.excluded_source_ids:
            return True
        if topics:
            for t in topics:
                if t in self.excluded_topics:
                    return True
        return False
