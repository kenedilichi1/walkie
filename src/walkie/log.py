"""Shared stderr logging.

Stdout stays reserved for machine-readable output (JSON-RPC rules); every
entry point calls setup() once, and tests get silence unless configured.
"""

import logging
import sys

LOGGER_NAME = "walkie"


def setup(level: int = logging.INFO) -> None:
    """Install the stderr handler once (idempotent)."""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def get_logger(name: str = "") -> logging.Logger:
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")
