from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from .utils import sanitize_path


def _detect_bundle(path: str, ext: str) -> tuple[bool, bool]:
    low = path.lower()
    is_archive = ext in {".zip", ".tar", ".gz"}
    is_bundle = is_archive or "takeout" in low or "export" in low
    return is_bundle, is_archive


def inspect_source(source_path: str, mime: str, ext: str, fallback_text: str = "") -> dict[str, Any]:
    path_obj = Path(source_path)
    preview: dict[str, Any] = {}
    text_preview = fallback_text or ""
    content: dict[str, Any] = {"raw_text": fallback_text}

    is_bundle, is_archive = _detect_bundle(source_path, ext)

    if path_obj.exists() and path_obj.is_file():
        try:
            if is_archive and ext == ".zip" and zipfile.is_zipfile(path_obj):
                with zipfile.ZipFile(path_obj, "r") as z:
                    raw_namelist = z.namelist()
                    # Sanitize filenames in namelist to prevent traversal leaks in metadata
                    namelist = [sanitize_path(n) for n in raw_namelist]
                    content["archive_files"] = namelist[:100]

                    # Try to find an informative file to extract text from
                    target_file = None
                    for name in raw_namelist:
                        low_name = name.lower()
                        if low_name.endswith("index.html") or low_name.endswith("messages.json") or "archive_browser.html" in low_name:
                            target_file = name
                            break
                    if not target_file:
                        # Fallback to the first html or json file
                        for name in raw_namelist:
                            low_name = name.lower()
                            if low_name.endswith(".html") or low_name.endswith(".json"):
                                target_file = name
                                break
                    if target_file:
                        with z.open(target_file) as f:
                            text = f.read(8000).decode("utf-8", errors="ignore")
                            text_preview = text[:1000]
                            content["raw_text"] = text
                            content["title"] = path_obj.name
                            content["summary"] = f"Archive containing {len(namelist)} files."

            elif ext == ".json":
                parsed = json.loads(path_obj.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    preview = {k: parsed[k] for k in list(parsed.keys())[:15]}
                    content = parsed
            elif ext in {".html", ".htm", ".txt", ".md", ".ics", ".csv"}:
                text = path_obj.read_text(encoding="utf-8", errors="ignore")[:8000]
                text_preview = text[:1000]
                content = {"raw_text": text, "title": path_obj.name, "summary": text[:200]}
        except Exception:
            pass
    return {
        "preview": preview,
        "text_preview": text_preview[:1000],
        "content": content,
        "is_bundle": is_bundle,
        "is_archive": is_archive,
        "is_export": ("export" in source_path.lower()) or is_bundle,
    }
