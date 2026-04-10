import os
from shared.oauth_user_credentials import get_user_credentials
from googleapiclient.discovery import build
from datetime import datetime, timezone

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker
from shared.drive_helpers import DriveManager
from shared.hash_helpers import calculate_sha256_streaming
from shared.change_type_logic import determine_change_type, check_md5_size_prefilter
from shared.models import FileRecord

TARGET_FOLDER_ID = os.environ.get("TARGET_FOLDER_ID", "")
ARCHIVE_FOLDER_ID = os.environ.get("ARCHIVE_FOLDER_ID")
CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
PROJECT_SLUG = os.environ.get("PROJECT_SLUG", "bummdidumm")

SKIP_OVER_MB = int(os.environ.get("SKIP_OVER_MB", "500"))
ENABLE_ARCHIVE = os.environ.get("ENABLE_ARCHIVE", "true").lower() == "true"
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"
INBOX_TRASH_FOLDER_ID = os.environ.get("INBOX_TRASH_FOLDER_ID", "")

def suggest_rename(name: str, created_time: str, project_slug: str = PROJECT_SLUG) -> str:
    if not created_time:
        return name
    iso_date = created_time[:10]
    if name.startswith(f"{iso_date}_"):
        return name
    safe = name.replace(":", "-").strip()
    return f"{iso_date}_{project_slug}_{safe}"

def run_pass1():
    print("Starte Pass 1: Delta + Dedupe + Archivierung")
    if not CONTROL_SHEET_ID:
        raise ValueError("Missing CONTROL_SHEET_ID")

    credentials = get_user_credentials()
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)
    drive_mgr = DriveManager(drive_service, TARGET_FOLDER_ID, ENABLE_SHARED_DRIVES)

    start_token = state.get_val("drive_start_page_token")
    in_progress_token = state.get_val("in_progress_page_token")

    # 1. Load known state for heuristics
    known_file_details = state.load_known_hashes()

    # ⚡ Bolt: Build lookup dictionary once, outside the batch loop (O(N) initialization)
    sha_to_primary_file_id = {meta.get("sha"): fid for fid, meta in known_file_details.items() if meta.get("sha")}

    inbox_trash_folder_id = _resolve_inbox_trash_folder_id(sheet_mgr)

    registry_rows = sheet_mgr.read_all_rows("Folder_Registry", "A:E")
    # Store full_path if available (index 4), else folder_name (index 1)
    folder_registry = {row[2]: row[4] if len(row) >= 5 else row[1] for row in registry_rows if len(row) >= 3 and row[0] != "folder_key"}

    processed = 0
    errors = 0

    try:
        if not start_token:
            print("Initialer Run: Führe kompletten Walk über TARGET_FOLDER durch.")
            state.set_val("current_phase", "INITIAL_SCAN")

            new_start_page_token = drive_mgr.get_initial_token()
            all_items = drive_mgr.walk_recursive(TARGET_FOLDER_ID)
            files = [f for f in all_items if f.get("mimeType") != "application/vnd.google-apps.folder"]

            _process_file_batch(drive_service, drive_mgr, state, files, known_file_details, True, inbox_trash_folder_id, folder_registry, sha_to_primary_file_id)
            processed = len(files)

            state.set_val("drive_start_page_token", new_start_page_token)
            state.flush_state()

        else:
            active_token = in_progress_token if in_progress_token else start_token
            if active_token != in_progress_token:
                state.set_val("in_progress_page_token", active_token)
                state.set_val("current_phase", "DELTA_FETCH")
                state.flush_state()

            new_start_page_token = None

            while active_token:
                print(f"Hole Delta Chunk: {active_token}")
                changes, next_token, new_start = drive_mgr.fetch_delta_chunk(active_token)
                files = [f for f in changes if f.get("mimeType") != "application/vnd.google-apps.folder"]

                _process_file_batch(drive_service, drive_mgr, state, files, known_file_details, False, inbox_trash_folder_id, folder_registry, sha_to_primary_file_id)
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

