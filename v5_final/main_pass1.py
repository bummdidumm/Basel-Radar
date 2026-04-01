import os
from typing import List, Dict
import google.auth
from googleapiclient.discovery import build
from datetime import datetime, timezone

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker
from shared.drive_helpers import DriveManager
from shared.hash_helpers import calculate_sha256_streaming
from shared.change_type_logic import determine_change_type, check_md5_size_prefilter
from shared.models import FileRecord

TARGET_FOLDER_ID = os.environ.get("TARGET_FOLDER_ID")
ARCHIVE_FOLDER_ID = os.environ.get("ARCHIVE_FOLDER_ID")
CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
PROJECT_SLUG = os.environ.get("PROJECT_SLUG", "bummdidumm")

SKIP_OVER_MB = int(os.environ.get("SKIP_OVER_MB", "500"))
ENABLE_ARCHIVE = os.environ.get("ENABLE_ARCHIVE", "true").lower() == "true"
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"

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

    # 1. Load known state for heuristics
    known_file_details = state.load_known_hashes()

    processed = 0
    errors = 0
    all_records = []

    try:
        if not start_token:
            print("Initialer Run: Führe kompletten Walk über TARGET_FOLDER durch.")
            state.set_val("current_phase", "INITIAL_SCAN")

            all_items = drive_mgr.walk_recursive(TARGET_FOLDER_ID)
            files = [f for f in all_items if f.get("mimeType") != "application/vnd.google-apps.folder"]
            new_start_page_token = drive_mgr.get_initial_token()

            _process_file_batch(drive_service, drive_mgr, state, files, known_file_details, True)
            processed = len(files)

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

                _process_file_batch(drive_service, drive_mgr, state, files, known_file_details, False)
                processed += len(files)

                if next_token:
                    active_token = next_token
                    state.set_val("in_progress_page_token", active_token)
                else:
                    new_start_page_token = new_start
                    break

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

def _process_file_batch(drive_service, drive_mgr, state, files, known_file_details, is_initial):
    records_to_process = []
    duplicate_groups_accumulator = {}

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
            parent_ids_sorted=",".join(sorted(f.get("parents", []))),
            path_display=drive_mgr.get_full_path(file_id, name, f.get("parents")),
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

        # Reiner Metadaten-Zustand, der nicht ge-hashed werden muss (falls Inhalt identisch und kein MOVED/RENAMED stattfand)
        if change_type == "UNCHANGED_CONTENT_METADATA_ONLY":
            rec.status = "UNCHANGED_CONTENT"
            rec.sha256 = known_file_details[file_id].get("sha", "")

            if rec.sha256 == "HASH_SKIPPED":
                rec.status = "SKIPPED_SIZE"

            known_file_details[rec.file_id].update({
                "name": rec.name,
                "parent_ids_sorted": rec.parent_ids_sorted,
                "path_display": rec.path_display,
                "updated_at": rec.updated_at
            })
            records_to_process.append(rec)
            continue

        if size > SKIP_OVER_MB * 1024 * 1024:
            rec.status = "SKIPPED_SIZE"
            rec.sha256 = "HASH_SKIPPED"
            # Update cache sofort für denselben Batch, damit nachfolgende Deltas ihn kennen
            known_file_details[rec.file_id] = {
                "sha": rec.sha256,
                "name": rec.name,
                "parent_ids_sorted": rec.parent_ids_sorted,
                "path_display": rec.path_display,
                "updated_at": rec.updated_at,
                "size_bytes": rec.size_bytes,
                "md5": rec.md5,
                "effective_mime_type": rec.effective_mime_type
            }
            records_to_process.append(rec)
            continue

        if not is_initial and check_md5_size_prefilter(f, known_file_details):
            rec.status = "UNCHANGED_CONTENT"
            rec.sha256 = known_file_details[file_id].get("sha", "")

            # Falls SKIPPED_SIZE Datei jetzt wegen Metadaten-Update als UNCHANGED_CONTENT durchgeht,
            # beenden wir die Iteration hier, da wir den Hash immer noch skippen.
            if rec.sha256 == "HASH_SKIPPED":
                rec.status = "SKIPPED_SIZE"

            known_file_details[rec.file_id].update({
                "name": rec.name,
                "parent_ids_sorted": rec.parent_ids_sorted,
                "path_display": rec.path_display,
                "updated_at": rec.updated_at
            })
            records_to_process.append(rec)
            continue

        sha, export_source = calculate_sha256_streaming(drive_service, rec.file_id, rec.mime_type, drive_mgr._base_params())
        rec.sha256 = sha or ""
        rec.export_source = export_source

        if not rec.sha256:
            state.log_error("PASS_1", rec.file_id, rec.name, "HashError", "Fehler bei SHA256 Berechnung")
            continue

        # Dedupe Logik über Value Iteration (da dict jetzt nach File-ID organisiert ist)
        duplicate_of_id = None
        for fid, meta in known_file_details.items():
            if meta.get("sha") == rec.sha256:
                duplicate_of_id = fid
                break

        if duplicate_of_id:
            if duplicate_of_id == rec.file_id:
                rec.status = "ORIGINAL_RESUMED"
            else:
                rec.status = "DUPLICATE"
                rec.duplicate_of = duplicate_of_id
        else:
            rec.status = "ORIGINAL"
            # Update cache sofort für denselben Batch
            known_file_details[rec.file_id] = {
                "sha": rec.sha256,
                "name": rec.name,
                "path": ",".join(rec.parents) if rec.parents else "",
                "updated_at": rec.updated_at,
                "size_bytes": rec.size_bytes,
                "md5": rec.md5,
                "effective_mime_type": rec.effective_mime_type
            }

        if rec.status == "DUPLICATE" and ENABLE_ARCHIVE:
            rec.archive_result = drive_mgr.archive_duplicate(rec.file_id, rec.parents, ARCHIVE_FOLDER_ID)
            if "SUCCESS" in rec.archive_result:
                rec.status = f"DUPLICATE_OF:{rec.duplicate_of}|ARCHIVED"

                # Accumulate for batched writes
                if rec.sha256 not in duplicate_groups_accumulator:
                    duplicate_groups_accumulator[rec.sha256] = {"original": rec.duplicate_of, "duplicates": set()}
                duplicate_groups_accumulator[rec.sha256]["duplicates"].add(rec.file_id)

        records_to_process.append(rec)

    state.append_new_hashes(records_to_process)
    state.append_dedupe_reports(records_to_process)
    state.flush_duplicate_groups(duplicate_groups_accumulator)

if __name__ == "__main__":
    run_pass1()
