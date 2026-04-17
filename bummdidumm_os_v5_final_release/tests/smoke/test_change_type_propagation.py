"""Regression: change_type must be propagated from FileRecord into source dicts.

Gap-B / Auto-Exclusion in personal_brain/runtime.py checks source["change_type"]
to auto-EXCLUDE deleted/trashed/removed sources. If change_type is missing from
the source dict, the exclusion logic silently does nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.models import FileRecord  # noqa: E402


_MINIMAL_INSPECT_RESULT = {
    "preview": {},
    "text_preview": "",
    "content": {},
    "is_export": False,
    "is_bundle": False,
    "is_archive": False,
}


def _make_pass2_stubs() -> dict:
    """Return sys.modules stubs for modules not yet imported that block main_pass2 import.

    Only stubs entries that are currently absent so patch.dict restores the original
    state (absent) on exit — preventing permanent pollution of sys.modules for other
    test files (e.g. test_gemini_helpers.py) collected in the same pytest session.
    """
    candidates = {
        "shared.oauth_user_credentials": {"get_user_credentials": MagicMock(return_value=MagicMock())},
        "shared.gemini_helpers": {"GeminiOCR": MagicMock()},
        # googleapiclient.discovery imports google.oauth2.service_account which triggers
        # the same broken crypto chain as oauth_user_credentials.
        "googleapiclient.discovery": {"build": MagicMock()},
    }
    stubs = {}
    for mod, attrs in candidates.items():
        if mod not in sys.modules:
            stub = MagicMock()
            for k, v in attrs.items():
                setattr(stub, k, v)
            stubs[mod] = stub
    return stubs


def _make_record(change_type: str = "UNCHANGED", file_id: str = "fid_test") -> FileRecord:
    return FileRecord(
        run_utc="2024-01-01T00:00:00Z",
        run_id="run_test",
        name="test.txt",
        file_id=file_id,
        path_display="/Test/test.txt",
        mime_type="text/plain",
        effective_mime_type="text/plain",
        status="ORIGINAL",
        change_type=change_type,
        can_download=False,  # skip actual Drive download
    )


def _call_build_source(rec: FileRecord) -> list[dict]:
    """Call _build_source_from_record with mocked inspect_source and no real Drive calls."""
    with patch.dict(sys.modules, _make_pass2_stubs()):
        with patch("main_pass2.inspect_source", return_value=_MINIMAL_INSPECT_RESULT):
            from main_pass2 import _build_source_from_record
            return _build_source_from_record(rec, MagicMock(), enable_shared_drives=False)


# ---------------------------------------------------------------------------
# BUG-02: change_type in parent source dict
# ---------------------------------------------------------------------------

def test_change_type_present_in_parent_source():
    rec = _make_record(change_type="UNCHANGED")
    sources = _call_build_source(rec)
    assert sources, "Expected at least one source dict"
    parent = sources[-1]
    assert "change_type" in parent, "change_type must be present in parent source dict"
    assert parent["change_type"] == "UNCHANGED"


def test_change_type_deleted_propagated():
    rec = _make_record(change_type="DELETED")
    sources = _call_build_source(rec)
    assert sources[-1].get("change_type") == "DELETED"


def test_change_type_trashed_propagated():
    rec = _make_record(change_type="TRASHED")
    assert _call_build_source(rec)[-1].get("change_type") == "TRASHED"


def test_change_type_moved_out_of_scope_propagated():
    rec = _make_record(change_type="MOVED_OUT_OF_SCOPE")
    assert _call_build_source(rec)[-1].get("change_type") == "MOVED_OUT_OF_SCOPE"


def test_change_type_removed_or_no_access_propagated():
    rec = _make_record(change_type="REMOVED_OR_NO_ACCESS")
    assert _call_build_source(rec)[-1].get("change_type") == "REMOVED_OR_NO_ACCESS"


# ---------------------------------------------------------------------------
# BUG-02: change_type forwarded to ZIP sub-sources
# ---------------------------------------------------------------------------

def test_change_type_in_zip_sub_source():
    """_extract_zip_sources must forward parent_rec.change_type to each sub-source."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("inner.txt", "hello")
    zip_bytes = buf.getvalue()

    parent_rec = _make_record(change_type="DELETED")

    with patch.dict(sys.modules, _make_pass2_stubs()):
        with patch("main_pass2.inspect_source", return_value=_MINIMAL_INSPECT_RESULT):
            from main_pass2 import _extract_zip_sources
            sub_sources = _extract_zip_sources(zip_bytes, parent_rec)

    assert sub_sources, "Expected sub-sources from ZIP"
    for src in sub_sources:
        assert "change_type" in src, (
            f"change_type missing in sub-source: {src.get('original_filename')}"
        )
        assert src["change_type"] == "DELETED", (
            f"Sub-source change_type should be DELETED, got {src['change_type']!r}"
        )


# ---------------------------------------------------------------------------
# Gap-B: process_sources auto-EXCLUDES removal sources
# ---------------------------------------------------------------------------

def _make_source(file_id: str, change_type: str) -> dict:
    return {
        "file_id": file_id,
        "source_path": f"/Test/{file_id}.txt",
        "original_filename": f"{file_id}.txt",
        "mime": "text/plain",
        "ext": ".txt",
        "checksum_sha256": "",
        "raw_ref": "",
        "status": "ORIGINAL",
        "change_type": change_type,
        "sot_status": "derived",
        "canonical_format": "text",
        "preview": {},
        "text_preview": "",
        "content": {},
        "is_export": False,
        "is_bundle": False,
        "is_archive": False,
        "contains_pii": False,
        "contains_messages": False,
        "contains_geo": False,
        "contains_financial": False,
        "contains_media_refs": False,
    }


def test_process_sources_auto_excludes_deleted():
    """process_sources must EXCLUDE a source whose change_type is DELETED."""
    from personal_brain.runtime import PersonalBrainRuntime
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        runtime = PersonalBrainRuntime(project_id="test", out_root=Path(tmpdir))
        stats = runtime.process_sources(
            [_make_source("fid_deleted", "DELETED")], exclusions={}
        )

    assert stats.get("total_sources", 0) == 0, (
        f"DELETED source must be auto-EXCLUDED → total_sources=0, got stats={stats}"
    )


def test_process_sources_does_not_exclude_active_source():
    """process_sources must NOT exclude a source with a non-removal change_type."""
    from personal_brain.runtime import PersonalBrainRuntime
    import tempfile

    src = _make_source("fid_active", "UNCHANGED")
    src["text_preview"] = "some content"
    src["content"] = {"title": "active", "summary": ""}

    with tempfile.TemporaryDirectory() as tmpdir:
        runtime = PersonalBrainRuntime(project_id="test", out_root=Path(tmpdir))
        stats = runtime.process_sources([src], exclusions={})

    assert stats.get("total_sources", 0) >= 1, (
        f"UNCHANGED source must be processed (total_sources >= 1), got stats={stats}"
    )
