"""Package-local logger for Namma Agent.

Self-contained so the new ``namma_agent/`` package has no dependency on the legacy
``core/`` tree. Logs to the terminal AND to a rotating file (``logs/namma_agent.log``
by default) so there's always a trail to debug from.

Level resolution: ``NAMMA_LOG_LEVEL`` env var > config ``logging.level`` >
``INFO``. Set it to ``DEBUG`` for verbose tracing of turns, tools, and providers.
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

logger = logging.getLogger("namma_agent")

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_DATEFMT = "%H:%M:%S"


def _formatter() -> logging.Formatter:
    return logging.Formatter(_FORMAT, _DATEFMT)


def _has_console() -> bool:
    return any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler)
        for h in logger.handlers
    )


def _has_file() -> bool:
    return any(isinstance(h, RotatingFileHandler) for h in logger.handlers)


def configure_logging(level: str | None = None, log_file: str | None = "logs/namma_agent.log",
                      to_file: bool = True) -> logging.Logger:
    """Set the level and attach console + rotating-file handlers (idempotent)."""
    lvl = (level or os.environ.get("NAMMA_LOG_LEVEL", "INFO")).upper()
    logger.setLevel(getattr(logging, lvl, logging.INFO))
    if not _has_console():
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(_formatter())
        logger.addHandler(sh)
    if to_file and log_file and not _has_file():
        try:
            Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
            fh.setFormatter(_formatter())
            logger.addHandler(fh)
        except OSError:
            pass  # read-only fs etc. — console logging still works
    logger.propagate = False
    return logger


# Minimal console config at import so logging always works, even before the app
# calls configure_logging() with the config-driven level + file handler.
if not logger.handlers:
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(_formatter())
    logger.addHandler(_h)
    logger.setLevel(getattr(logging, os.environ.get("NAMMA_LOG_LEVEL", "INFO").upper(), logging.INFO))
    logger.propagate = False
