import os
import time
from shared.oauth_user_credentials import get_user_credentials
from googleapiclient.discovery import build
from datetime import datetime, timezone
import logging as _logging

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker
from shared.drive_helpers import DriveManager
from shared.hash_helpers import calculate_sha256_streaming
from shared.change_type_logic import determine_change_type, check_md5_size_prefilter
from shared.models import FileRecord, KnownFileMeta

_module_log = _logging.getLogger("bummdidumm.pass1")

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


def _is_lease_stale(state, lease_timeout_sec: int) -> bool:
    heartbeat_utc_str = (
        state.get_val("lease_heartbeat_at")
        or state.get_val("lease_acquired_at")
        or state.get_val("last_run_utc")
    )
    if not heartbeat_utc_str:
        return False
    try:
        last_t = datetime.fromisoformat(heartbeat_utc_str)
    except (ValueError, TypeError):  # M-1 fix: fromisoformat raises TypeError on non-string input
        return False
    diff = (datetime.now(timezone.utc) - last_t).total_seconds()
    return diff >= lease_timeout_sec


def _claim_lease(state):
    now_utc = datetime.now(timezone.utc).isoformat()
    state.set_val("lease_owner_id", state.owner_id)
    state.set_val("lease_acquired_at", now_utc)
    state.set_val("lease_heartbeat_at", now_utc)
    state.set_val("run_id", state.run_id)
    state.flush_state()


def _touch_lease(state) -> bool:
    state.reload_state()
    if state.get_val("lease_owner_id") != state.owner_id:
        return False
    now_utc = datetime.now(timezone.utc).isoformat()
    state.set_val("lease_heartbeat_at", now_utc)
    state.flush_state()
    return True


def _release_lease(state):
    state.reload_state()
    if state.get_val("lease_owner_id") != state.owner_id:
        return
    state.set_val("lease_owner_id", "")
    state.set_val("lease_heartbeat_at", "")
    state.set_val("lease_acquired_at", "")


def _touch_lease_or_raise(state, context: str):
    if not _touch_lease(state):
        raise RuntimeError(f"Lease verloren während {context}")


def _acquire_lease_or_abort(state, log, lease_timeout_sec: int) -> bool:
    state.reload_state()
    existing_owner = state.get_val("lease_owner_id")
    existing_run_id = state.get_val("run_id")
    existing_phase = state.get_val("current_phase")

    if existing_owner and existing_owner != state.owner_id and not _is_lease_stale(state, lease_timeout_sec):
        log.warning(
            "Parallel-Run Guard: Aktiver Lease erkannt. Breche Start ab um Korruption zu vermeiden.",
            extra={
                "active_owner": existing_owner,
                "active_run": existing_run_id,
                "active_phase": existing_phase,
                "my_owner": state.owner_id,
                "my_run": state.run_id,
            },
        )
        return False

    if existing_run_id and (
        (existing_owner and existing_owner != state.owner_id and _is_lease_stale(state, lease_timeout_sec))
        or (not existing_owner and existing_phase in ["INITIAL_SCAN", "DELTA_FETCH"])
    ):
        state.run_id = existing_run_id

    _claim_lease(state)
    time.sleep(0.5)  # RISK-1 fix: 500ms fence reduces TOCTOU window before verification read
    state.reload_state()
    if state.get_val("lease_owner_id") != state.owner_id:
        log.warning("Parallel-Run Guard: Lease-Konkurrenz erkannt, Start abgebrochen.")
        return False
    if state.get_val("run_id") != state.run_id:
        log.warning("Parallel-Run Guard: run_id-Konkurrenz erkannt, Start abgebrochen.")
        return False
    return True

