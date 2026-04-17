"""Regression tests for flush_state backoff and lease staleness hardening.

Covers:
- BUG-D: flush_state() must route through _execute_with_backoff, not bare .execute()
- BUG-I: corrupt lease timestamp → stale (True), not deadlock (False)
- BUG-J: last_run_utc must NOT be used as lease staleness fallback
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from shared.state_helpers import StateTracker


def _make_tracker(state_data=None):
    sheets = MagicMock()
    sheets.spreadsheet_id = "sheet_id"
    sheets.sheets = MagicMock()
    tracker = StateTracker.__new__(StateTracker)
    tracker.sheets = sheets
    tracker.run_id = "run_test"
    tracker._state_cache = dict(state_data or {})
    tracker._known_hashes = None
    tracker._dirty = True  # pre-mark dirty so flush_state proceeds
    return tracker


# ---------------------------------------------------------------------------
# BUG-D: flush_state uses backoff
# ---------------------------------------------------------------------------

class TestFlushStateBackoff:

    def test_flush_state_uses_backoff(self):
        """flush_state() must call sheets._execute_with_backoff, not bare .execute()."""
        tracker = _make_tracker({"key1": "val1"})

        tracker.flush_state()

        assert tracker.sheets._execute_with_backoff.called, (
            "flush_state() must route the request through _execute_with_backoff"
        )
        # Verify that bare .execute() was NOT called directly on the request
        # (the request object is built by calling .update() then passed to backoff)
        update_req = tracker.sheets.sheets.spreadsheets.return_value.values.return_value.update.return_value
        update_req.execute.assert_not_called()


# ---------------------------------------------------------------------------
# BUG-I + BUG-J: _is_lease_stale
# ---------------------------------------------------------------------------

import main_pass1


class TestLeaseStaleHardening:

    def _state_with(self, **kv):
        m = MagicMock()
        m.get_val.side_effect = lambda k: kv.get(k)
        return m

    def test_lease_stale_corrupt_timestamp(self):
        """BUG-I: corrupt lease_heartbeat_at must cause _is_lease_stale to return True.

        Previously returned False, causing deadlock — no new instance could ever
        take over because the corrupt timestamp was treated as 'no heartbeat'.
        """
        state = self._state_with(lease_heartbeat_at="CORRUPT_NOT_A_TIMESTAMP")
        result = main_pass1._is_lease_stale(state, lease_timeout_sec=3600)
        assert result is True, (
            "Corrupt timestamp must be treated as stale (not as a permanent lock)"
        )

    def test_lease_stale_no_last_run_utc_fallback(self):
        """BUG-J: last_run_utc alone must NOT trigger staleness.

        last_run_utc is the timestamp of the *previous successful run*, not the
        current lease. An orphaned lease with no heartbeat/acquired_at should return
        False (no active lease detected), not True based on the previous run time.
        """
        from datetime import datetime, timezone, timedelta
        # Make last_run_utc appear very old (would be stale if used as fallback)
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=9999)).isoformat()
        state = self._state_with(
            lease_heartbeat_at=None,
            lease_acquired_at=None,
            last_run_utc=old_ts,
        )
        result = main_pass1._is_lease_stale(state, lease_timeout_sec=3600)
        assert result is False, (
            "Without lease timestamps, _is_lease_stale must return False "
            "(last_run_utc is not a lease timestamp)"
        )
