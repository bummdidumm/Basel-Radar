class TierClassifier:
    def classify_entity(self, entity_type: str, display_name: str = "") -> dict:
        """Returns {"knowledge_tier": ..., "staleness_days": ...}"""
        mapping = {
            "person": {"knowledge_tier": "slow_changing", "staleness_days": 365},
            "device": {"knowledge_tier": "slow_changing", "staleness_days": None},
            "subscription": {"knowledge_tier": "slow_changing", "staleness_days": 30},
            "place": {"knowledge_tier": "ephemeral", "staleness_days": 90},
            "app": {"knowledge_tier": "slow_changing", "staleness_days": 180},
            "topic": {"knowledge_tier": "ephemeral", "staleness_days": 60}
        }

        # Specific overrides based on the rules
        if entity_type == "place" and display_name.lower() in ["home", "work"]:
            return {"knowledge_tier": "permanent", "staleness_days": None}

        return mapping.get(entity_type, {"knowledge_tier": "ephemeral", "staleness_days": 90})

    def classify_record(self, record_type: str) -> dict:
        """Returns {"knowledge_tier": ..., "staleness_days": ...}"""
        mapping = {
            "event": {"knowledge_tier": "ephemeral", "staleness_days": 30},
            "message": {"knowledge_tier": "ephemeral", "staleness_days": 14},
            "purchase": {"knowledge_tier": "slow_changing", "staleness_days": 365}
        }
        return mapping.get(record_type, {"knowledge_tier": "ephemeral", "staleness_days": 90})
