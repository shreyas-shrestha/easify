"""Append-only JSONL audit log for expansions (opt-in)."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.config.settings import Settings
from app.utils.log import get_logger

LOG = get_logger(__name__)
_lock = threading.Lock()


def append_expansion_record(settings: Settings, record: Mapping[str, Any]) -> None:
    if not settings.expansion_log_enabled:
        return
    path: Path = settings.expansion_log_path
    row = dict(record)
    row.setdefault("ts", datetime.now(timezone.utc).isoformat())
    line = json.dumps(row, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
    except OSError as e:
        LOG.debug("expansion log append failed: %s", e)