def run_pass1():
    if not CONTROL_SHEET_ID:
        raise ValueError("Missing CONTROL_SHEET_ID")

    credentials = get_user_credentials()
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)
    from shared.log import get_logger
    log = get_logger("pass1", run_id=state.run_id, phase="PASS_1")
    log.info("Pass 1 gestartet")
    drive_mgr = DriveManager(drive_service, TARGET_FOLDER_ID, ENABLE_SHARED_DRIVES)

    start_token = state.get_val("drive_start_page_token")
    in_progress_token = state.get_val("in_progress_page_token")
    lease_timeout_sec = int(os.environ.get("RUN_LEASE_TIMEOUT_SEC", "3600"))

    if not _acquire_lease_or_abort(state, log, lease_timeout_sec):
        return

    # 1. Load known state for heuristics
    known_file_details = state.load_known_hashes()

    # FIX: Duplicate-Hash-Lookup nur einmal pro Run aufbauen statt pro Batch neu.
    sha_to_primary_file_id = {
        meta.get("sha"): fid
        for fid, meta in known_file_details.items()
        if meta.get("sha")
    }

    inbox_trash_folder_id = _resolve_inbox_trash_folder_id(sheet_mgr)

    registry_rows = sheet_mgr.read_all_rows("Folder_Registry", "A:E")
    # Store full_path if available (index 4), else folder_name (index 1)
    folder_registry = {row[2]: row[4] if len(row) >= 5 else row[1] for row in registry_rows if len(row) >= 3 and row[0] != "folder_key"}

    processed = 0
    errors = 0

    try:
        if not start_token:
            log.info("Initialer Run: Walk über TARGET_FOLDER", extra={"folder_id": TARGET_FOLDER_ID})
            state.set_val("current_phase", "INITIAL_SCAN")
            state.flush_state()

            new_start_page_token = drive_mgr.get_initial_token()

            # Setup the callback args
            kwargs = {
                "drive_service": drive_service,
                "drive_mgr": drive_mgr,
                "state": state,
                "known_file_details": known_file_details,
                "is_initial": True,
                "inbox_trash_folder_id": inbox_trash_folder_id,
                "folder_registry": folder_registry,
                "sha_to_primary_file_id": sha_to_primary_file_id,
            }

            processed = drive_mgr.walk_recursive_chunked(
                TARGET_FOLDER_ID,
                state,
                _process_file_batch_wrapper,
                kwargs,
                lease_touch_callback=lambda: _touch_lease_or_raise(state, "Initial-Scan"),
            )

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
                _touch_lease_or_raise(state, "Delta-Fetch")
                log.debug("Delta Chunk", extra={"token": active_token})
                changes, next_token, new_start = drive_mgr.fetch_delta_chunk(active_token)
                files = [f for f in changes if f.get("mimeType") != "application/vnd.google-apps.folder"]

                _process_file_batch(
                    drive_service,
                    drive_mgr,
                    state,
                    files,
                    known_file_details,
                    False,
                    inbox_trash_folder_id,
                    folder_registry,
                    sha_to_primary_file_id,
                )
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
                state.flush_state()  # BUG-2 fix: checkpoint token advancement before success block

        state.set_val("current_phase", "PASS1_DONE")
        state.set_val("last_successful_run_id", state.run_id)
        # Coordinate handover to Pass 2 securely to avoid race conditions.
        # Pass 2 should only pick up this run_id when explicitly signaled.
        state.set_val("ready_for_pass2_run_id", state.run_id)
        state.set_val("last_run_utc", datetime.now(timezone.utc).isoformat())
        state.flush_state()       # BUG-1 fix: persist before reload_state() inside _release_lease
        state.compact_hash_index()  # compact while lease is still held to prevent race on clear+update
        state.compact_reports()
        _release_lease(state)
        state.flush_state()       # persist lease release (owner_id="")
        state.log_run("PASS_1", "SUCCESS", processed, errors)

    except Exception as e:
        state.set_val("current_phase", "PASS1_FAILED")
        state.set_val("last_run_utc", datetime.now(timezone.utc).isoformat())
        state.flush_state()       # BUG-1 fix: persist before reload_state() inside _release_lease
        _release_lease(state)
        state.flush_state()       # persist lease release
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

    _module_log.warning("01_inbox_trash nicht auflösbar")
    return ""


