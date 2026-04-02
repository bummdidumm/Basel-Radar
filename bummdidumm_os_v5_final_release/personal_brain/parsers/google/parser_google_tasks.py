from __future__ import annotations

from ..base import BaseParser


class GoogleTasksParser(BaseParser):
    parser_name = "parser_google_tasks"
    parser_version = "1.0.0"
    source_system = "google"
    source_service = "tasks"
    source_app = "google-tasks"
    source_kind = "export"
    source_format = "tasks"
    default_record_type = "task_event"
    default_entity_type = "app"
    match_tokens = ('tasks', 'task')

