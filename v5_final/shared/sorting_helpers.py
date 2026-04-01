import os
from typing import Dict, Tuple

class SortingRules:
    """
    Kapselt die Sortierregeln (Prioritäten 1-8) für das automatische File-Routing
    in die Bummdidumm-Ordnerstruktur.
    """

    def __init__(self, folder_ids: Dict[str, str]):
        """Erwartet ein Dictionary der Form {'00_inbox': 'id123', '99_archive': 'id456', ...}"""
        self.folder_ids = folder_ids

    def determine_target(self, file_meta: dict) -> Tuple[str, str, str]:
        """
        Gibt (target_folder_name, target_folder_id, rule_reason) zurück.
        file_meta muss enthalten: name, mime_type, status, duplicate_of, path
        """
        name = file_meta.get("name", "").lower()
        mime = file_meta.get("mime_type", "").lower()
        status = file_meta.get("status", "")
        path = file_meta.get("path", "").lower()

        # Prio 1: Sonderfälle (Archive & Quarantine)
        if "DUPLICATE" in status:
            return "99_archive", self.folder_ids.get("99_archive", ""), "Prio 1: Duplikat"

        if status in ["ERROR", "FATAL", "UNREADABLE"]:
            return "99_quarantine", self.folder_ids.get("99_quarantine", ""), "Prio 1: Fehlerfall/Quarantäne"

        # Prio 2: Medien
        if mime.startswith("image/"):
            return "50a_fotos", self.folder_ids.get("50a_fotos", ""), "Prio 2: Bilddatei (Mime-Type)"
        if mime.startswith("video/"):
            return "50b_videos", self.folder_ids.get("50b_videos", ""), "Prio 2: Videodatei (Mime-Type)"
        if mime.startswith("audio/"):
            return "50c_audio", self.folder_ids.get("50c_audio", ""), "Prio 2: Audiodatei (Mime-Type)"

        # Prio 3: Code / Skripte
        code_exts = [".py", ".js", ".ts", ".gs", ".ipynb", ".sh", ".yaml", ".yml", ".json", ".sql"]
        if any(name.endswith(ext) for ext in code_exts):
            return "30_scripts", self.folder_ids.get("30_scripts", ""), f"Prio 3: Code/Skript (Dateiendung)"

        if name.endswith(".md") and ("script" in path or "code" in path or "project" in path):
             return "30_scripts", self.folder_ids.get("30_scripts", ""), "Prio 3: Markdown im Code-Kontext"

        # Prio 4: Dokumente / Referenzen (Standard)
        if mime == "application/pdf":
            return "40b_referenzen", self.folder_ids.get("40b_referenzen", ""), "Prio 4: PDF Dokument"

        # Prio 5: Projektdateien
        project_markers = ["projektai", "bummdidumm", "driveview", "sky", "matrix", "ai_os"]
        if any(marker in name or marker in path for marker in project_markers):
            return "40c_projekte", self.folder_ids.get("40c_projekte", ""), "Prio 5: Projektmarker im Namen/Pfad"

        # Prio 6: Entscheidungen
        decision_markers = ["decision", "entscheid", "adr", "architecture_decision"]
        if any(marker in name for marker in decision_markers):
            return "10_decisions", self.folder_ids.get("10_decisions", ""), "Prio 6: Entscheidungs-Kontext im Namen"

        # Prio 7: Software / Binärartefakte
        sw_exts = [".apk", ".exe", ".dmg", ".pkg", ".deb", ".rpm", ".zip", ".tar", ".7z"]
        if any(name.endswith(ext) for ext in sw_exts):
            return "60_software", self.folder_ids.get("60_software", ""), "Prio 7: Software/Binärpaket (Dateiendung)"

        # Prio 8: Nicht eindeutig zuordenbar
        return "00_inbox", self.folder_ids.get("00_inbox", ""), "Prio 8: Unsicher/Keine Regel greift"
