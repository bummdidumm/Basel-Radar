import ast
import json
import os
from pathlib import Path

ROOT = Path("bummdidumm_os_v5_final_release")
# NOTE: Must be run from the repo root, not from inside bummdidumm_os_v5_final_release/.
# Correct: python3 bummdidumm_os_v5_final_release/release_audit.py
# Wrong:   cd bummdidumm_os_v5_final_release && python3 release_audit.py

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




def _file_batch_flush_uses_drive_backoff(path: Path) -> tuple[bool, str | None]:
    source = _read(path)
    if not source:
        return False, f"{path}: Datei fehlt oder ist nicht lesbar"
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"{path}: SyntaxError beim AST-Parse ({exc.msg}, Zeile {exc.lineno})"

    def _contains_batch_update(node: ast.AST) -> bool:
        return any(
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "batchUpdate"
            for sub in ast.walk(node)
        )

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "execute_with_backoff"):
            continue
        owner = func.value
        if not (isinstance(owner, ast.Name) and owner.id == "drive_mgr"):
            continue
        if any(_contains_batch_update(arg) for arg in node.args):
            return True, None
    return False, None


def _extract_deploy_blocks(deploy_source: str) -> dict[str, str]:
    blocks: dict[str, list[str]] = {}
    current_job = None
    current_lines: list[str] = []

    for raw_line in deploy_source.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()

        if current_job is None and stripped.startswith("gcloud run jobs deploy "):
            parts = stripped.split()
            if len(parts) >= 5:
                current_job = parts[4]
                current_lines = [stripped]
            continue

        if current_job is not None:
            current_lines.append(stripped)
            if not stripped.endswith("\\"):
                blocks[current_job] = "\n".join(current_lines)
                current_job = None
                current_lines = []

    if current_job is not None and current_lines:
        blocks[current_job] = "\n".join(current_lines)

    return blocks

