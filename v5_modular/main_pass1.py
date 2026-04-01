import os
from typing import List, Dict
import google.auth
from googleapiclient.discovery import build
from datetime import datetime, timezone

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker
from shared.drive_helpers import DriveManager
from shared.hash_helpers import calculate_sha256_streaming
from shared.models import FileRecord

TARGET_FOLDER_ID = os.environ.get("TARGET_FOLDER_ID")
ARCHIVE_FOLDER_ID = os.environ.get("ARCHIVE_FOLDER_ID")
CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
PROJECT_SLUG = os.environ.get("PROJECT_SLUG", "bummdidumm")

SKIP_OVER_MB = int(os.environ.get("SKIP_OVER_MB", "500"))
ENABLE_ARCHIVE = os.environ.get("ENABLE_ARCHIVE", "true").lower() == "true"
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"

def determine_change_type(f: dict, known_file_details: dict, is_initial: bool) -> str:
    """Implementiert echte Statusfelder: NEW, UPDATED, RENAMED, MOVED, TRASHED, DELETED"""
    if is_initial: return "NEW"

    file_id = f.get("id")
    removed = f.get("removed", False)
    trashed = f.get("trashed", False)

    if removed:
        return "REMOVED_OR_NO_ACCESS"

    if trashed:
        return "TRASHED"

    if file_id not in known_file_details:
        return "NEW"

    # File is known, evaluate what changed
    cached = known_file_details[file_id]

    # Check parent folder movement
    current_parents = f.get("parents", [])
    # Wir nehmen hier stark vereinfacht das erste Parent als "Move" Indikator.
    # Für exaktes Path-Tracking bräuchte man den kompletten Pfad in der Hash_Index Tabelle.
    cached_path = cached.get("path", "")
    if cached_path and current_parents and current_parents[0] not in cached_path:
        return "MOVED"

    # Check Name change
    cached_name = cached.get("name")
    if cached_name and cached_name != f.get("name"):
        return "RENAMED"

    # If not moved or renamed, it must be content updated (since it showed up in delta)
    return "UPDATED"

def check_md5_size_prefilter(f: dict, known_file_details: dict) -> bool:
    """True = Die Datei wurde mit Sicherheit nicht geändert (Größe + MD5 stimmen exakt überein)."""
    file_id = f.get("id")
    if file_id not in known_file_details:
        return False # Datei unbekannt

    mime_type = f.get("mimeType", "")
    # Google Native Formate haben keine md5Checksum in Drive.
    if mime_type.startswith("application/vnd.google-apps"):
        return False

    current_md5 = f.get("md5Checksum")
    current_size = str(f.get("size", "0"))

    cached = known_file_details[file_id]
    cached_md5 = cached.get("md5")
    cached_size = str(cached.get("size_bytes", "0"))

    # Wenn md5 existiert und übereinstimmt, und die Größe exakt passt:
    if current_md5 and cached_md5 and current_md5 == cached_md5 and current_size == cached_size:
        return True

    return False

def suggest_rename(name: str, created_time: str) -> str:
    if not created_time: return name
    iso_date = created_time[:10]
    if name.startswith(f"{iso_date}_"): return name
    safe = name.replace(":", "-").strip()
    return f"{iso_date}_{PROJECT_SLUG}_{safe}"

