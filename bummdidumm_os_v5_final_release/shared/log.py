"""Structured JSON logging for Cloud Run. stdout is auto-parsed as structured entries."""
from __future__ import annotations
import json
import logging
import os
import sys
from typing import Any

_SKIP = frozenset({
    "msg","args","levelname","levelno","pathname","filename","module",
    "exc_info","exc_text","stack_info","lineno","funcName","created",
    "msecs","relativeCreated","thread","threadName","processName","process","name","message",
})
_SEV = {"DEBUG":"DEBUG","INFO":"INFO","WARNING":"WARNING","ERROR":"ERROR","CRITICAL":"CRITICAL"}


class _GCPHandler(logging.Handler):
    def __init__(self, run_id: str = "", phase: str = "") -> None:
        super().__init__()
        self._ctx = {"run_id": run_id, "phase": phase}

    def emit(self, record: logging.LogRecord) -> None:
        entry: dict[str, Any] = {"severity": _SEV.get(record.levelname, "DEFAULT"),
                                  "message": record.getMessage(), **self._ctx}
        for k, v in record.__dict__.items():
            if k not in _SKIP:
                entry[k] = v
        if record.exc_info:
            entry["exception"] = self.formatter.formatException(record.exc_info) if self.formatter else str(record.exc_info)
        sys.stdout.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        sys.stdout.flush()


def get_logger(name: str, run_id: str = "", phase: str = "") -> logging.Logger:
    logger = logging.getLogger(f"bummdidumm.{name}")
    if not logger.handlers:
        logger.addHandler(_GCPHandler(run_id=run_id, phase=phase))
        logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))
        logger.propagate = False
    else:
        # Update context on existing handler if new run_id provided
        for h in logger.handlers:
            if isinstance(h, _GCPHandler) and run_id:
                h._ctx["run_id"] = run_id
            if isinstance(h, _GCPHandler) and phase:
                h._ctx["phase"] = phase
    return logger
