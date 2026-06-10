"""?????? ? ??????????????????"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

LOG_FILE = Path(__file__).resolve().parent / "agent.log"
LOGGER_NAME = "ownit_agent"

_logger: logging.Logger | None = None


def setup_logging(level: int = logging.WARNING) -> logging.Logger:
    """?????????????? logger ???"""
    global _logger

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)

    # ?????? handler
    if logger.handlers:
        return logger

    # ??? handler???? stderr????? Rich ? stdout ???
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s", datefmt="%H:%M:%S",
    ))
    logger.addHandler(console_handler)

    # ?? handler????????????
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(name)s:%(lineno)d %(message)s",
    ))
    logger.addHandler(file_handler)

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """?????? logger ???????????? WARNING ???"""
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger
