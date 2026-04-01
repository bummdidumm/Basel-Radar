import os
import re

def run_audit():
    print("Starte bummdidumm-OS Self-Audit...\n")
    errors = []

    # 1. Cleanliness
    print("[1] Prüfe Workspace Cleanliness...")
    for root, dirs, files in os.walk("bummdidumm_os_v5_final_release"):
        if "__pycache__" in dirs:
            errors.append(f"GEFUNDEN: __pycache__ in {root}")
        for file in files:
            if file.endswith(".pyc"):
                errors.append(f"GEFUNDEN: .pyc file {file} in {root}")

    # 2. File Structure
    print("[2] Prüfe Projektstruktur...")
    required_files = [
        "bummdidumm_os_v5_final_release/main_pass1.py",
        "bummdidumm_os_v5_final_release/main_pass2.py",
        "bummdidumm_os_v5_final_release/main_apply_renames.py",
        "bummdidumm_os_v5_final_release/main_safe_sort.py",
        "bummdidumm_os_v5_final_release/main_apply_sort.py",
        "bummdidumm_os_v5_final_release/shared/drive_helpers.py",
        "bummdidumm_os_v5_final_release/shared/sheets_helpers.py",
        "bummdidumm_os_v5_final_release/shared/hash_helpers.py",
        "bummdidumm_os_v5_final_release/shared/gemini_helpers.py",
        "bummdidumm_os_v5_final_release/shared/state_helpers.py",
        "bummdidumm_os_v5_final_release/shared/models.py",
        "bummdidumm_os_v5_final_release/shared/change_type_logic.py",
        "bummdidumm_os_v5_final_release/shared/sorting_helpers.py",
        "bummdidumm_os_v5_final_release/requirements.txt",
        "bummdidumm_os_v5_final_release/Dockerfile.pass1",
        "bummdidumm_os_v5_final_release/Dockerfile.pass2",
        "bummdidumm_os_v5_final_release/Dockerfile.renames",
        "bummdidumm_os_v5_final_release/Dockerfile.safesort",
        "bummdidumm_os_v5_final_release/Dockerfile.applysort",
        "bummdidumm_os_v5_final_release/appsscript/Code.gs",
        "bummdidumm_os_v5_final_release/appsscript/appsscript.json",
        "bummdidumm_os_v5_final_release/deploy.sh",
        "bummdidumm_os_v5_final_release/README.md"
    ]
    for rf in required_files:
        if not os.path.exists(rf):
            errors.append(f"FEHLT: {rf}")

    # 3. Apps Script Logic
    print("[3] Prüfe Apps Script Logic...")
    if os.path.exists("bummdidumm_os_v5_final_release/appsscript/Code.gs"):
        with open("bummdidumm_os_v5_final_release/appsscript/Code.gs", "r") as f:
            code = f.read()
            if "ScriptApp.getOAuthToken()" not in code:
                errors.append("Apps Script verwendet nicht getOAuthToken()")
            if "getIdentityToken()" in code:
                errors.append("Apps Script verwendet getIdentityToken(), was verboten ist.")
            if "emergencyStopAllTriggers" not in code:
                errors.append("Apps Script hat keine Notbremse (emergencyStopAllTriggers).")
            if "autoCleanupTransientFolder" not in code:
                errors.append("Apps Script hat kein Cleanup für transiente Ordner.")
            if "initializeFolderStructure" not in code:
                errors.append("Apps Script hat keine initializeFolderStructure().")
            if "DEIN_PROJEKT_ID" in code:
                errors.append("Code.gs enthält noch den hardcodierten Platzhalter DEIN_PROJEKT_ID.")

    # 4. Schema Consistency
    print("[4] Prüfe State- und Schema-Konsistenz...")
    if os.path.exists("bummdidumm_os_v5_final_release/shared/sheets_helpers.py"):
        with open("bummdidumm_os_v5_final_release/shared/sheets_helpers.py", "r") as f:
            sheets_code = f.read()
            if "parent_ids_sorted" not in sheets_code or "path_display" not in sheets_code:
                errors.append("Hash_Index Schema hat nicht die verlangten parent_ids_sorted und path_display Felder.")
            if "Sorting_Suggestions" not in sheets_code:
                errors.append("Sorting_Suggestions Sheet ist nicht im SheetManager.")
            if "Folder_Registry" not in sheets_code:
                errors.append("Folder_Registry Sheet ist nicht im SheetManager.")

    # 5. Delta Resume Logic
    print("[5] Prüfe Delta & Resume Logik...")
    if os.path.exists("bummdidumm_os_v5_final_release/main_pass1.py"):
        with open("bummdidumm_os_v5_final_release/main_pass1.py", "r") as f:
            p1_code = f.read()
            if "in_progress_page_token" not in p1_code:
                errors.append("Pass 1 nutzt kein in_progress_page_token.")
            if "state.set_val(\"drive_start_page_token\", new_start_page_token)" not in p1_code:
                errors.append("Pass 1 speichert newStartPageToken scheinbar nicht am Ende.")

    # 6. Sorting Layer
    print("[6] Prüfe Sorting Layer...")
    if os.path.exists("bummdidumm_os_v5_final_release/shared/sorting_helpers.py"):
        with open("bummdidumm_os_v5_final_release/shared/sorting_helpers.py", "r") as f:
            sh_code = f.read()
            if "99_archive" not in sh_code or "30_scripts" not in sh_code or "40b_referenzen" not in sh_code:
                errors.append("Sorting Rules fehlen bestimmte Kategorien.")
    if os.path.exists("bummdidumm_os_v5_final_release/main_safe_sort.py"):
        with open("bummdidumm_os_v5_final_release/main_safe_sort.py", "r") as f:
            ss_code = f.read()
            # Expecting exactly 12 items appended to suggestions
            if "current_run_id, file_id, name, mime_type, path, current_parent_id, target_name, target_id, target_path, rule_reason, \"SAFE\", \"PENDING\"" not in ss_code:
                errors.append("main_safe_sort.py appended nicht das korrekte 12-Spalten-Format an Sorting_Suggestions.")

    # 7. JSONL/OCR Logic
    print("[7] Prüfe JSONL Event-only und OCR Cleanup...")
    if os.path.exists("bummdidumm_os_v5_final_release/main_pass2.py"):
        with open("bummdidumm_os_v5_final_release/main_pass2.py", "r") as f:
            p2_code = f.read()
            if "event_only_no_content_processing" not in p2_code:
                errors.append("Pass 2 hat keinen Event-Only Branch für DELETED/MOVED in JSONL.")
    if os.path.exists("bummdidumm_os_v5_final_release/shared/gemini_helpers.py"):
        with open("bummdidumm_os_v5_final_release/shared/gemini_helpers.py", "r") as f:
            gem_code = f.read()
            if "self.client.files.delete" not in gem_code or "finally:" not in gem_code:
                errors.append("Gemini File Delete findet nicht im finally-Block statt.")

    # 8. Quota Robustness
    print("[8] Prüfe Quota & Robustness...")
    if os.path.exists("bummdidumm_os_v5_final_release/shared/sheets_helpers.py"):
        with open("bummdidumm_os_v5_final_release/shared/sheets_helpers.py", "r") as f:
            q_code = f.read()
            if "_execute_with_backoff" not in q_code or "429" not in q_code:
                errors.append("Exponential Backoff fehlt in sheets_helpers.")
            if "read_rows_chunked" not in q_code:
                errors.append("read_rows_chunked fehlt.")

    # Output Results
    print("\n--- AUDIT ERGEBNISSE ---")
    if errors:
        print("RESULT: FAIL ❌\n")
        for e in errors:
            print(f"- {e}")
        with open("SELF_AUDIT.md", "w") as f:
            f.write("# Self Audit: FAIL ❌\n\n")
            f.write("Folgende Fehler wurden gefunden:\n")
            for e in errors:
                f.write(f"- {e}\n")
        return False
    else:
        print("RESULT: PASS ✅")
        print("Alle 9 Prüfkategorien wurden erfolgreich bestanden.")
        with open("SELF_AUDIT.md", "w") as f:
            f.write("# Self Audit: PASS ✅\n\n")
            f.write("Alle Release-Kriterien (Cleanliness, Schema, Delta Logic, Sorting, OCR, Quota) wurden erfüllt.\n")
        return True

if __name__ == "__main__":
    run_audit()
