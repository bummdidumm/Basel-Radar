import json
from pathlib import Path

class LlmContextPackWriter:
    def write(self, published_root: Path, exclusion_mgr=None):
        pack_dir = published_root / "13_llm_context_packs"
        pack_dir.mkdir(parents=True, exist_ok=True)

        pack = {
            "generated_at": "ISO8601",
            "schema_version": "1.0",
            "owner": self._load_profile(published_root / "10_profile" / "me.json"),
            "family": self._load_profile(published_root / "10_profile" / "family.json").get("members", []),
            "devices": self._load_profile(published_root / "10_profile" / "devices.json").get("devices", []),
            "active_subscriptions": self._load_profile(published_root / "11_inventory" / "subscriptions.json").get("subscriptions", []),
            "recent_7_days": {
                "summary": "",
                "key_events": [],
                "people_met": [],
                "places_visited": [],
                "purchases": []
            },
            "frequent_topics_30d": [],
            "important_upcoming": [],
            "stale_knowledge_warning": ""
        }

        dm_dir = published_root / "04_daily_memory"
        if dm_dir.exists():
            dm_files = sorted(list(dm_dir.glob("*.jsonl")))[-7:]
            for df in dm_files:
                for line in df.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        rec = json.loads(line)
                        if exclusion_mgr and exclusion_mgr.is_excluded(record_id=rec.get("record_id"), source_id=rec.get("source_id")):
                            continue
                        pack["recent_7_days"]["key_events"].append(rec.get("title", ""))

        pack_str = json.dumps(pack, indent=2)
        if len(pack_str.encode('utf-8')) > 50000:
            pack["recent_7_days"]["key_events"] = pack["recent_7_days"]["key_events"][:10]

        with open(pack_dir / "gemini_daily_context.json", "w") as f:
            json.dump(pack, f, indent=2)

    def _load_profile(self, path: Path) -> dict:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}