def _build_file_record(f: dict, drive_mgr, known_file_details: dict, is_initial: bool,
                       inbox_trash_folder_id: str, folder_registry: dict) -> FileRecord:
    """Construct a FileRecord from a raw Drive API file dict.

    Separated from the hash/dedupe logic in _process_file_batch to make each
    responsibility independently testable.
    """
    file_id = f.get("id", "")
    mime = f.get("mimeType", "")
    size = int(f.get("size", 0))
    name = f.get("name", "UNKNOWN_REMOVED")
    parents = f.get("parents", [])

    change_type = determine_change_type(f, known_file_details, is_initial)
    suggested_name = (
        suggest_rename(name, f.get("createdTime", ""))
        if change_type not in ["REMOVED_OR_NO_ACCESS", "TRASHED", "DELETED", "MOVED_OUT_OF_SCOPE"]
        else ""
    )

    lane = "ACTIVE"
    if parents and folder_registry and all(p in folder_registry for p in parents):
        base_path = folder_registry[parents[0]].rstrip("/")
        path_disp = f"{base_path}/{name}"
    else:
        path_disp = drive_mgr.get_parent_and_name_path(file_id, name, parents)

    if inbox_trash_folder_id and inbox_trash_folder_id in parents:
        lane = "INBOX_TRASH"

    rec = FileRecord(
        file_id=file_id,
        name=name,
        parent_ids_sorted=",".join(sorted(parents)),
        path_display=path_disp,
        mime_type=mime,
        size_bytes=size,
        md5=f.get("md5Checksum", ""),
        updated_at=f.get("modifiedTime", ""),
        created_time=f.get("createdTime", ""),
        web_link=f.get("webViewLink", ""),
        parents=parents,
        description=f.get("description", ""),
        starred=f.get("starred", False),
        owner_email=(f.get("owners") or [{}])[0].get("emailAddress", ""),
        owner_name=(f.get("owners") or [{}])[0].get("displayName", ""),
        last_modified_by_email=(f.get("lastModifyingUser") or {}).get("emailAddress", ""),
        can_edit=(f.get("capabilities") or {}).get("canEdit", True),
        can_share=(f.get("capabilities") or {}).get("canShare", True),
        can_download=(f.get("capabilities") or {}).get("canDownload", True),
    )
    rec.change_type = change_type
    rec.suggested_name = suggested_name
    rec.notes = f"Lane: {lane}"
    return rec


def _process_file_batch_wrapper(files, **kwargs):
    _process_file_batch(files=files, **kwargs)


