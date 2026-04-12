"""Test that get_logger does not permanently cache empty run_id."""
import logging
import unittest
from shared.log import get_logger, _GCPHandler


class TestLoggerContext(unittest.TestCase):
    def setUp(self):
        # Remove any existing handlers for test logger to ensure clean state
        logger = logging.getLogger("bummdidumm.test_ctx")
        logger.handlers.clear()

    def test_stale_context_not_cached(self):
        """Second call with run_id must update handler context, not be silently dropped."""
        get_logger("test_ctx", phase="PHASE_A")  # no run_id
        get_logger("test_ctx", run_id="run_123", phase="PHASE_A")
        logger = logging.getLogger("bummdidumm.test_ctx")
        for h in logger.handlers:
            if isinstance(h, _GCPHandler):
                self.assertEqual(h._ctx.get("run_id"), "run_123",
                    "run_id must be updated on second get_logger call")
                return
        self.fail("No _GCPHandler found")

    def test_first_caller_with_run_id_wins(self):
        """First call with run_id sets it correctly."""
        logging.getLogger("bummdidumm.test_ctx2").handlers.clear()
        get_logger("test_ctx2", run_id="run_abc", phase="PHASE_X")
        logger = logging.getLogger("bummdidumm.test_ctx2")
        for h in logger.handlers:
            if isinstance(h, _GCPHandler):
                self.assertEqual(h._ctx.get("run_id"), "run_abc")
                return
        self.fail("No _GCPHandler found")


if __name__ == "__main__":
    unittest.main()