def run_pass1():
    print("Starte Pass 1: Delta + Dedupe + Archivierung")
    if not all([TARGET_FOLDER_ID, CONTROL_SHEET_ID]):
        raise ValueError("Missing TARGET_FOLDER_ID or CONTROL_SHEET_ID")

    credentials, _ = google.auth.default()
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)
    drive_mgr = DriveManager(drive_service, TARGET_FOLDER_ID, ENABLE_SHARED_DRIVES)

    start_token = state.get_val("drive_start_page_token")
    in_progress_token = state.get_val("in_progress_page_token")

    # Baue erweiterten File-Cache für echtes Change-Type Tracking und Prefilter
    known_file_details = {}
    rows = sheet_mgr.read_all_rows("Hash_Index", "A:H") # sha, fid, name, path, updated_at, size_bytes, md5, eff_mime
    for r in rows:
        if len(r) >= 7 and r[0] != "sha256":
            known_file_details[r[1]] = {
                "sha": r[0],
                "name": r[2],
                "path": r[3],
                "size_bytes": r[5],
                "md5": r[6]
            }

    known_hashes = state.load_known_hashes()

    processed = 0
    errors = 0
    all_records = []

    try:
        if not start_token:
            print("Initialer Run: Führe kompletten Walk über TARGET_FOLDER durch.")
            state.set_val("current_phase", "INITIAL_SCAN")

            # 1. Fetch all items (Recursive Walk)
            all_items = drive_mgr.walk_recursive(TARGET_FOLDER_ID)
            files = [f for f in all_items if f.get("mimeType") != "application/vnd.google-apps.folder"]

            # 2. Get initial token to mark point in time for future deltas
            new_start_page_token = drive_mgr.get_initial_token()

            # 3. Process batch
            _process_file_batch(drive_service, drive_mgr, state, files, known_file_details, known_hashes, True, all_records)

            processed = len(files)

            # End Initial Run
            state.set_val("drive_start_page_token", new_start_page_token)

        else:
            active_token = in_progress_token if in_progress_token else start_token
            if active_token != in_progress_token:
                state.set_val("in_progress_page_token", active_token)
                state.set_val("current_phase", "DELTA_FETCH")

            new_start_page_token = None

            while active_token:
                print(f"Hole Delta Chunk: {active_token}")
                changes, next_token, new_start = drive_mgr.fetch_delta_chunk(active_token)

                files = [f for f in changes if f.get("mimeType") != "application/vnd.google-apps.folder"]

                _process_file_batch(drive_service, drive_mgr, state, files, known_file_details, known_hashes, False, all_records)

                processed += len(files)

                if next_token:
                    active_token = next_token
                    state.set_val("in_progress_page_token", active_token)
                else:
                    new_start_page_token = new_start
                    break

            # Erfolgreicher Abschluss des Deltas
            if new_start_page_token:
                state.set_val("drive_start_page_token", new_start_page_token)
                state.set_val("in_progress_page_token", "")

        state.set_val("current_phase", "PASS1_DONE")
        state.set_val("last_successful_run_id", state.run_id)
        state.set_val("last_run_utc", datetime.now(timezone.utc).isoformat())
        state.log_run("PASS_1", "SUCCESS", processed, errors)

    except Exception as e:
        state.set_val("current_phase", "PASS1_FAILED")
        state.log_error("PASS_1", "SYSTEM", "", "Fatal", str(e))
        state.log_run("PASS_1", "FAILED", processed, errors + 1)
        raise e

def _process_file_batch(drive_service, drive_mgr: DriveManager, state: StateTracker, files: List[Dict], known_file_details: Dict, known_hashes: Dict, is_initial: bool, all_records: List):

    records_to_process = []

    for f in files:
        file_id = f.get("id", "")
        mime = f.get("mimeType", "")
        size = int(f.get("size", 0))
        name = f.get("name", "UNKNOWN_REMOVED")

        change_type = determine_change_type(f, known_file_details, is_initial)
        suggested_name = suggest_rename(name, f.get("createdTime", ""))

        rec = FileRecord(
            file_id=file_id,
            name=name,
            path="UNKNOWN_PATH_DUE_TO_DELTA", # Simplification. Real implementation walks parents to root.
            mime_type=mime,
            size_bytes=size,
            md5=f.get("md5Checksum", ""),
            updated_at=f.get("modifiedTime", ""),
            created_time=f.get("createdTime", ""),
            web_link=f.get("webViewLink", ""),
            parents=f.get("parents", [])
        )
        rec.change_type = change_type
        rec.suggested_name = suggested_name

        if change_type in ["REMOVED_OR_NO_ACCESS", "TRASHED", "DELETED"]:
            rec.status = change_type
            records_to_process.append(rec)
            continue

        if size > SKIP_OVER_MB * 1024 * 1024:
            rec.status = "SKIPPED_SIZE"
            records_to_process.append(rec)
            continue

        # MD5 + Size Prefilter für Binary Files
        if not is_initial and check_md5_size_prefilter(f, known_file_details):
            rec.status = "UNCHANGED_CONTENT"
            rec.sha256 = known_file_details[file_id].get("sha", "")
            records_to_process.append(rec)
            continue

        # Streaming Hash Calculation
        sha, export_source = calculate_sha256_streaming(drive_service, rec.file_id, rec.mime_type, drive_mgr._base_params())
        rec.sha256 = sha or ""
        rec.export_source = export_source

        if not rec.sha256:
            state.log_error("PASS_1", rec.file_id, rec.name, "HashError", "Fehler bei SHA256 Berechnung")
            continue

        # Dedupe Logik
        if rec.sha256 in known_hashes:
            rec.status = "DUPLICATE"
            rec.duplicate_of = known_hashes[rec.sha256]
        else:
            rec.status = "ORIGINAL"
            known_hashes[rec.sha256] = rec.file_id

        if rec.status == "DUPLICATE" and ENABLE_ARCHIVE:
            rec.archive_result = drive_mgr.archive_duplicate(rec.file_id, rec.parents, ARCHIVE_FOLDER_ID)
            if "SUCCESS" in rec.archive_result:
                rec.status = f"DUPLICATE_OF:{rec.duplicate_of}|ARCHIVED"
                state.append_duplicate_group(rec.sha256, rec.duplicate_of, rec.file_id)

        records_to_process.append(rec)

    # Append Chunk to State
    state.append_new_hashes(records_to_process)
    state.append_dedupe_reports(records_to_process)

if __name__ == "__main__":
    run_pass1()
