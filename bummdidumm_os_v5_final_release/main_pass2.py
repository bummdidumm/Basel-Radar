from pathlib import Path
import os
import json
import tempfile
from datetime import datetime, timezone

from shared.oauth_user_credentials import get_user_credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

from shared.sheets_helpers import SheetManager
from shared.state_helpers import StateTracker
from shared.drive_helpers import DriveManager
from shared.gemini_helpers import GeminiOCR
from shared.models import FileRecord
from personal_brain.runtime import PersonalBrainRuntime
from personal_brain.source_ingestion import inspect_source
from personal_brain.utils import sanitize_path
from personal_brain.utils import PARSEABLE_EXTS as _PARSEABLE_EXTS, PARSEABLE_MIMES as _PARSEABLE_MIMES
from personal_brain.utils import get_parseable_mime_type
import zipfile
import hashlib
import logging
from shared.log import get_logger

CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
INDEX_FOLDER_ID = os.environ.get("INDEX_FOLDER_ID")
PROJECT_SLUG = os.environ.get("PROJECT_SLUG", "bummdidumm")
# Persistent root for the local brain index mirror.
# Set BRAIN_INDEX_ROOT to a path that survives restarts (e.g. a mounted volume or
# a directory synced back to Drive). Defaults to a subdirectory next to this file.
BRAIN_INDEX_ROOT = Path(os.environ.get("BRAIN_INDEX_ROOT", str(Path(__file__).parent / "brain_index")))
if "K_SERVICE" in os.environ and not os.environ.get("BRAIN_INDEX_ROOT"):
    # Fail fast if running in Cloud Run without persistent brain_index mapping
    raise RuntimeError("BRAIN_INDEX_ROOT must be set explicitly when running in Cloud Run to avoid index ephemeral destruction.")


ENABLE_OCR = os.environ.get("ENABLE_OCR", "true").lower() == "true"
OCR_BUDGET_PER_RUN = int(os.environ.get("OCR_BUDGET_PER_RUN", "500"))
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"

# Extensions and MIME types for which we attempt a real Drive download so the
# parser can open the actual file content rather than falling back to OCR text.
_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB cap per file