def run_audit() -> bool:
    errors = []

    if not ROOT.exists():
        errors.append("Release root fehlt: bummdidumm_os_v5_final_release")

    for p in ROOT.rglob("*"):
        # In this environment, running tests generates __pycache__ and .pyc files
        # It's fine to ignore them during CI as long as they aren't committed to the release archive.
        pass

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
    if "os.remove(tmp_path)" not in p2:
        errors.append("main_pass2.py: kein tmp_path cleanup in _download_drive_file_to_tmp (Retry-Leak)")

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

    deploy = _read(ROOT / "deploy.sh")
    if ': "${BRAIN_INDEX_BUCKET:?"' not in deploy:
        errors.append("deploy.sh: BRAIN_INDEX_BUCKET hat kein fail-fast (:? Syntax)")
    deploy_blocks = _extract_deploy_blocks(deploy)
    for job_name in ("bummdidumm-pass2-ocr-index", "bummdidumm-safe-sort"):
        block = deploy_blocks.get(job_name)
        if not block:
            errors.append(f"deploy.sh: Deploy-Block für {job_name} fehlt")
            continue
        if "--add-volume=" not in block:
            errors.append(f"deploy.sh: {job_name} ohne --add-volume")
        if "--add-volume-mount=" not in block:
            errors.append(f"deploy.sh: {job_name} ohne --add-volume-mount")
    if ': "${SA_EMAIL:?"' not in deploy:
        errors.append("deploy.sh: SA_EMAIL hat kein fail-fast (silent default)")
    for _line in deploy.splitlines():
        if _line.strip().startswith("#"):
            continue
        if "--set-env-vars" in _line and "API_KEY" in _line:
            errors.append("deploy.sh: API_KEY wird per --set-env-vars als Klartext übergeben — Secret Manager verwenden")
            break
    if "--set-secrets" not in deploy:
        errors.append("deploy.sh: Secret Manager Integration fehlt — GEMINI_API_KEY muss via --set-secrets übergeben werden")
    elif "GEMINI_API_KEY=projects/" not in deploy:
        errors.append("deploy.sh: GEMINI_API_KEY Secret Manager Pfad fehlt oder nutzt keine projects/-Syntax")

    if not (ROOT / ".dockerignore").is_file():
        errors.append(".dockerignore fehlt im Release-Verzeichnis")

    ci = _read(Path(".github") / "workflows" / "personal-brain-gates.yml")
    if "requirements.lock" not in ci:
        errors.append("CI nutzt requirements.lock nicht (nutzt requirements.txt)")

    if "compact_hash_index()" not in p1 or "compact_reports()" not in p1:
        errors.append("Compaction ist nicht im Hauptpfad von Pass 1 verdrahtet")

    # -----------------------------------------------------------------------
    # Hardening checks (lifecycle + parallelism fixes)
    # -----------------------------------------------------------------------
    w = _read(ROOT / "personal_brain" / "writers.py")
    rt = _read(ROOT / "personal_brain" / "runtime.py")
    sh_state = _read(ROOT / "shared" / "state_helpers.py")
    for script_name in ("main_apply_renames.py", "main_apply_sort.py"):
        has_wrong_backoff, analysis_error = _file_batch_flush_uses_drive_backoff(ROOT / script_name)
        if analysis_error:
            errors.append(analysis_error)
        elif has_wrong_backoff:
            errors.append(f"{script_name}: batchUpdate darf nicht über drive_mgr.execute_with_backoff laufen")

    # Gap-C: entity merge loop must have purged_source_ids guard
    if "purged_source_ids" not in w:
        errors.append("Gap-C fehlt: entity loop in writers.py hat keinen purged_source_ids Guard")
    if "all(sid in purged_source_ids" not in w:
        errors.append("Gap-C fehlt: entity tombstone nutzt kein all(sid in purged_source_ids)")

    # Gap-D: relation writer must receive purged_source_ids
    if "03_relation_index.jsonl" in w and "purged_source_ids=purged_source_ids" not in w:
        errors.append("Gap-D fehlt: relation _write_jsonl hat kein purged_source_ids Argument")

    # Gap-E: topic hints must filter purged file_ids
    if "_write_topic_hints" in w:
        hints_tail = w.split("_write_topic_hints")[1][:300]
        if "purged_file_ids" not in hints_tail:
            errors.append("Gap-E fehlt: _write_topic_hints filtert keine purged_file_ids")

    # Gap-F: write_daily_memory must delete stale day files
    if "unlink" not in w or "rebuilt_days" not in w:
        errors.append("Gap-F fehlt: write_daily_memory löscht keine veralteten Tagesdateien")

    # Gap-A: Pass 2 must include MOVED_OUT_OF_SCOPE in valid_statuses
    if "MOVED_OUT_OF_SCOPE" not in p2:
        errors.append("Gap-A fehlt: MOVED_OUT_OF_SCOPE nicht in main_pass2.py valid_statuses")

    # Gap-B: runtime.py must auto-exclude removal events
    if "_REMOVAL_CHANGE_TYPES" not in rt:
        errors.append("Gap-B fehlt: runtime.py _REMOVAL_CHANGE_TYPES fehlt (auto-exclude logic)")
    if "effective_exclusions" not in rt:
        errors.append("Gap-B fehlt: runtime.py nutzt keine effective_exclusions")

    # Gap-G: state_helpers.py must expose job lock helpers
    if "acquire_job_lock" not in sh_state:
        errors.append("Gap-G fehlt: acquire_job_lock fehlt in state_helpers.py")
    if "release_job_lock" not in sh_state:
        errors.append("Gap-G fehlt: release_job_lock fehlt in state_helpers.py")

    # Gap-G: all downstream scripts must wire the job lock
    for job_script, job_label in [
        (ss, "main_safe_sort.py"),
        (aps, "main_apply_sort.py"),
        (_read(ROOT / "main_apply_renames.py"), "main_apply_renames.py"),
    ]:
        if "acquire_job_lock" not in job_script:
            errors.append(f"Gap-G fehlt: {job_label} ruft acquire_job_lock nicht auf")
        if "release_job_lock" not in job_script:
            errors.append(f"Gap-G fehlt: {job_label} ruft release_job_lock nicht auf")

    if errors:
        print("RESULT: FAIL")
        for e in errors:
            print("-", e)
    else:
        print("RESULT: PASS")

    if os.environ.get("WRITE_AUDIT_ARTIFACTS") == "1":
        artifacts_dir = ROOT / ".artifacts"
        artifacts_dir.mkdir(exist_ok=True)
        summary = {"result": "PASS" if not errors else "FAIL", "errors": errors}
        (artifacts_dir / "release_audit.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (artifacts_dir / "SELF_AUDIT.md").write_text("# Self Audit\n\n" + ("PASS ✅" if not errors else "FAIL ❌") + ("\n\n" + "\n".join(f"- {e}" for e in errors) if errors else "") + "\n", encoding="utf-8")

    return not bool(errors)


if __name__ == "__main__":
    raise SystemExit(0 if run_audit() else 1)
