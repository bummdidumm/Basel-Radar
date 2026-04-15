from typing import List, Dict, Tuple, Optional
from datetime import datetime, timezone
from shared.log import get_logger as _get_logger
_log = _get_logger("drive", phase="SHARED")

class DriveManager:
    """Encapsulates Google Drive API interactions, caching, and filtering."""
    def __init__(self, drive_service, target_folder_id: str, enable_shared_drives: bool = True):
        self.drive = drive_service
        self.target_folder_id = target_folder_id
        self.enable_shared_drives = enable_shared_drives
        self.ancestor_cache = {target_folder_id: True}

    def execute_with_backoff(self, request_callable):
        import time
        from googleapiclient.errors import HttpError
        for attempt in range(5):
            try:
                return request_callable()
            except HttpError as e:
                if e.resp.status in (429, 500, 503):
                    sleep_time = (2 ** attempt) + 1
                    _log.warning("Drive API rate limit", extra={"status": e.resp.status, "sleep_sec": sleep_time, "attempt": attempt + 1})
                    time.sleep(sleep_time)
                else:
                    raise
        raise Exception("Drive API max retries reached.")

    def _base_params(self) -> dict:
        return {"supportsAllDrives": True} if self.enable_shared_drives else {}

    def _list_params(self) -> dict:
        params = {}
        if self.enable_shared_drives:
            params["includeItemsFromAllDrives"] = True
            params["supportsAllDrives"] = True
        return params

    def is_in_target_folder(self, file_id: str, parents: List[str]) -> bool:
        """Return True if any ancestor of *parents* is target_folder_id.

        Iterative BFS over the Drive folder hierarchy — avoids recursion-depth
        limits on deep folder trees (Drive can nest 20+ levels) and handles
        cycles via a visited set.
        """
        if not self.target_folder_id:
            return True
        if not parents:
            return False
        if self.target_folder_id in parents:
            return True

        stack = list(parents)
        visited: set = set()

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)

            if current == self.target_folder_id:
                return True
            if self.ancestor_cache.get(current) is True:
                return True
            if self.ancestor_cache.get(current) is False:
                continue

            try:
                meta = self.drive.files().get(
                    fileId=current, fields="id,parents", **self._base_params()
                ).execute()
                grandparents = meta.get("parents", [])
                if self.target_folder_id in grandparents:
                    self.ancestor_cache[current] = True
                    return True
                for gp in grandparents:
                    if gp not in visited:
                        stack.append(gp)
            except Exception:
                self.ancestor_cache[current] = False

        return False

    def get_initial_token(self) -> str:
        params = self._base_params()
        res = self.drive.changes().getStartPageToken(**params).execute()
        return res.get("startPageToken")

    def get_parent_and_name_path(self, file_id: str, name: str, parents: Optional[List[str]] = None) -> str:
        """
        Returns a descriptive pseudo-path consisting of the first parent ID and the file name.
        Allows for basic visual distinction in logs without executing costly tree-walks.
        """
        if parents and len(parents) > 0:
            return f"{parents[0]}/{name}"
        return name

    def walk_recursive(self, folder_id: str) -> List[Dict]:
        """Deprecated. Use walk_recursive_chunked() instead."""
        raise NotImplementedError(
            "walk_recursive() is deprecated and must not be called. "
            "Use walk_recursive_chunked() for all production code paths."
        )

    def walk_recursive_chunked(self, folder_id: str, state, process_batch_callback, batch_kwargs: dict):
        """Performs initial recursive scan in bounded chunks to prevent timeout endloops."""
        queue = state.get_val("initial_scan_queue")
        if queue:
            queue = queue.split(",")
        else:
            queue = [folder_id]

        active_page_token = state.get_val("initial_scan_page_token") or None

        total_processed = 0

        while queue:
            current = queue.pop(0)
            page_token = active_page_token

            while True:
                params = self._list_params()
                if self.enable_shared_drives:
                    params["corpora"] = "allDrives"

                query = f"'{current}' in parents and trashed = false" if current else "'root' in parents and trashed = false"

                def _do_list():
                    return self.drive.files().list(
                        q=query,
                        pageSize=1000,
                        pageToken=page_token,
                        fields="nextPageToken, files(id,name,mimeType,size,md5Checksum,parents,createdTime,modifiedTime,trashed,webViewLink,description,starred,owners(emailAddress,displayName),lastModifyingUser(emailAddress,displayName),capabilities(canEdit,canShare,canDownload))",
                        **params
                    ).execute()

                resp = self.execute_with_backoff(_do_list)

                children = resp.get("files", [])
                files = []
                for item in children:
                    if item["mimeType"] == "application/vnd.google-apps.folder":
                        queue.append(item["id"])
                    else:
                        files.append(item)

                if files:
                    process_batch_callback(files, **batch_kwargs)
                    total_processed += len(files)

                page_token = resp.get("nextPageToken")

                # Checkpointing
                state.set_val("initial_scan_queue", ",".join(queue))
                state.set_val("initial_scan_page_token", page_token or "")
                if state.get_val("lease_owner_id"):
                    state.set_val("lease_heartbeat_at", datetime.now(timezone.utc).isoformat())
                # We do not strictly need to save the new start token here as it's fetched at the start of walk
                # but if we wanted to, we could. The queue saves the progress anyway.
                state.flush_state()

                if not page_token:
                    break

            active_page_token = None # Reset for next folder

        state.set_val("initial_scan_queue", "")
        state.set_val("initial_scan_page_token", "")
        state.flush_state()
        return total_processed

    def fetch_delta_chunk(self, page_token: str) -> Tuple[List[Dict], Optional[str], Optional[str]]:
        params = self._list_params()
        params["pageToken"] = page_token
        params["spaces"] = "drive"
        params["fields"] = "nextPageToken, newStartPageToken, changes(fileId, removed, file(id,name,mimeType,size,md5Checksum,parents,createdTime,modifiedTime,trashed,webViewLink,description,starred,owners(emailAddress,displayName),lastModifyingUser(emailAddress,displayName),capabilities(canEdit,canShare,canDownload)))"

        def _do_delta_list():
            return self.drive.changes().list(**params).execute()
        res = self.execute_with_backoff(_do_delta_list)

        changes = []
        for change in res.get("changes", []):
            f = change.get("file")
            removed = change.get("removed", False)

            if removed or not f:
                # Distinguish explicit DELETED vs REMOVED_OR_NO_ACCESS
                # According to Drive API, if the resource was permanently deleted, "removed" is true
                # AND there's no "file" object attached, just the fileId.
                is_deleted = False
                if removed and not f:
                    is_deleted = True

                changes.append({
                    "id": change["fileId"],
                    "removed": True,
                    "explicitly_trashed_or_deleted_flag": is_deleted,
                    "trashed": False,
                    "name": "UNKNOWN_REMOVED",
                    "mimeType": "",
                    "parents": []
                })
                continue

            if f.get("parents") and self.is_in_target_folder(f["id"], f["parents"]):
                f["removed"] = False
                changes.append(f)
            elif f.get("trashed"):
                # Nur trashed Files reinnehmen, wenn sie auch wirklich im Target Ordner Baum hängen
                if f.get("parents") and self.is_in_target_folder(f["id"], f["parents"]):
                    f["removed"] = False
                    changes.append(f)

        return changes, res.get("nextPageToken"), res.get("newStartPageToken")

    def archive_duplicate(self, file_id: str, parents: List[str], archive_folder_id: str) -> str:
        if not archive_folder_id:
            return "DRY_RUN: NO_ARCHIVE_ID"
        try:
            params = self._base_params()
            def _do_update():
                return self.drive.files().update(
                    fileId=file_id,
                    addParents=archive_folder_id,
                    removeParents=",".join(parents),
                    **params
                ).execute()
            self.execute_with_backoff(_do_update)
            import time
            time.sleep(0.5)  # Throttle to avoid aggressive 429
            return "SUCCESS"
        except Exception as e:
            return f"FAILED:{str(e)[:50]}"
