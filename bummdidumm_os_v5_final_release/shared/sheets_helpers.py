import time
from typing import List, Any
from googleapiclient.errors import HttpError
import logging
_log = logging.getLogger("bummdidumm.sheets")

class SheetManager:
    """Provides base interactions with the Google Sheets API."""
    def __init__(self, sheets_service, spreadsheet_id: str):
        self.sheets = sheets_service
        self.spreadsheet_id = spreadsheet_id

        self.headers = {
            "State": ["key", "value"],
            "Hash_Index": ["sha256", "file_id", "name", "parent_ids_sorted", "path_display", "updated_at", "size_bytes", "md5", "effective_mime_type"],
            "Dedupe_Report": ["run_utc", "run_id", "path", "name", "file_id", "mime_type", "effective_mime_type", "size_bytes", "md5", "sha256", "status", "change_type", "duplicate_of", "archive_result", "suggested_name", "web_link", "notes"],
            "Duplicate_Groups": ["sha256", "original_file_id", "duplicate_file_ids", "count"],
            "Error_Report": ["run_utc", "run_id", "phase", "file_id", "path", "error_type", "error_message"],
            "Run_Log": ["run_utc", "run_id", "phase", "status", "files_processed", "errors"],
            "Folder_Registry": ["folder_key", "folder_name", "folder_id", "parent_folder_id", "full_path"],
            "Sorting_Suggestions": ["run_id", "file_id", "name", "mime_type", "current_location", "current_parent_id", "folder_rule", "folder_rule_reason", "suggested_target_folder", "suggested_target_folder_id", "target_path", "action_mode", "move_result"],
            "Knowledge_Exclusions": ["file_id", "path_display", "status", "reason"]
        }

        self.DEDUPE_COL = {col: i for i, col in enumerate(self.headers["Dedupe_Report"])}
        self.SORT_COL = {col: i for i, col in enumerate(self.headers["Sorting_Suggestions"])}

    def _execute_with_backoff(self, request_op):
        """Führt eine Request-Methode der Sheets-API aus und wendet Exponential Backoff bei 429 Fehlern an."""
        max_retries = 5
        for attempt in range(max_retries):
            try:
                return request_op.execute()
            except HttpError as e:
                # 429 ist Quota Exceeded/Rate Limit
                if e.resp.status == 429 or (
                    e.resp.status == 403 and
                    any(d.get("reason", "") in ("rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded")
                        for d in (e.error_details or []))
                ):
                    sleep_time = (2 ** attempt) + 1  # 1, 3, 5, 9, 17 Sekunden
                    _log.warning("Sheets API rate limit", extra={"sleep_sec": sleep_time, "attempt": attempt + 1, "max": max_retries})
                    time.sleep(sleep_time)
                else:
                    raise
        raise Exception("Maximale Retry-Anzahl für Sheets API erreicht.")

    def initialize_headers(self):
        """Ensures all required tabs exist with correct headers."""
        try:
            res = self._execute_with_backoff(self.sheets.spreadsheets().get(spreadsheetId=self.spreadsheet_id))
            existing_tabs = [sheet.get("properties", {}).get("title") for sheet in res.get("sheets", [])]

            requests = []
            for tab_name, header_row in self.headers.items():
                if tab_name not in existing_tabs:
                    requests.append({"addSheet": {"properties": {"title": tab_name}}})

            if requests:
                self._execute_with_backoff(self.sheets.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id, body={"requests": requests}
                ))

            # Write headers
            for tab_name, header_row in self.headers.items():
                header_check = self._execute_with_backoff(self.sheets.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id, range=f"{tab_name}!A1"
                ))
                existing_values = header_check.get("values", [[]])
                existing_first = existing_values[0][0] if existing_values and existing_values[0] else ""
                if existing_first != header_row[0]:
                    self._execute_with_backoff(self.sheets.spreadsheets().values().update(
                        spreadsheetId=self.spreadsheet_id,
                        range=f"{tab_name}!A1",
                        valueInputOption="RAW",
                        body={"values": [header_row]}
                    ))
        except Exception as e:
            _log.error("Sheets init fehlgeschlagen", extra={"error": str(e)})

    def append_rows(self, tab: str, rows: List[List[Any]]):
        if not rows:
            return
        self._execute_with_backoff(self.sheets.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{tab}!A:Z",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ))

    def read_all_rows(self, tab: str, columns: str = "A:Z") -> List[List[str]]:
        """Liest alle Zeilen (kann RAM-lastig bei 100k+ Einträgen sein)."""
        try:
            res = self._execute_with_backoff(self.sheets.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id, range=f"{tab}!{columns}"
            ))
            return res.get("values", [])
        except Exception as e:
            _log.warning("read_all_rows fehlgeschlagen", extra={"tab": tab, "error": str(e)})
            return []

    def read_rows_chunked(self, tab: str, chunk_size: int = 1000):
        """Liest Rows chunkweise mit Yield aus, um RAM-Crashes bei Pass 2 zu vermeiden."""
        start_row = 1

        while True:
            # We assume A:Z for safety and simplicity across wide sheets.
            range_str = f"{tab}!A{start_row}:Z{start_row + chunk_size - 1}"
            try:
                res = self._execute_with_backoff(self.sheets.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id, range=range_str
                ))
                values = res.get("values", [])

                if not values:
                    break

                yield values

                # If we received fewer rows than asked for, it's the end of the sheet
                if len(values) < chunk_size:
                    break

                start_row += chunk_size
            except Exception as e:
                _log.error("Chunked read fehlgeschlagen", extra={"range": range_str, "error": str(e)})
                break

    def read_rows_chunked_with_row_numbers(self, tab: str, chunk_size: int = 1000):
        """Yieldt (sheet_row_number, row_values) chunkweise für präzise Updates ohne rows.index()."""
        start_row = 1

        while True:
            range_str = f"{tab}!A{start_row}:Z{start_row + chunk_size - 1}"
            try:
                res = self._execute_with_backoff(self.sheets.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id, range=range_str
                ))
                values = res.get("values", [])
                if not values:
                    break

                for offset, row in enumerate(values):
                    yield (start_row + offset, row)

                if len(values) < chunk_size:
                    break
                start_row += chunk_size
            except Exception as e:
                _log.error("Chunked read with row numbers fehlgeschlagen", extra={"range": range_str, "error": str(e)})
                break
