import os
import io
import json
import tempfile
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any, Tuple, Set

import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaFileUpload
from google import genai
from pydantic import BaseModel, Field

# ==========================================
# CONFIGURATION & ENVIRONMENT
# ==========================================

TARGET_FOLDER_ID = os.environ.get("TARGET_FOLDER_ID")
ARCHIVE_FOLDER_ID = os.environ.get("ARCHIVE_FOLDER_ID")
INDEX_FOLDER_ID = os.environ.get("INDEX_FOLDER_ID")
CONTROL_SHEET_ID = os.environ.get("CONTROL_SHEET_ID")
PROJECT_SLUG = os.environ.get("PROJECT_SLUG", "bummdidumm")

# Policies
SKIP_OVER_MB = int(os.environ.get("SKIP_OVER_MB", "500"))
ENABLE_OCR = os.environ.get("ENABLE_OCR", "true").lower() == "true"
ENABLE_ARCHIVE = os.environ.get("ENABLE_ARCHIVE", "true").lower() == "true"
ENABLE_SHARED_DRIVES = os.environ.get("ENABLE_SHARED_DRIVES", "true").lower() == "true"

FOLDER_MIME = "application/vnd.google-apps.folder"

# ==========================================
# PYDANTIC SCHEMA FOR GEMINI OCR
# ==========================================

class ExtractedDocument(BaseModel):
    doc_type: str = Field(description="Art des Dokuments (z.B. Rechnung, Brief, Foto, Vertrag, Sonstiges)")
    amount: Optional[float] = Field(description="Ein erkannter Rechnungs- oder Gesamtbetrag, falls vorhanden")
    date: Optional[str] = Field(description="Das Beleg- oder Erstelldatum im ISO Format YYYY-MM-DD")
    vendor: Optional[str] = Field(description="Der Name des Absenders, Händlers oder Ausstellers")
    summary: str = Field(description="Eine kurze, prägnante Zusammenfassung des Inhalts (1-3 Sätze)")
    full_text: str = Field(description="Der vollständige extrahierte Text aus dem Dokument")

# ==========================================
# STATE MANAGER (GOOGLE SHEETS)
# ==========================================

