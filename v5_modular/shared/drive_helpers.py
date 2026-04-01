import os
from typing import List, Dict, Tuple, Optional
from googleapiclient.discovery import build

class DriveManager:
    """Encapsulates Google Drive API interactions, caching, and filtering."""
    def __init__(self, drive_service, target_folder_id: str, enable_shared_drives: bool = True):
        self.drive = drive_service
        self.target_folder_id = target_folder_id
        self.enable_shared_drives = enable_shared_drives
        self.ancestor_cache = {target_folder_id: True}

    def _base_params(self) -> dict:
        return {"supportsAllDrives": True} if self.enable_shared_drives else {}

    def _list_params(self) -> dict:
        params = {}
        if self.enable_shared_drives:
            params["includeItemsFromAllDrives"] = True
            params["supportsAllDrives"] = True
        return params

    def is_in_target_folder(self, file_id: str, parents: List[str]) -> bool:
        if not parents: return False
        if self.target_folder_id in parents: return True

        for p in parents:
            if p in self.ancestor_cache:
                if self.ancestor_cache[p]: return True
                continue

            try:
                folder_meta = self.drive.files().get(
                    fileId=p, fields="id,parents", **self._base_params()
                ).execute()
                grandparents = folder_meta.get("parents", [])
                result = self.is_in_target_folder(p, grandparents)
                self.ancestor_cache[p] = result
                if result: return True
            except Exception:
                self.ancestor_cache[p] = False

        return False

    def get_initial_token(self) -> str:
        params = self._base_params()
        if self.enable_shared_drives: params["driveId"] = None
        res = self.drive.changes().getStartPageToken(**params).execute()
        return res.get("startPageToken")

    def walk_recursive(self, folder_id: str) -> List[Dict]:
        """Führt einen rekursiven Scan für den allerersten Lauf durch."""
        records = []
        page_token = None

        while True:
            params = self._list_params()
            if self.enable_shared_drives:
                params["corpora"] = "allDrives"

            resp = self.drive.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                pageSize=1000,
                pageToken=page_token,
                fields="nextPageToken, files(id,name,mimeType,size,md5Checksum,parents,createdTime,modifiedTime,trashed)",
                **params
            ).execute()

            children = resp.get("files", [])
            for item in children:
                records.append(item)
                if item["mimeType"] == "application/vnd.google-apps.folder":
                    records.extend(self.walk_recursive(item["id"]))

            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return records

    def fetch_delta_chunk(self, page_token: str) -> Tuple[List[Dict], Optional[str], Optional[str]]:
        params = self._list_params()
        params["pageToken"] = page_token
        params["spaces"] = "drive"
        # Hole extra Metadaten für echtes Change-Type Tracking
        params["fields"] = "nextPageToken, newStartPageToken, changes(fileId, removed, file(id,name,mimeType,size,md5Checksum,parents,createdTime,modifiedTime,trashed))"

        res = self.drive.changes().list(**params).execute()

        changes = []
        for change in res.get("changes", []):
            f = change.get("file")
            removed = change.get("removed", False)

            # Falls Datei hart gelöscht oder Rechte entzogen wurden (kein file-Objekt vorhanden)
            if removed or not f:
                changes.append({
                    "id": change["fileId"],
                    "removed": True,
                    "trashed": False,
                    "name": "UNKNOWN_REMOVED",
                    "mimeType": "",
                    "parents": []
                })
                continue

            # Wenn sie noch existiert (trashed oder aktiv) prüfen wir den Zielordner
            # (bzw. bei Trashed wissen wir die parents nicht immer sicher, wir nehmen sie mit,
            # wenn wir sie in unserem State als bekannt finden, können wir sie später als TRASHED markieren).
            if f.get("parents") and self.is_in_target_folder(f["id"], f["parents"]):
                f["removed"] = False
                changes.append(f)
            elif f.get("trashed"):
                 f["removed"] = False
                 changes.append(f) # Trashed items might not show up in target folder tree easily, but we catch them here.

        return changes, res.get("nextPageToken"), res.get("newStartPageToken")

    def archive_duplicate(self, file_id: str, parents: List[str], archive_folder_id: str) -> str:
        if not archive_folder_id: return "DRY_RUN: NO_ARCHIVE_ID"
        try:
            params = self._base_params()
            self.drive.files().update(
                fileId=file_id,
                addParents=archive_folder_id,
                removeParents=",".join(parents),
                **params
            ).execute()
            return "SUCCESS"
        except Exception as e:
            return f"FAILED:{str(e)[:50]}"
