from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path


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