class StateTracker:
    def __init__(self, sheets_service, spreadsheet_id: str):
        self.sheets = sheets_service
        self.spreadsheet_id = spreadsheet_id

        # Tabs
        self.tab_state = "State"
        self.tab_hash = "Hash_Index"
        self.tab_report = "Dedupe_Report"
        self.tab_dup = "Duplicate_Groups"
        self.tab_error = "Error_Report"
        self.tab_log = "Run_Log"

        self.run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        self._known_hashes = None
        self._known_file_ids = None # Cache for file_id -> sha256 to detect UPDATED vs NEW

    def _get_cell(self, tab: str, cell: str) -> Optional[str]:
        try:
            res = self.sheets.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id, range=f"{tab}!{cell}"
            ).execute()
            values = res.get("values", [])
            return values[0][0] if values and values[0] else None
        except Exception:
            return None

    def _set_cell(self, tab: str, cell: str, value: str):
        self.sheets.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{tab}!{cell}",
            valueInputOption="RAW",
            body={"values": [[value]]}
        ).execute()

    def get_run_state(self) -> dict:
        return {
            "start_token": self._get_cell(self.tab_state, "B1"),
            "in_progress_token": self._get_cell(self.tab_state, "B2"),
            "phase": self._get_cell(self.tab_state, "B3") or "IDLE"
        }

    def save_run_state(self, start_token: str = None, in_progress_token: str = None, phase: str = None):
        if start_token is not None:
            self._set_cell(self.tab_state, "B1", start_token)
        if in_progress_token is not None:
            self._set_cell(self.tab_state, "B2", in_progress_token)
        if phase is not None:
            self._set_cell(self.tab_state, "B3", phase)

    def load_known_hashes(self) -> Dict[str, str]:
        """Returns dict: {sha256: original_id}."""
        if self._known_hashes is not None:
            return self._known_hashes

        self._known_hashes = {}
        self._known_file_ids = {}
        try:
            res = self.sheets.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id, range=f"{self.tab_hash}!A:B"
            ).execute()
            for row in res.get("values", []):
                if len(row) >= 2 and row[0] != "SHA256":
                    sha = row[0]
                    fid = row[1]
                    self._known_hashes[sha] = fid
                    self._known_file_ids[fid] = sha
        except Exception as e:
            self.log_error("SYSTEM", "LoadHashes", f"Failed to load hashes: {e}")

        return self._known_hashes

    def is_file_known(self, file_id: str) -> bool:
        """Returns True if the file_id has been seen before (useful to detect updates vs new files)"""
        if self._known_file_ids is None:
            self.load_known_hashes()
        return file_id in self._known_file_ids

    def append_hashes(self, hashes: Dict[str, str]):
        if not hashes: return
        rows = [[sha, fid] for sha, fid in hashes.items()]
        self.sheets.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=f"{self.tab_hash}!A:B",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ).execute()
        if self._known_hashes is not None:
            self._known_hashes.update(hashes)
            for sha, fid in hashes.items():
                self._known_file_ids[fid] = sha

    def log_run(self, status: str, files_processed: int, errors: int):
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.sheets.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=f"{self.tab_log}!A:E",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": [[timestamp, self.run_id, status, files_processed, errors]]}
        ).execute()

    def log_error(self, file_id: str, context: str, message: str):
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        print(f"ERROR [{context}] {file_id}: {message}")
        self.sheets.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=f"{self.tab_error}!A:E",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": [[timestamp, self.run_id, file_id, context, str(message)[:500]]]}
        ).execute()

    def append_report_rows(self, rows: List[List[Any]]):
        if not rows: return
        self.sheets.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=f"{self.tab_report}!A:J",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ).execute()

    def append_duplicate_group(self, original_id: str, duplicate_id: str, sha: str, name: str):
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        row = [sha, original_id, duplicate_id, name, timestamp]
        self.sheets.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id, range=f"{self.tab_dup}!A:E",
            valueInputOption="RAW", insertDataOption="INSERT_ROWS",
            body={"values": [row]}
        ).execute()

# ==========================================
# SHARED PARAMS HELPERS
# ==========================================

def get_base_params() -> dict:
    """Safe for methods like .get(), .get_media(), .update() which ONLY support 'supportsAllDrives'"""
    return {"supportsAllDrives": True} if ENABLE_SHARED_DRIVES else {}

def get_list_params() -> dict:
    """Used for .list() and .changes().list() which ALSO support 'includeItemsFromAllDrives'"""
    params = {}
    if ENABLE_SHARED_DRIVES:
        params["includeItemsFromAllDrives"] = True
        params["supportsAllDrives"] = True
    return params

# ==========================================
# DRIVE SCANNER (DELTA & CACHING)
# ==========================================

class DriveScanner:
    def __init__(self, drive_service):
        self.drive = drive_service
        self.ancestor_cache = {TARGET_FOLDER_ID: True}

    def is_in_target_folder(self, file_id: str, parents: List[str]) -> bool:
        if not parents: return False
        if TARGET_FOLDER_ID in parents: return True

        for p in parents:
            if p in self.ancestor_cache:
                if self.ancestor_cache[p]: return True
                continue

            try:
                folder_meta = self.drive.files().get(
                    fileId=p, fields="id,parents", **get_base_params()
                ).execute()
                grandparents = folder_meta.get("parents", [])
                result = self.is_in_target_folder(p, grandparents)
                self.ancestor_cache[p] = result
                if result: return True
            except Exception:
                self.ancestor_cache[p] = False

        return False

    def get_initial_token(self) -> str:
        params = get_base_params()
        if ENABLE_SHARED_DRIVES: params["driveId"] = None
        res = self.drive.changes().getStartPageToken(**params).execute()
        return res.get("startPageToken")

    def walk_recursive(self, folder_id: str) -> List[Dict]:
        """Führt einen rekursiven Scan für den allerersten Lauf durch."""
        records = []
        page_token = None

        while True:
            params = get_list_params()
            if ENABLE_SHARED_DRIVES:
                params["corpora"] = "allDrives"

            resp = self.drive.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                pageSize=1000,
                pageToken=page_token,
                fields="nextPageToken, files(id,name,mimeType,size,md5Checksum,parents,createdTime,modifiedTime)",
                **params
            ).execute()

            children = resp.get("files", [])
            for item in children:
                records.append(item)
                if item["mimeType"] == FOLDER_MIME:
                    records.extend(self.walk_recursive(item["id"]))

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return records

    def fetch_delta_chunk(self, page_token: str) -> Tuple[List[Dict], Optional[str], Optional[str]]:
        params = get_list_params()
        params["pageToken"] = page_token
        params["spaces"] = "drive"
        params["fields"] = "nextPageToken, newStartPageToken, changes(fileId, removed, file(id,name,mimeType,size,md5Checksum,parents,createdTime,modifiedTime))"

        res = self.drive.changes().list(**params).execute()

        changes = []
        for change in res.get("changes", []):
            if change.get("removed"): continue
            f = change.get("file")
            if f and f.get("parents"):
                if self.is_in_target_folder(f["id"], f["parents"]):
                    changes.append(f)

        return changes, res.get("nextPageToken"), res.get("newStartPageToken")

    def calculate_sha256(self, file_id: str, mime_type: str) -> Tuple[Optional[str], str]:
        """Returns (SHA256, ExportSource)"""
        is_native = mime_type.startswith("application/vnd.google-apps")
        export_source = "Native Drive" if is_native else "Binary File"

        try:
            if is_native:
                export_mime = "application/pdf"
                request = self.drive.files().export_media(fileId=file_id, mimeType=export_mime)
                export_source = "Exported as PDF"
            else:
                request = self.drive.files().get_media(fileId=file_id, **get_base_params())

            with tempfile.NamedTemporaryFile() as tmp:
                downloader = MediaIoBaseDownload(tmp, request, chunksize=8 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                tmp.flush()
                tmp.seek(0)

                sha = hashlib.sha256()
                while True:
                    chunk = tmp.read(8 * 1024 * 1024)
                    if not chunk: break
                    sha.update(chunk)
                return sha.hexdigest(), export_source
        except Exception as e:
            print(f"Hash error for {file_id}: {e}")
            return None, "Error"

    def archive_duplicate(self, file_id: str, parents: List[str]) -> str:
        if not ENABLE_ARCHIVE: return "DRY_RUN"
        try:
            params = get_base_params()
            self.drive.files().update(
                fileId=file_id,
                addParents=ARCHIVE_FOLDER_ID,
                removeParents=",".join(parents),
                **params
            ).execute()
            return "SUCCESS"
        except Exception as e:
            print(f"Archive failed for {file_id}: {e}")
            return f"FAILED:{str(e)[:50]}"

# ==========================================
# GEMINI PROCESSOR (OCR & EXTRACTION)
# ==========================================

class GeminiProcessor:
    def __init__(self, drive_service):
        self.drive = drive_service
        self.client = genai.Client() if "GEMINI_API_KEY" in os.environ else None

    def _download_for_ocr(self, file_id: str, mime_type: str) -> Tuple[Optional[str], str]:
        """Returns (TempPath, EffectiveMimeType)"""
        is_native = mime_type.startswith("application/vnd.google-apps")
        effective_mime = "application/pdf" if is_native and "document" in mime_type else mime_type

        try:
            if is_native:
                if "document" in mime_type:
                    request = self.drive.files().export_media(fileId=file_id, mimeType="application/pdf")
                else:
                    return None, mime_type
            else:
                request = self.drive.files().get_media(fileId=file_id, **get_base_params())

            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                downloader = MediaIoBaseDownload(tmp, request, chunksize=8 * 1024 * 1024)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                tmp.flush()
                return tmp.name, effective_mime
        except Exception as e:
            print(f"Download for OCR failed: {e}")
            return None, mime_type

    def extract_structured_data(self, file_id: str, mime_type: str, state: StateTracker) -> Tuple[Optional[dict], str]:
        """Returns (ExtractedDataDict, EffectiveMimeType)"""
        if not self.client or not ENABLE_OCR: return None, mime_type
        if not (mime_type.startswith("image/") or mime_type == "application/pdf" or "document" in mime_type):
            return None, mime_type

        tmp_path, effective_mime = self._download_for_ocr(file_id, mime_type)
        if not tmp_path: return None, effective_mime

        gemini_file = None
        try:
            gemini_file = self.client.files.upload(file=tmp_path, mime_type=effective_mime)
            prompt = "Bitte analysiere dieses Dokument und extrahiere die angeforderten strukturierten Daten."

            response = self.client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[gemini_file, prompt],
                config={"response_mime_type": "application/json", "response_schema": ExtractedDocument}
            )

            if response.text:
                return json.loads(response.text), effective_mime

        except Exception as e:
            state.log_error(file_id, "Gemini OCR", str(e))
            return None, effective_mime
        finally:
            os.remove(tmp_path)
            if gemini_file:
                try:
                    self.client.files.delete(name=gemini_file.name)
                except Exception as e:
                    print(f"Warning: Failed to delete Gemini temp file {gemini_file.name}: {e}")
        return None, effective_mime

# ==========================================
# PIPELINE ORCHESTRATOR
# ==========================================

class Pipeline:
    def __init__(self):
        if not all([TARGET_FOLDER_ID, CONTROL_SHEET_ID]):
            raise ValueError("Missing essential env vars: TARGET_FOLDER_ID, CONTROL_SHEET_ID")

        credentials, _ = google.auth.default()
        self.drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)

        self.state = StateTracker(self.sheets, CONTROL_SHEET_ID)
        self.scanner = DriveScanner(self.drive)
        self.ocr = GeminiProcessor(self.drive)
        self.errors = 0
        self.processed_files = 0

    def export_jsonl(self, records: List[Dict], phase: str):
        if not records or not INDEX_FOLDER_ID: return

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"index_{PROJECT_SLUG}_{phase}_{date_str}.jsonl"

        try:
            with open(filename, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

            media = MediaFileUpload(filename, mimetype="application/x-ndjson")

            self.drive.files().create(
                body={"name": filename, "parents": [INDEX_FOLDER_ID]},
                media_body=media,
                fields="id",
                **get_base_params()
            ).execute()
        except Exception as e:
            self.state.log_error("SYSTEM", "ExportJSONL", str(e))
        finally:
            if os.path.exists(filename):
                os.remove(filename)

    def determine_change_type(self, file_id: str, known: bool, f: dict) -> str:
        """Klassifiziert den Delta Status: NEW, UPDATED, RENAMED"""
        if not known: return "NEW"

        # Simplistic heuristic for renamed vs updated if file is known
        # In a strict implementation, we would compare the cached name vs current name
        # For now, if modified time is recent, it's UPDATED.
        return "UPDATED"

    def suggest_rename(self, name: str, created_time: Optional[str]) -> str:
        """Rename-Safe-Mode: We only suggest the name. We don't apply it."""
        if not created_time: return name
        iso_date = created_time[:10]
        if name.startswith(f"{iso_date}_"): return name
        safe = name.replace(":", "-").strip()
        return f"{iso_date}_{PROJECT_SLUG}_{safe}"

    def run(self):
        print(f"Starting V5 Pipeline (Run: {self.state.run_id})...")
        run_state = self.state.get_run_state()

        start_token = run_state["start_token"]
        in_progress_token = run_state["in_progress_token"]

        all_jsonl_records = []
        new_start_page_token = None

        try:
            if not start_token:
                print("No Initial Token found. Executing Initial Full-Scan...")
                self.state.save_run_state(phase="INITIAL_SCAN")

                # Fetch all files recursively
                all_items = self.scanner.walk_recursive(TARGET_FOLDER_ID)
                files = [f for f in all_items if f.get("mimeType") != FOLDER_MIME]

                # We won't loop through tokens here, just process the big batch
                new_start_page_token = self.scanner.get_initial_token()
                self._process_file_batch(files, all_jsonl_records, is_initial=True)

            else:
                active_token = in_progress_token if in_progress_token else start_token
                if active_token != in_progress_token:
                    self.state.save_run_state(in_progress_token=active_token, phase="DELTA_SCAN")

                while active_token:
                    print(f"Fetching delta chunk: {active_token}")
                    changes, next_page_token, new_start_token = self.scanner.fetch_delta_chunk(active_token)

                    files = [f for f in changes if f.get("mimeType") != FOLDER_MIME]
                    self._process_file_batch(files, all_jsonl_records, is_initial=False)

                    if next_page_token:
                        active_token = next_page_token
                        self.state.save_run_state(in_progress_token=active_token)
                    else:
                        new_start_page_token = new_start_token
                        break

            # Wrap up
            phase_name = "init" if not start_token else "delta"
            self.export_jsonl(all_jsonl_records, phase_name)

            # Idempotence: Only on full success do we set the new start token for the next job
            if new_start_page_token:
                self.state.save_run_state(
                    start_token=new_start_page_token,
                    in_progress_token="", # Clear in-progress
                    phase="IDLE"
                )

            self.state.log_run("SUCCESS", self.processed_files, self.errors)
            print("Pipeline completed successfully.")

        except Exception as e:
            self.state.log_error("SYSTEM", "Pipeline Fatal", str(e))
            self.state.log_run("FAILED", self.processed_files, self.errors + 1)
            print(f"Pipeline crashed: {e}")

    def _process_file_batch(self, files: List[Dict], all_jsonl_records: List[Dict], is_initial: bool):
        known_hashes = self.state.load_known_hashes()
        new_hashes = {}
        report_rows = []

        for f in files:
            file_id = f["id"]
            mime = f.get("mimeType", "")
            size = int(f.get("size", 0))
            name = f["name"]

            # Rename Safe Mode Suggestion
            suggested_name = self.suggest_rename(name, f.get("createdTime"))

            # Change classification
            is_file_known = self.state.is_file_known(file_id)
            change_type = "NEW" if is_initial else self.determine_change_type(file_id, is_file_known, f)

            if size > SKIP_OVER_MB * 1024 * 1024:
                # Ensure we append exactly 10 columns for skipped items as well to align the Sheet
                report_rows.append([file_id, name, mime, size, "SKIPPED_SIZE", "", "", change_type, suggested_name, ""])
                continue

            sha, export_source = self.scanner.calculate_sha256(file_id, mime)
            if not sha:
                self.errors += 1
                continue

            # Pass 1: Deduplication Logic (SHA-256 is the anchor)
            is_duplicate = False
            original_id = None

            if sha in known_hashes:
                is_duplicate = True
                original_id = known_hashes[sha]
            elif sha in new_hashes:
                is_duplicate = True
                original_id = new_hashes[sha]
            else:
                new_hashes[sha] = file_id

            status = "ORIGINAL"
            archive_result = "N/A"
            if is_duplicate:
                archive_result = self.scanner.archive_duplicate(file_id, f.get("parents", []))
                status = f"DUPLICATE_OF:{original_id}"
                self.state.append_duplicate_group(original_id, file_id, sha, name)

            # Pass 2: Heavy OCR & Indexing (Only for Originals)
            ocr_data = None
            effective_mime = mime
            if not is_duplicate and ENABLE_OCR:
                ocr_data, effective_mime = self.ocr.extract_structured_data(file_id, mime, self.state)

            # Build Records (10 columns)
            report_rows.append([
                file_id, name, mime, size, sha, status,
                ocr_data.get("doc_type") if ocr_data else "",
                change_type, suggested_name, archive_result
            ])

            record = {
                "file_id": file_id,
                "name": name,
                "suggested_name": suggested_name,
                "mime_type": mime,
                "effective_mime_type": effective_mime,
                "export_source": export_source,
                "sha256": sha,
                "status": status,
                "duplicate_of": original_id if is_duplicate else None,
                "archive_result": archive_result,
                "change_type": change_type,
                "run_id": self.state.run_id,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            }
            if ocr_data:
                record.update(ocr_data)

            all_jsonl_records.append(record)
            self.processed_files += 1

        self.state.append_hashes(new_hashes)
        self.state.append_report_rows(report_rows)

if __name__ == "__main__":
    Pipeline().run()