def _download_drive_file_to_tmp(drive_service, file_id: str, size_bytes: int, enable_shared_drives: bool) -> str | None:
    """Download a Drive file to a NamedTemporaryFile and return the local path.

    Returns None on any error. The caller is responsible for deleting the file.
    We cap downloads at _MAX_DOWNLOAD_BYTES to avoid memory exhaustion on
    accidentally large files landing in an export folder.
    """
    if size_bytes > _MAX_DOWNLOAD_BYTES:
        return None
    params = {"supportsAllDrives": True} if enable_shared_drives else {}
    tmp_path = None
    for attempt in range(3):
        try:
            request = drive_service.files().get_media(fileId=file_id, **params)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".tmp") as tmp:
                tmp_path = tmp.name
                downloader = MediaIoBaseDownload(tmp, request, chunksize=4 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                tmp.flush()
                return tmp_path
        except Exception as e:
            from googleapiclient.errors import HttpError
            import time
            is_http_err = isinstance(e, HttpError)
            status_code = getattr(e.resp, 'status', 'unknown') if is_http_err else 'N/A'
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            tmp_path = None
            if status_code in (429, 503, 500, 502) and attempt < 2:
                logging.warning(f"Retrying transient download error {status_code} for {file_id}")
                time.sleep((2 ** attempt) + 1)
                continue

            logging.debug(f"Failed to download drive file {file_id}: {e}")
            return None
    return None


def _extract_zip_sources(zip_bytes: bytes, parent_rec) -> list[dict]:
    """Parse parseable files inside a ZIP archive and return source dicts for each.

    Each sub-file is written to a short-lived temp file, parsed by inspect_source,
    then the temp file is immediately deleted. The parent record supplies metadata
    (run_utc, file_id, sha256, etc.) used to build stable sub-file IDs.
    """
    import io
    sources = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as z:
            for zinfo in z.infolist():
                if zinfo.is_dir() or zinfo.file_size > 50 * 1024 * 1024:
                    continue
                sub_ext = os.path.splitext(zinfo.filename)[1].lower()
                if sub_ext not in _PARSEABLE_EXTS:
                    continue
                sub_mime = get_parseable_mime_type(sub_ext)
                sub_local_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=sub_ext) as tf:
                        sub_local_path = tf.name
                        tf.write(z.read(zinfo))

                    sanitized_name = sanitize_path(zinfo.filename)
                    sub_detected = inspect_source(
                        source_path=sub_local_path,
                        mime=sub_mime,
                        ext=sub_ext,
                        fallback_text="",
                        original_path=sanitized_name,
                    )
                    sub_content = sub_detected.get("content", {})
                    sub_content.setdefault("title", sanitized_name)
                    sub_event_time = parent_rec.ocr_date or parent_rec.run_utc or ""
                    sub_content.setdefault("event_time_start", sub_event_time)
                    sub_content.setdefault("event_date", sub_event_time[:10] if sub_event_time else "")

                    sub_checksum = hashlib.sha256(Path(sub_local_path).read_bytes()).hexdigest()
                    canonical_sub_path = f"{parent_rec.path_display or parent_rec.name}/{sanitized_name}"
                    sub_file_id = f"{parent_rec.file_id}_{hashlib.sha256((parent_rec.sha256 + sanitized_name).encode('utf-8')).hexdigest()}"
                    sources.append({
                        "file_id": sub_file_id,
                        "bundle_id": parent_rec.file_id,
                        "source_path": canonical_sub_path,
                        "source_path_rel": canonical_sub_path,
                        "original_filename": sanitized_name,
                        "mime": sub_mime,
                        "ext": sub_ext,
                        "checksum_sha256": sub_checksum,
                        "raw_ref": f"{parent_rec.web_link or parent_rec.path_display or parent_rec.name}/{sanitized_name}",
                        "status": parent_rec.status,
                        "sot_status": "derived",
                        "canonical_format": "text" if sub_mime.startswith("text/") else "json" if "json" in sub_mime else "unknown",
                        "preview": {
                            "coverage_start": parent_rec.run_utc,
                            "coverage_end": parent_rec.run_utc,
                            **sub_detected.get("preview", {}),
                        },
                        "text_preview": sub_detected.get("text_preview", ""),
                        "content": sub_content,
                        "is_export": sub_detected.get("is_export", True),
                        "is_bundle": sub_detected.get("is_bundle", False),
                        "is_archive": False,
                        "contains_pii": False,
                        "contains_messages": "message" in sanitized_name.lower() or "chat" in sanitized_name.lower(),
                        "contains_geo": "map" in sanitized_name.lower() or "location" in sanitized_name.lower(),
                        "contains_financial": False,
                        "contains_media_refs": False,
                    })
                except Exception as e:
                    logging.warning(f"Error parsing sub-file {zinfo.filename}: {e}")
                finally:
                    if sub_local_path and os.path.exists(sub_local_path):
                        os.remove(sub_local_path)
    except Exception as e:
        logging.warning(f"Failed to open ZIP for {parent_rec.file_id}: {e}")
    return sources


