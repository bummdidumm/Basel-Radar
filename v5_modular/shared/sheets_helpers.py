from typing import List, Optional, Any

class SheetManager:
    """Core Google Sheets operations."""
    def __init__(self, sheets_service, spreadsheet_id: str):
        self.sheets = sheets_service
        self.spreadsheet_id = spreadsheet_id

        self.headers = {
            "State": ["key", "value"],
            "Hash_Index": ["sha256", "file_id", "name", "path", "updated_at", "size_bytes", "md5", "effective_mime_type"],
            "Dedupe_Report": ["run_utc", "run_id", "path", "name", "file_id", "mime_type", "effective_mime_type", "size_bytes", "md5", "sha256", "status", "change_type", "duplicate_of", "archive_result", "suggested_name", "web_link", "notes"],
            "Duplicate_Groups": ["sha256", "original_file_id", "duplicate_file_ids", "count"],
            "Error_Report": ["run_utc", "run_id", "phase", "file_id", "path", "error_type", "error_message"],
            "Run_Log": ["run_utc", "run_id", "phase", "status", "files_processed", "errors"]
        }

    def initialize_headers(self):
        """Ensures all tabs have their correct headers."""
        for tab_name, header_row in self.headers.items():
            try:
                # Check if header exists
                res = self.sheets.spreadsheets().values().get(
                    spreadsheetId=self.spreadsheet_id, range=f"{tab_name}!A1"
                ).execute()

                if not res.get("values"):
                    self._write_header(tab_name, header_row)
            except Exception as e:
                # If tab doesn't exist, we skip or could use batchUpdate to create it.
                # Assuming user created tabs manually based on instructions.
                print(f"Warning: Could not read/write {tab_name} header: {e}")

    def _write_header(self, tab: str, header: List[str]):
        self.sheets.spreadsheets().values().update(
            spreadsheetId=self.spreadsheet_id,
            range=f"{tab}!A1",
            valueInputOption="RAW",
            body={"values": [header]}
        ).execute()

    def append_rows(self, tab: str, rows: List[List[Any]]):
        if not rows: return
        self.sheets.spreadsheets().values().append(
            spreadsheetId=self.spreadsheet_id,
            range=f"{tab}!A:Z",
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": rows}
        ).execute()

    def read_all_rows(self, tab: str, columns: str = "A:Z") -> List[List[str]]:
        try:
            res = self.sheets.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id, range=f"{tab}!{columns}"
            ).execute()
            return res.get("values", [])
        except Exception:
            return []
