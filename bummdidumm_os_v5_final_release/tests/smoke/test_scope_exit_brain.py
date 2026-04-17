"""Tests for auto-exclusion of scope-exited / deleted sources in the brain runtime.

Gap-A: MOVED_OUT_OF_SCOPE events must not re-index content and must not clear
existing brain records (EXCLUDED semantics, not PURGED).

Gap-B: DELETED / TRASHED / REMOVED_OR_NO_ACCESS sources are likewise auto-excluded.

The effective_exclusions dict (built dynamically in runtime.py) must give
explicit Knowledge_Exclusions entries priority over auto-exclusions.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from personal_brain.runtime import PersonalBrainRuntime


def _jsonl_file_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            fid = row.get("file_id", "")
            if fid:
                ids.add(fid)
    return ids


def _minimal_source(file_id: str, change_type: str = "") -> dict:
    return {
        "file_id": file_id,
        "source_path": f"/fake/{file_id}.txt",
        "source_path_rel": f"{file_id}.txt",
        "original_filename": f"{file_id}.txt",
        "mime": "text/plain",
        "ext": ".txt",
        "content": {"title": f"{file_id}.txt", "raw_text": "hello world"},
        "change_type": change_type,
    }


class TestAutoExcludeRemovedSources(unittest.TestCase):
    """Files with removal change_types must be auto-excluded (brain records preserved)."""

    def _index_and_then_remove(self, change_type: str):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = PersonalBrainRuntime("proj", root)
            pub = root / "20_index" / "published"

            # Run 1: index the file normally.
            runtime.process_sources([_minimal_source("file_x")])
            source_ids_before = _jsonl_file_ids(pub / "00_source_registry.jsonl")
            self.assertIn("file_x", source_ids_before, "File must be indexed in run 1")
            _record_ids_before = _jsonl_file_ids(pub / "01_record_index.jsonl")
            # Records may or may not exist depending on parser — we just verify source exists.

            # Run 2: file exits scope / is deleted.
            removal_source = _minimal_source("file_x", change_type=change_type)
            runtime.process_sources([removal_source])

            # The source entry must NOT be re-indexed (parser must not be called on
            # inaccessible content); existing records are preserved (EXCLUDED semantics).
            # Specifically: the source registry must still contain file_x (preserved),
            # and no new parser output must have overwritten it with error status.
            source_ids_after = _jsonl_file_ids(pub / "00_source_registry.jsonl")
            self.assertIn(
                "file_x", source_ids_after,
                f"EXCLUDED source ({change_type}) must preserve existing registry entry",
            )
            return pub

    def test_moved_out_of_scope_auto_excluded(self):
        self._index_and_then_remove("MOVED_OUT_OF_SCOPE")

    def test_deleted_auto_excluded(self):
        self._index_and_then_remove("DELETED")

    def test_trashed_auto_excluded(self):
        self._index_and_then_remove("TRASHED")

    def test_removed_or_no_access_auto_excluded(self):
        self._index_and_then_remove("REMOVED_OR_NO_ACCESS")

    def test_removal_source_does_not_call_parser(self):
        """A removal source must NOT produce new records (parser must be bypassed)."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = PersonalBrainRuntime("proj", root)
            pub = root / "20_index" / "published"

            # Run 1: index a file that produces at least one source entry.
            runtime.process_sources([_minimal_source("file_y")])
            sources_run1 = []
            src_path = pub / "00_source_registry.jsonl"
            if src_path.exists():
                for line in src_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        sources_run1.append(json.loads(line))
            self.assertTrue(any(s.get("file_id") == "file_y" for s in sources_run1))

            # Run 2: deletion event — same file_id, change_type=DELETED.
            runtime.process_sources([_minimal_source("file_y", change_type="DELETED")])

            # The scanned_at timestamp of the source must NOT be updated
            # (parser was not called → entry unchanged from run 1).
            sources_run2 = []
            if src_path.exists():
                for line in src_path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        sources_run2.append(json.loads(line))

            entry_run1 = next((s for s in sources_run1 if s.get("file_id") == "file_y"), None)
            entry_run2 = next((s for s in sources_run2 if s.get("file_id") == "file_y"), None)
            self.assertIsNotNone(entry_run2, "Source entry must still exist after deletion event")
            if entry_run1 and entry_run2:
                self.assertEqual(
                    entry_run1.get("scanned_at"), entry_run2.get("scanned_at"),
                    "scanned_at must not change when parser is bypassed for deletion event",
                )


class TestExplicitPurgeOverridesAutoExclude(unittest.TestCase):
    """An explicit PURGED entry in Knowledge_Exclusions must take priority
    over the auto-EXCLUDED dynamic rule."""

    def test_purged_overrides_auto_excluded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            runtime = PersonalBrainRuntime("proj", root)
            pub = root / "20_index" / "published"

            # Run 1: index the file.
            runtime.process_sources([_minimal_source("file_z")])
            self.assertIn("file_z", _jsonl_file_ids(pub / "00_source_registry.jsonl"))

            # Run 2: deletion event AND explicit PURGED in exclusions.
            # The PURGED status must win → source must be tombstoned.
            runtime.process_sources(
                [_minimal_source("file_z", change_type="DELETED")],
                exclusions={"file_z": "PURGED"},
            )
            source_ids_after = _jsonl_file_ids(pub / "00_source_registry.jsonl")
            self.assertNotIn(
                "file_z", source_ids_after,
                "Explicit PURGED must tombstone the source even when change_type is DELETED",
            )


if __name__ == "__main__":
    unittest.main()