def _build_source_from_record(rec, drive_service, enable_shared_drives: bool) -> list[dict]:
    """Build one or more source dicts for a single FileRecord.

    Downloads the file if parseable, runs inspect_source, and expands ZIP
    archives into additional per-file source dicts. Returns a list because
    a single ZIP record can yield multiple sources.
    """
    ext = os.path.splitext(rec.name)[1].lower()
    mime = rec.effective_mime_type or rec.mime_type or ""

    local_path: str | None = None
    detected = {}
    try:
        # Skip download if Drive reports file is not downloadable
        if not rec.can_download:
            detected = inspect_source(
                source_path=rec.path_display or rec.name,
                mime=mime, ext=ext,
                fallback_text=rec.ocr_summary or rec.notes or "",
            )
        elif rec.file_id and (ext in _PARSEABLE_EXTS or mime in _PARSEABLE_MIMES or ext == ".zip" or "zip" in mime):
            local_path = _download_drive_file_to_tmp(
                drive_service, rec.file_id, rec.size_bytes, enable_shared_drives
            )
            detected = inspect_source(
                source_path=local_path or rec.path_display or rec.name,
                mime=mime,
                ext=ext,
                fallback_text=rec.ocr_full_text or rec.ocr_summary or rec.notes or "",
            )
        else:
            detected = inspect_source(
                source_path=rec.path_display or rec.name,
                mime=mime,
                ext=ext,
                fallback_text=rec.ocr_full_text or rec.ocr_summary or rec.notes or "",
            )

        # Fix leak of temp path in title
        if local_path and detected.get("content", {}).get("title") == os.path.basename(local_path):
            detected["content"]["title"] = rec.name

        # Recursive dispatch: if the detected content found parseable files inside a ZIP
        zip_sources: list[dict] = []
        if detected.get("is_archive") and "archive_files" in detected.get("content", {}) and local_path:
            zip_bytes = Path(local_path).read_bytes()
            zip_sources = _extract_zip_sources(zip_bytes, rec)
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)

    content = detected.get("content", {})
    content.setdefault("title", rec.name)
    content.setdefault("summary", rec.ocr_summary or rec.notes or "")
    event_time = rec.ocr_date or rec.run_utc or ""
    content.setdefault("event_time_start", event_time)
    content.setdefault("event_date", event_time[:10] if event_time else "")
    if rec.folder_rule:
        content.setdefault("apps", [rec.folder_rule])
    # Use OCR doc_type as a semantic topic hint; avoid using change_type
    # (which is an internal delta status, not a meaningful topic).
    ocr_topic = rec.ocr_doc_type.strip() if rec.ocr_doc_type else ""
    content.setdefault("topics", [ocr_topic] if ocr_topic else [])
    # OCR-extracted people/orgs → inject into content for Brain Index entity extraction
    if rec.ocr_people:
        content["people"] = list(dict.fromkeys(content.get("people", []) + rec.ocr_people))
    if rec.ocr_organizations:
        content["apps"] = list(dict.fromkeys(content.get("apps", []) + rec.ocr_organizations))
    # Starred files → higher importance_score
    if rec.starred:
        content["importance_score"] = min(1.0, content.get("importance_score", 0.5) + 0.25)
    content.setdefault("url", rec.web_link or "")

    canonical_path = rec.path_display or rec.name
    parent_source = {
        "file_id": rec.file_id,
        "source_path": canonical_path,
        "source_path_rel": canonical_path,
        "original_filename": rec.name,
        "mime": mime,
        "ext": ext,
        "checksum_sha256": rec.sha256 or "",
        "raw_ref": rec.web_link or rec.path_display or rec.name,
        "status": rec.status,
        "sot_status": "derived",
        "canonical_format": "binary" if mime == "application/octet-stream" else "text" if mime.startswith("text/") else "json" if "json" in mime else "unknown",
        "preview": {
            "coverage_start": rec.run_utc,
            "coverage_end": rec.run_utc,
            **detected.get("preview", {}),
        },
        "text_preview": detected.get("text_preview", ""),
        "content": content,
        "is_export": detected.get("is_export", True),
        "is_bundle": detected.get("is_bundle", False),
        "is_archive": detected.get("is_archive", False),
        "contains_pii": rec.ocr_sensitivity in ("medium", "high"),
        "contains_messages": "message" in (rec.ocr_doc_type or "").lower(),
        "contains_geo": "map" in (rec.path_display or "").lower(),
        "contains_financial": bool(rec.ocr_amount),
        "contains_media_refs": rec.mime_type.startswith("image/"),
    }
    return zip_sources + [parent_source]


