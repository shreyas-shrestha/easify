"""CLI entry: `easify`, `python -m app`, or `PYTHONPATH=. python app/main.py`."""

from __future__ import annotations

import argparse
import shutil
import signal
import sys
import threading
from pathlib import Path

from app.config.settings import Settings, default_data_dir
from app.engine.service import ExpansionService
from app.keyboard.listener import KeyboardListener
from app.utils.log import get_logger

LOG = get_logger(__name__)


def _init_config() -> None:
    cfg = Path.home() / ".config" / "easify"
    cfg.mkdir(parents=True, exist_ok=True)
    dst = cfg / "snippets.json"
    dd = default_data_dir()
    src = dd / "snippets.json"
    if not dst.exists() and src.is_file():
        shutil.copy(src, dst)
        print(f"Created {dst}", file=sys.stderr)
    elif dst.exists():
        print(f"Already exists: {dst}", file=sys.stderr)
    elif not src.is_file():
        print("No snippets template found to copy.", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(prog="easify")
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("run", help="Start global listener (default)")
    sub.add_parser("init", help="Create ~/.config/easify/ and default snippets.json")
    args = ap.parse_args()
    if args.command == "init":
        _init_config()
        return
    if args.command not in (None, "run"):
        ap.print_help()
        return

    settings = Settings.load()
    if not settings.trigger:
        LOG.error("EASIFY_TRIGGER must be non-empty")
        sys.exit(2)

    service = ExpansionService(settings)
    service.start()
    service.preload_cache_metadata()
    if settings.prewarm:
        service.prewarm_cache()

    LOG.info(
        "Easify L1→L3 | snippets=%s paths | model=%s | cache_ttl=%ss | live_enrich=%s",
        len(settings.snippets_paths),
        settings.ollama_model,
        settings.cache_ttl_sec or "off",
        "on" if settings.live_cache_enrich else "off",
    )

    stop = threading.Event()

    def _stop(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    listener = KeyboardListener(
        service=service,
        settings=settings,
        trigger=settings.trigger,
        enter_backspaces=settings.enter_backspaces,
        debug=settings.debug_keys,
    )
    listener.run_blocking(stop)


if __name__ == "__main__":
    main()
