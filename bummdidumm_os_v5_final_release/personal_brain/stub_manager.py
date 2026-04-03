import json
from pathlib import Path

class StubManager:
    def ensure_stubs(self, published_root: Path, settings_root: Path):
        (published_root / "10_profile").mkdir(parents=True, exist_ok=True)
        (published_root / "11_inventory").mkdir(parents=True, exist_ok=True)
        settings_root.mkdir(parents=True, exist_ok=True)

        stubs = {
            published_root / "10_profile/me.json": {"schema_version": "1.0", "knowledge_tier": "permanent", "last_manually_updated": "YYYY-MM-DD", "identity": {"full_name": "", "preferred_name": "", "date_of_birth": "", "nationality": "", "languages": [], "timezone": "", "city": "", "country": ""}, "contact": {"primary_email": "", "secondary_emails": [], "phone": ""}},
            published_root / "10_profile/family.json": {"schema_version": "1.0", "knowledge_tier": "permanent", "members": []},
            published_root / "10_profile/devices.json": {"schema_version": "1.0", "knowledge_tier": "slow_changing", "devices": []},
            published_root / "10_profile/accounts.json": {"schema_version": "1.0", "knowledge_tier": "slow_changing", "accounts": []},
            published_root / "11_inventory/subscriptions.json": {"schema_version": "1.0", "knowledge_tier": "slow_changing", "subscriptions": []},
            published_root / "11_inventory/apps.json": {"schema_version": "1.0", "knowledge_tier": "slow_changing", "apps": []},
            published_root / "11_inventory/places.json": {"schema_version": "1.0", "knowledge_tier": "slow_changing", "places": []},
            settings_root / "exclusions.json": {"schema_version": "1.0", "excluded_entity_ids": [], "excluded_record_ids": [], "excluded_source_ids": [], "excluded_topics": []},
            settings_root / "entity_aliases.json": {"schema_version": "1.0", "alias_groups": []}
        }

        for path, default_content in stubs.items():
            if not path.exists():
                with open(path, "w") as f:
                    json.dump(default_content, f, indent=2)
