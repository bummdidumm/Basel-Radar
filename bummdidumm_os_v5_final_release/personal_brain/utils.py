from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def sanitize_path(path: str) -> str:
    """Neutralize path traversal (..) and absolute paths."""
    if not path:
        return ""
    # Replace backslashes with forward slashes first to handle potential Windows paths
    path = path.replace("\\", "/")
    # Normalize path by resolving .. and removing leading slashes/drives
    # We prefix with / to ensure it's treated as absolute for normalization,
    # then strip it back to get a clean relative path.
    normalized = os.path.normpath("/" + path)
    return normalized.lstrip("/")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def semantic_hash(payload: dict) -> str:
    stable = "|".join(f"{k}={payload.get(k, '')}" for k in sorted(payload))
    return sha256_text(stable)


def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def norm_filename(name: str) -> str:
    p = Path(name)
    return f"{slugify(p.stem)}{p.suffix.lower()}"

PARSEABLE_MIME_MAP: dict[str, str] = {
    ".json": "application/json", ".html": "text/html", ".htm": "text/html",
    ".txt": "text/plain", ".md": "text/markdown", ".csv": "text/csv", ".ics": "text/calendar"
}
PARSEABLE_EXTS: frozenset[str] = frozenset(PARSEABLE_MIME_MAP.keys())
PARSEABLE_MIMES: frozenset[str] = frozenset(PARSEABLE_MIME_MAP.values())

def get_parseable_mime_type(ext: str) -> str:
    return PARSEABLE_MIME_MAP.get(ext.lower(), "")