def _process_file_batch(
    drive_service,
    drive_mgr,
    state,
    files,
    known_file_details: dict[str, KnownFileMeta],
    is_initial,
    inbox_trash_folder_id: str,
    folder_registry: dict = None,
    sha_to_primary_file_id: dict = None,
):
    if folder_registry is None:
        folder_registry = {}

    if sha_to_primary_file_id is None:
        # FIX: Fallback für Tests / ältere Aufrufer, falls das Lookup nicht
        # von run_pass1() vorab übergeben wurde.
        sha_to_primary_file_id = {
            meta.get("sha"): fid
            for fid, meta in known_file_details.items()
            if meta.get("sha")
        }

    records_to_process = []
    duplicate_groups_accumulator = {}

    # ------------------------------------------------------------------ #
    # Inner helpers – closures over the mutable accumulators above.       #
    # Each helper handles one change-type branch and appends to           #
    # records_to_process / updates known_file_details as needed.          #
    # ------------------------------------------------------------------ #

    def _make_cache_entry(rec: FileRecord) -> KnownFileMeta:
        return {
            "sha": rec.sha256,
            "name": rec.name,
            "parent_ids_sorted": rec.parent_ids_sorted,
            "path_display": rec.path_display,
            "updated_at": rec.updated_at,
            "size_bytes": rec.size_bytes,
            "md5": rec.md5,
            "effective_mime_type": rec.effective_mime_type,
        }

    def _handle_removed(rec: FileRecord) -> None:
        rec.status = rec.change_type
        records_to_process.append(rec)

    def _handle_unchanged(rec: FileRecord) -> None:
        rec.status = "UNCHANGED_CONTENT"
        rec.sha256 = known_file_details.get(rec.file_id, {}).get("sha", "")
        if rec.sha256 == "HASH_SKIPPED_SIZE":
            rec.status = "SKIPPED_SIZE"
        # Update cache metadata; seed entry if somehow missing.
        if rec.file_id in known_file_details:
            known_file_details[rec.file_id].update({
                "name": rec.name,
                "parent_ids_sorted": rec.parent_ids_sorted,
                "path_display": rec.path_display,
                "updated_at": rec.updated_at,
            })
        else:
            known_file_details[rec.file_id] = _make_cache_entry(rec)
        records_to_process.append(rec)

    def _handle_skipped_size(rec: FileRecord) -> None:
        rec.status = "SKIPPED_SIZE"
        rec.sha256 = "HASH_SKIPPED_SIZE"
        # Update cache sofort für denselben Batch, damit nachfolgende Deltas ihn kennen.
        known_file_details[rec.file_id] = _make_cache_entry(rec)
        records_to_process.append(rec)

    def _handle_new_or_updated(rec: FileRecord) -> None:
        sha, export_source = calculate_sha256_streaming(
            drive_service, rec.file_id, rec.mime_type, drive_mgr._base_params()
        )
        rec.sha256 = sha or ""
        rec.export_source = export_source

        if not rec.sha256:
            state.log_error("PASS_1", rec.file_id, rec.name, "HashError", "SHA256 fehlgeschlagen")
            rec.status = "HASH_ERROR"
            records_to_process.append(rec)
            return

        # Dedupe Logik über Hash Map (O(1))
        duplicate_of_id = sha_to_primary_file_id.get(rec.sha256)
        if duplicate_of_id:
            rec.status = "ORIGINAL_RESUMED" if duplicate_of_id == rec.file_id else "DUPLICATE"
            if rec.status == "DUPLICATE":
                rec.duplicate_of = duplicate_of_id
            else:
                # DM-3 fix: ORIGINAL_RESUMED must refresh its cache entry so subsequent
                # delta runs detect metadata changes (name, path, updated_at) correctly.
                known_file_details[rec.file_id] = _make_cache_entry(rec)
        else:
            rec.status = "ORIGINAL"
            sha_to_primary_file_id[rec.sha256] = rec.file_id
            # Update cache sofort für denselben Batch.
            known_file_details[rec.file_id] = _make_cache_entry(rec)

        if rec.status == "DUPLICATE" and ENABLE_ARCHIVE:
            rec.archive_result = drive_mgr.archive_duplicate(rec.file_id, rec.parents, ARCHIVE_FOLDER_ID)
            if "SUCCESS" in rec.archive_result:
                rec.status = f"DUPLICATE_OF:{rec.duplicate_of}|ARCHIVED"
                if rec.sha256 not in duplicate_groups_accumulator:
                    duplicate_groups_accumulator[rec.sha256] = {"original": rec.duplicate_of, "duplicates": set()}
                duplicate_groups_accumulator[rec.sha256]["duplicates"].add(rec.file_id)

        records_to_process.append(rec)

    # ------------------------------------------------------------------ #
    # Main dispatch loop                                                  #
    # ------------------------------------------------------------------ #

    for f in files:
        rec = _build_file_record(
            f, drive_mgr, known_file_details, is_initial,
            inbox_trash_folder_id, folder_registry,
        )
        change_type = rec.change_type

        if change_type in ["REMOVED_OR_NO_ACCESS", "TRASHED", "DELETED", "MOVED_OUT_OF_SCOPE"]:
            _handle_removed(rec)
        elif change_type == "UNCHANGED_CONTENT_METADATA_ONLY" or (
            not is_initial and check_md5_size_prefilter(f, known_file_details)
        ):
            _handle_unchanged(rec)
        elif rec.size_bytes > SKIP_OVER_MB * 1024 * 1024:
            _handle_skipped_size(rec)
        else:
            _handle_new_or_updated(rec)

    state.append_new_hashes(records_to_process)
    state.append_dedupe_reports(records_to_process)
    state.flush_duplicate_groups(duplicate_groups_accumulator)

if __name__ == "__main__":
    run_pass1()
