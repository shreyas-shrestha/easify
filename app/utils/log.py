"""Central logging for Easify."""

from __future__ import annotations

import logging
import os
import sys


def get_logger(name: str = "easify") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    level = logging.DEBUG if os.environ.get("EASIFY_DEBUG", "").lower() in ("1", "true", "yes") else logging.INFO
    logger.setLevel(level)
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(h)
    return logger
