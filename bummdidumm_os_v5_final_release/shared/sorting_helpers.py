from typing import Dict, Tuple

class SortingRules:
    """Sortierregeln + Registry-Navigation für folder-aware Zielermittlung."""

    def __init__(self, folder_registry: Dict[str, Dict[str, str]]):
        self.folder_registry = folder_registry
        self.inbox_trash_folder_id = (
            folder_registry.get("01_inbox_trash", {}).get("folder_id", "")
        )

    def resolve_target(self, folder_key: str) -> Tuple[str, str, str]:
        entry = self.folder_registry.get(folder_key, {})
        return (
            entry.get("folder_name", folder_key),
            entry.get("folder_id", ""),
            entry.get("full_path", f"/{folder_key}")
        )

    def determine_target(self, file_meta: dict) -> Tuple[str, str, str, str, str]:
        """Returns (folder_rule, folder_rule_reason, target_name, target_id, target_path)."""
        name = file_meta.get("name", "").lower()
        mime = file_meta.get("mime_type", "").lower()
        status = file_meta.get("status", "")
        path = file_meta.get("path", "").lower()
        lane = file_meta.get("lane", "")
        current_parent_id = file_meta.get("current_parent_id", "")
        semantic_topic_hint = file_meta.get("semantic_topic_hint", "").lower()

        _FINANCIAL_HINTS = frozenset({
            "invoice", "rechnung", "receipt", "quittung", "beleg",
            "contract", "vertrag", "bank_statement", "kontoauszug",
            "mahnung", "lieferschein", "delivery_note"
        })

        if lane == "INBOX_TRASH" or (self.inbox_trash_folder_id and current_parent_id == self.inbox_trash_folder_id):
            key = "01_inbox_trash"
            reason = "Prio 0: Inbox Trash Lane"
        elif "DUPLICATE" in status:
            key = "99_archive"
            reason = "Prio 1: Duplikat"
        elif status in ["ERROR", "FATAL", "UNREADABLE"]:
            key = "99_quarantine"
            reason = "Prio 1: Fehlerfall/Quarantäne"
        elif semantic_topic_hint in _FINANCIAL_HINTS:
            key = "40b_referenzen"
            reason = "Prio 1.5: Semantic Topic Hint (OCR)"
        elif mime.startswith("image/"):
            key = "50a_fotos"
            reason = "Prio 2: Bilddatei (Mime-Type)"
        elif mime.startswith("video/"):
            key = "50b_videos"
            reason = "Prio 2: Videodatei (Mime-Type)"
        elif mime.startswith("audio/"):
            key = "50c_audio"
            reason = "Prio 2: Audiodatei (Mime-Type)"
        elif name.endswith((".py", ".js", ".ts", ".gs", ".ipynb", ".sh", ".yaml", ".yml", ".json", ".sql")):
            key = "30_scripts"
            reason = "Prio 3: Code/Skript (Dateiendung)"
        elif name.endswith(".md") and ("script" in path or "code" in path or "project" in path):
            key = "30_scripts"
            reason = "Prio 3: Markdown im Code-Kontext"
        elif mime == "application/pdf":
            key = "40b_referenzen"
            reason = "Prio 4: PDF Dokument"
        elif any(marker in name or marker in path for marker in ["projektai", "bummdidumm", "driveview", "sky", "matrix", "ai_os"]):
            key = "40c_projekte"
            reason = "Prio 5: Projektmarker im Namen/Pfad"
        elif any(marker in name for marker in ["decision", "entscheid", "adr", "architecture_decision"]):
            key = "10_decisions"
            reason = "Prio 6: Entscheidungs-Kontext im Namen"
        elif name.endswith((".apk", ".exe", ".dmg", ".pkg", ".deb", ".rpm", ".zip", ".tar", ".7z")):
            key = "60_software"
            reason = "Prio 7: Software/Binärpaket (Dateiendung)"
        else:
            key = "00_inbox"
            reason = "Prio 8: Unsicher/Keine Regel greift"

        target_name, target_id, target_path = self.resolve_target(key)
        return key, reason, target_name, target_id, target_path