def _resolve_inbox_trash_folder_id(sheet_mgr) -> str:
    if INBOX_TRASH_FOLDER_ID:
        return INBOX_TRASH_FOLDER_ID

    try:
        registry_rows = sheet_mgr.read_all_rows("Folder_Registry", "A:C")
        for row in registry_rows:
            if len(row) >= 3 and row[0] == "01_inbox_trash":
                return row[2]
    except Exception:
        pass

    print("WARN: 01_inbox_trash lane is conceptually expected but cannot be resolved from env or Folder_Registry.")
    return ""


def _process_file_batch(drive_service, drive_mgr, state, files, known_file_details, is_initial, inbox_trash_folder_id: str, folder_registry: dict = None, sha_to_primary_file_id: dict = None):
    if folder_registry is None:
        folder_registry = {}
    if sha_to_primary_file_id is None:
        # Fallback for backwards compatibility or tests that don't provide it
        sha_to_primary_file_id = {meta.get("sha"): fid for fid, meta in known_file_details.items() if meta.get("sha")}

    records_to_process = []
    duplicate_groups_accumulator = {}

    for f in files:
        file_id = f.get("id", "")
        mime = f.get("mimeType", "")
        size = int(f.get("size", 0))
        name = f.get("name", "UNKNOWN_REMOVED")

        change_type = determine_change_type(f, known_file_details, is_initial)
        suggested_name = suggest_rename(name, f.get("createdTime", "")) if change_type not in ["REMOVED_OR_NO_ACCESS", "TRASHED", "DELETED"] else ""

        lane = "ACTIVE"
        parents = f.get("parents", [])

        if parents and folder_registry and all(p in folder_registry for p in parents):
            # full_path is typically absolute like "/00_inbox/...", we don't need to join them all,
            # we just take the first parent's full path since files usually reside in one primary folder.
            base_path = folder_registry[parents[0]].rstrip("/")
            path_disp = f"{base_path}/{name}"
        else:
            path_disp = drive_mgr.get_parent_and_name_path(file_id, name, parents)

        if inbox_trash_folder_id and inbox_trash_folder_id in parents:
            lane = "INBOX_TRASH"

        rec = FileRecord(
            file_id=file_id,
            name=name,
            parent_ids_sorted=",".join(sorted(f.get("parents", []))),
            path_display=path_disp,
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
        rec.notes = f"Lane: {lane}"

        if change_type in ["REMOVED_OR_NO_ACCESS", "TRASHED", "DELETED"]:
            rec.status = change_type
            records_to_process.append(rec)
            continue

        # Wenn sich Inhalte nicht geändert haben (UNCHANGED_CONTENT_METADATA_ONLY) ODER
        # wenn ein MOVED/RENAMED stattfand, bei dem die Binärdaten laut Prefilter
        # identisch geblieben sind, wollen wir das Hashing überspringen.
        if change_type == "UNCHANGED_CONTENT_METADATA_ONLY" or (not is_initial and check_md5_size_prefilter(f, known_file_details)):
            rec.status = "UNCHANGED_CONTENT"
            rec.sha256 = known_file_details[file_id].get("sha", "")

            if rec.sha256 == "HASH_SKIPPED_SIZE":
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
            rec.sha256 = "HASH_SKIPPED_SIZE"
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
            sha_to_primary_file_id[rec.sha256] = rec.file_id
            records_to_process.append(rec)
            continue

        sha, export_source = calculate_sha256_streaming(drive_service, rec.file_id, rec.mime_type, drive_mgr._base_params())
        rec.sha256 = sha or ""
        rec.export_source = export_source

        if not rec.sha256:
            state.log_error("PASS_1", rec.file_id, rec.name, "HashError", "SHA256 fehlgeschlagen")
            rec.status = "HASH_ERROR"
            records_to_process.append(rec)
            continue

        # Dedupe Logik über Hash Map (O(1))
        duplicate_of_id = sha_to_primary_file_id.get(rec.sha256)

        if duplicate_of_id:
            if duplicate_of_id == rec.file_id:
                rec.status = "ORIGINAL_RESUMED"
            else:
                rec.status = "DUPLICATE"
                rec.duplicate_of = duplicate_of_id
        else:
            rec.status = "ORIGINAL"
            sha_to_primary_file_id[rec.sha256] = rec.file_id
            # Update cache sofort für denselben Batch
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
