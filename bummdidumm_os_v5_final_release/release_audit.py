import json
from pathlib import Path

ROOT = Path("bummdidumm_os_v5_final_release")

_PLACEHOLDER_TOKENS = [
    "DEIN_PROJEKT_ID",
    "DEINE_SHEET_ID",
    "DEIN_API_KEY",
    "DEIN_TARGET_FOLDER_ID",
]

_AUDIT_OUTPUT_FILES = {"release_audit.py", "SELF_AUDIT.md", "release_audit.json"}


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def run_audit() -> bool:
    errors = []

    if not ROOT.exists():
        errors.append("Release root fehlt: bummdidumm_os_v5_final_release")

    for p in ROOT.rglob("*"):
        if "__pycache__" in p.parts:
            errors.append(f"__pycache__ gefunden: {p}")
        if p.suffix == ".pyc":
            errors.append(f".pyc gefunden: {p}")

        if not p.is_file() or p.name in _AUDIT_OUTPUT_FILES:
            continue

        text = _read(p)
        for bad in _PLACEHOLDER_TOKENS:
            if bad in text:
                errors.append(f"Platzhalter {bad} gefunden in {p}")

    code = _read(ROOT / "appsscript" / "Code.gs")
    required_ops = [
        "Fast Delta-Scan starten", "OCR & Indexing starten", "Renames anwenden",
        "Kompletten Lauf starten", "Ordnerstruktur initialisieren",
        "Sortier-Vorschläge erzeugen", "Sortierung anwenden",
        "Error Reports leeren", "NOTBREMSE"
    ]
    for op in required_ops:
        if op not in code:
            errors.append(f"Apps Script Menüeintrag fehlt: {op}")
    for must in ["emergencyStopAllTriggers", "deleteMyTriggers", "POLL_ATTEMPTS", "initializeFolderStructure", "Folder_Registry"]:
        if must not in code:
            errors.append(f"Apps Script Feature fehlt: {must}")

    p1 = _read(ROOT / "main_pass1.py")
    if "HASH_SKIPPED_SIZE" not in p1 or "known_file_details[rec.file_id]" not in p1:
        errors.append("SKIPPED_SIZE Cache Fix fehlt in main_pass1.py")

    p2 = _read(ROOT / "main_pass2.py")
    if "read_rows_chunked" not in p2:
        errors.append("Chunking fehlt in main_pass2.py")
    for status in ["DELETED", "TRASHED", "REMOVED_OR_NO_ACCESS", "MOVED", "RENAMED", "UNCHANGED_CONTENT_METADATA_ONLY"]:
        if status not in p2:
            errors.append(f"Pass2 Event-Status fehlt: {status}")
    for fld in ["current_parent_id", "current_path", "target_parent_id", "target_path", "folder_rule", "folder_rule_reason", "sort_mode", "move_result"]:
        if fld not in p2:
            errors.append(f"Folder-aware Feld fehlt in main_pass2.py: {fld}")

    ss = _read(ROOT / "main_safe_sort.py")
    aps = _read(ROOT / "main_apply_sort.py")
    sh = _read(ROOT / "shared" / "sorting_helpers.py")
    for must in ["folder_rule", "folder_rule_reason", "Folder_Registry", "A:E"]:
        if must not in ss:
            errors.append(f"Safe sort Härtung fehlt: {must}")
    if "read_rows_chunked_with_row_numbers" not in aps or "rows.index(" in aps:
        errors.append("Apply sort nutzt keine robuste Row-Index-Logik")
    if "parent_folder_id" not in sh and "full_path" not in sh:
        errors.append("Sorting Helpers nutzen Registry-Schema nicht vollständig")

    gh = _read(ROOT / "shared" / "gemini_helpers.py")
    for must in ["_is_retryable", "ResourceExhausted", "quota", "self.client.files.delete", "finally"]:
        if must.lower() not in gh.lower():
            errors.append(f"Gemini Robustness fehlt: {must}")

    summary = {"result": "PASS" if not errors else "FAIL", "errors": errors}
    (ROOT / "release_audit.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "SELF_AUDIT.md").write_text("# Self Audit\n\n" + ("PASS ✅" if not errors else "FAIL ❌") + "\n" + "\n".join(f"- {e}" for e in errors), encoding="utf-8")

    if errors:
        print("RESULT: FAIL")
        for e in errors:
            print("-", e)
        return False
    print("RESULT: PASS")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if run_audit() else 1)