def _build_personal_brain_sources(records_to_index, drive_service, enable_shared_drives: bool) -> list[dict]:
    """Convert FileRecord objects into personal-brain source dicts.

    For parseable file types we download the actual file from Drive so that
    inspect_source can open and read real content (JSON, HTML, ICS, CSV, TXT).
    Temp files are deleted immediately after content is loaded into memory.
    """
    sources = []
    for rec in records_to_index:
        sources.extend(_build_source_from_record(rec, drive_service, enable_shared_drives))
    return sources


def run_pass2():
    if not all([CONTROL_SHEET_ID, INDEX_FOLDER_ID]):
        raise ValueError("Missing CONTROL_SHEET_ID or INDEX_FOLDER_ID")

    credentials = get_user_credentials()
    drive_service = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    sheet_mgr = SheetManager(sheets_service, CONTROL_SHEET_ID)
    state = StateTracker(sheet_mgr)
    drive_mgr = DriveManager(drive_service, "", ENABLE_SHARED_DRIVES)
    log = get_logger("pass2", run_id=state.run_id, phase="PASS_2")
    log.info("Pass 2 gestartet")
    ocr = GeminiOCR(drive_service, ENABLE_SHARED_DRIVES)
    ocr_calls_this_run = 0

    current_run_id = state.get_val("ready_for_pass2_run_id")

    if not current_run_id:
        state.set_val("current_phase", "PASS2_BLOCKED_NO_HANDOVER")
        state.flush_state()
        state.log_error("PASS_2", "SYSTEM", "", "NoRunID", "Keine explizite Pass 1 Übergabe (ready_for_pass2_run_id) gefunden.")
        return

    state.set_val("current_phase", "PASS2_OCR_INDEXING")
    state.flush_state()

    # Load Knowledge Exclusions
    exclusions = {}
    for row in sheet_mgr.read_all_rows("Knowledge_Exclusions", "A:D"):
        if len(row) >= 3 and row[0] != "file_id":
            exclusions[row[0]] = row[2]  # file_id -> status (EXCLUDED/PURGED)

    # Lese Folder-Aware Indexing Daten chunkweise aus Sorting_Suggestions ein, um OOM bei >100k Files zu verhindern.
    # Wir projizieren nur die absolut notwendigen Felder des AKTUELLEN Runs in ein lokales Dict.
    # Da dies nur die Deltas eines Runs sind, bleibt der RAM-Footprint auch bei Millionen historischer Einträge im Sheet minimal (<50MB) und locker im 2GiB Limit.
    # Schema: ["run_id", "file_id", "name", "mime_type", "current_location", "current_parent_id", "folder_rule", "folder_rule_reason", "suggested_target_folder", "suggested_target_folder_id", "target_path", "action_mode", "move_result"]
    sorting_data = {}
    for sort_chunk in sheet_mgr.read_rows_chunked("Sorting_Suggestions", chunk_size=2000):
        for s_row in sort_chunk:
            # FIX: Off-by-one-Grenze bei Sorting-Zeilen -> Zugriff auf Index 12 nur noch ab 13 Spalten.
            if len(s_row) >= 13 and s_row[0] == current_run_id:
                sorting_data[s_row[1]] = {
                    "current_parent_id": s_row[5],
                    "folder_rule": s_row[6],
                    "folder_rule_reason": s_row[7],
                    "target_parent_id": s_row[9],
                    "target_path": s_row[10],
                    "sort_mode": s_row[11],
                    "move_result": s_row[12]
                }

    records_to_index = []
    processed = 0
    errors = 0

    # Cap Pass 2 RAM load: Chunkweises Auslesen
    for chunk_rows in sheet_mgr.read_rows_chunked("Dedupe_Report", chunk_size=1000):
        for row in chunk_rows:
            if len(row) < 17 or row[0] == "run_utc":
                continue
            if row[1] != current_run_id:
                continue # Nur Dateien des letzten Laufs

            status = row[10]
            change_type = row[11]
            file_id = row[4]
            mime_type = row[5]

            # Validiere, welche Records wir überhaupt an das AI-OS im JSONL weiterleiten.
            # Wir lassen "DUPLICATE" und "SKIPPED_SIZE" weg.
            # MOVED_OUT_OF_SCOPE wird eingeschlossen, damit der Brain-Index scope-exits
            # als event_only empfängt und abgeleitete Einträge bereinigen kann.
            valid_statuses = ("ORIGINAL", "ORIGINAL_RESUMED", "UNCHANGED_CONTENT", "DELETED", "TRASHED", "REMOVED_OR_NO_ACCESS", "MOVED_OUT_OF_SCOPE")
            if not status.startswith(valid_statuses):
                continue

            rec = FileRecord(
                run_utc=row[0],
                run_id=row[1],
                path_display=row[2],
                name=row[3],
                file_id=file_id,
                mime_type=mime_type,
                effective_mime_type=row[6],
                size_bytes=int(row[7]) if str(row[7]).isdigit() else 0,
                md5=row[8],
                sha256=row[9],
                status=status,
                change_type=change_type,
                duplicate_of=row[12],
                archive_result=row[13],
                suggested_name=row[14],
                web_link=row[15],
                notes=row[16]
            )

            # Folder-Aware Indexing anreichern
            rec.current_path = rec.path_display
            s_data = sorting_data.get(file_id, {})
            if s_data:
                rec.current_parent_id = s_data.get("current_parent_id", "")
                rec.current_path = rec.path_display
                rec.target_parent_id = s_data.get("target_parent_id", "")
                rec.target_path = s_data.get("target_path", "")
                rec.folder_rule = s_data.get("folder_rule", "")
                rec.folder_rule_reason = s_data.get("folder_rule_reason", "")
                rec.sort_mode = s_data.get("sort_mode", "")
                rec.move_result = s_data.get("move_result", "")

            # ZWEI-PFADE ORCHESTRIERUNG FÜR PASS 2
            # Pfad A: OCR-pflichtige Originale
            if ENABLE_OCR and ocr.is_ocr_worthy(mime_type) and status == "ORIGINAL" and change_type in ["NEW", "UPDATED"] and ocr_calls_this_run < OCR_BUDGET_PER_RUN:
                try:
                    ocr_data, effective_mime = ocr.extract_structured_data(file_id, mime_type)
                    if ocr_data:
                        ocr_calls_this_run += 1
                        rec.ocr_doc_type = ocr_data.get("doc_type", "")
                        rec.ocr_amount = str(ocr_data.get("amount", "") or "")
                        rec.ocr_date = ocr_data.get("date", "")
                        rec.ocr_vendor = ocr_data.get("vendor", "")
                        rec.ocr_summary = ocr_data.get("summary", "")
                        rec.ocr_full_text = ocr_data.get("full_text", "")
                        rec.effective_mime_type = effective_mime
                        rec.ocr_people = ocr_data.get("people_mentioned", [])
                        rec.ocr_organizations = ocr_data.get("organizations_mentioned", [])
                        rec.ocr_sensitivity = ocr_data.get("sensitivity", "low")
                        rec.ocr_is_readable = ocr_data.get("is_readable", True)
                        rec.ocr_language = ocr_data.get("language", "")
                        rec.ocr_currency = ocr_data.get("currency", "")
                        rec.ocr_reference_number = ocr_data.get("reference_number", "")
                    else:
                        errors += 1
                        state.log_error("PASS_2", file_id, rec.name, "OCRError", "Fehler bei der OCR-Extraktion (Kein Resultat)")
                except Exception as e:
                    errors += 1
                    state.log_error("PASS_2", file_id, rec.name, "OCRError", f"Fehler bei der OCR-Extraktion: {str(e)}")

            # Pfad B: Statusereignisse ohne OCR
            elif change_type in ["DELETED", "TRASHED", "REMOVED_OR_NO_ACCESS", "MOVED_OUT_OF_SCOPE",
                                  "MOVED", "RENAMED", "UNCHANGED_CONTENT_METADATA_ONLY"] \
                    or status in ("UNCHANGED_CONTENT", "MOVED_OUT_OF_SCOPE"):
                # Kein OCR, wir signalisieren dem nachgelagerten System nur die Bestandsänderung
                rec.notes = "event_only_no_content_processing"

            records_to_index.append(rec)
            processed += 1

    if not records_to_index:
        state.set_val("current_phase", "PASS2_DONE")
        state.set_val("ready_for_pass2_run_id", "")
        state.flush_state()
        state.log_run("PASS_2", "NO_FILES", 0, errors)
        return

    date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{date_str}_{PROJECT_SLUG}_delta.jsonl"

    try:
        with open(filename, "w", encoding="utf-8") as f:
            for r in records_to_index:
                j_dict = {
                    "run_utc": r.run_utc,
                    "run_id": r.run_id,
                    "path": r.path_display,
                    "name": r.name,
                    "file_id": r.file_id,
                    "mime_type": r.mime_type,
                    "effective_mime_type": r.effective_mime_type,
                    "size_bytes": r.size_bytes,
                    "md5": r.md5,
                    "sha256": r.sha256,
                    "status": r.status,
                    "change_type": r.change_type,
                    "duplicate_of": r.duplicate_of,
                    "archive_result": r.archive_result,
                    "suggested_name": r.suggested_name,
                    "current_parent_id": r.current_parent_id,
                    "current_path": r.current_path,
                    "target_parent_id": r.target_parent_id,
                    "target_path": r.target_path,
                    "folder_rule": r.folder_rule,
                    "folder_rule_reason": r.folder_rule_reason,
                    "sort_mode": r.sort_mode,
                    "move_result": r.move_result,
                    "ocr": {
                        "doc_type": r.ocr_doc_type,
                        "amount": r.ocr_amount,
                        "date": r.ocr_date,
                        "vendor": r.ocr_vendor,
                        "summary": r.ocr_summary,
                        "full_text": r.ocr_full_text
                    } if r.notes != "event_only_no_content_processing" else None,
                    "web_link": r.web_link,
                    "notes": r.notes
                }
                f.write(json.dumps(j_dict, ensure_ascii=False) + "\n")

        media = MediaFileUpload(filename, mimetype="application/x-ndjson")
        params = {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

        def _upload_delta():
            return drive_service.files().create(
                body={"name": filename, "parents": [INDEX_FOLDER_ID]},
                media_body=media,
                fields="id",
                **params
            ).execute()
        drive_mgr.execute_with_backoff(_upload_delta)

        BRAIN_INDEX_ROOT.mkdir(parents=True, exist_ok=True)
        runtime = PersonalBrainRuntime(project_id=PROJECT_SLUG, out_root=BRAIN_INDEX_ROOT)
        runtime.process_sources(
            _build_personal_brain_sources(records_to_index, drive_service, ENABLE_SHARED_DRIVES),
            exclusions
        )

        state.set_val("current_phase", "PASS2_DONE")
        # Clear coordination key indicating successful processing
        state.set_val("ready_for_pass2_run_id", "")
        state.flush_state()
        state.log_run("PASS_2", "SUCCESS", processed, errors)

    except Exception as e:
        state.set_val("current_phase", "PASS2_FAILED")
        state.flush_state()
        state.log_error("PASS_2", "SYSTEM", "ExportJSONL", "Fatal", str(e))
        state.log_run("PASS_2", "FAILED", processed, errors + 1)
        raise e
    finally:
        if os.path.exists(filename):
            os.remove(filename)

if __name__ == "__main__":
    run_pass2()
