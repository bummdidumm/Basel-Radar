from __future__ import annotations

import json
from pathlib import Path
from typing import Any


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

    if path_obj.exists() and path_obj.is_file():
        try:
            if ext == ".json":
                parsed = json.loads(path_obj.read_text(encoding="utf-8"))
                if isinstance(parsed, dict):
                    preview = {k: parsed[k] for k in list(parsed.keys())[:15]}
                    content = parsed
            elif ext in {".html", ".htm", ".txt", ".md"}:
                text = path_obj.read_text(encoding="utf-8", errors="ignore")[:8000]
                text_preview = text[:1000]
                content = {"raw_text": text, "title": path_obj.name, "summary": text[:200]}
        except Exception:
            pass

    is_bundle, is_archive = _detect_bundle(source_path, ext)
    return {
        "preview": preview,
        "text_preview": text_preview[:1000],
        "content": content,
        "is_bundle": is_bundle,
        "is_archive": is_archive,
        "is_export": ("export" in source_path.lower()) or is_bundle,
    }
