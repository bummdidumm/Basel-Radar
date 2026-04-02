from __future__ import annotations

from ..base import BaseParser

class GoogleTasksParser(BaseParser):
    parser_name = "parser_google_tasks"
    parser_version = "2.0.0"
    source_system = "google"
    source_service = "tasks"
    source_app = "google-tasks"
    source_kind = "export"
    source_format = "json"
    default_record_type = "task"
    match_tokens = ("tasks", "google")

    def can_handle(self, source_meta: dict, preview: dict) -> bool:
        if "tasks" in source_meta.get("original_filename", "").lower():
            return True
        return False

    def parse_to_records(self, source_meta: dict, content: dict) -> list[dict]:
        records = []
        tasks = content.get("items", [])
        if not tasks:
            return super().parse_to_records(source_meta, content)

        for task in tasks:
            ts = task.get("updated", "") or task.get("due", "")
            records.append({
                "record_type": "task",
                "subtype": "todo",
                "event_time_start": ts,
                "event_date": ts[:10] if ts else "",
                "title": task.get("title", "Untitled Task"),
                "summary": task.get("notes", ""),
                "external_id": task.get("id", ""),
                "status": task.get("status", "needsAction")
            })
        return records
