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
    sub.add_parser("ui", help="Local web UI for user snippets (localhost)")
    p_doc = sub.add_parser("doctor", help="Check paths, optional deps, and AI backend reachability")
    p_doc.add_argument("--strict", action="store_true", help="Exit with error if any warnings")
    p_as = sub.add_parser("autostart", help="Install or remove login startup (macOS/Linux/Windows)")
    as_sub = p_as.add_subparsers(dest="autostart_cmd")
    as_sub.add_parser("install", help="Start Easify when you log in")
    as_sub.add_parser("remove", help="Remove login startup entry")
    as_sub.add_parser("status", help="Show autostart configuration state")
    args = ap.parse_args()
    if args.command == "init":
        _init_config()
        return
    if args.command == "ui":
        from app.ui.snippet_server import run_snippet_ui

        run_snippet_ui(Settings.load())
        return
    if args.command == "doctor":
        from app.cli.doctor import run_doctor

        sys.exit(run_doctor(Settings.load(), strict=args.strict))
    if args.command == "autostart":
        from app.cli import autostart as autostart_mod

        cmd = args.autostart_cmd
        if cmd == "install":
            sys.exit(autostart_mod.autostart_install())
        if cmd == "remove":
            sys.exit(autostart_mod.autostart_remove())
        if cmd == "status":
            sys.exit(autostart_mod.autostart_status())
        p_as.print_help()
        sys.exit(2)
    if args.command not in (None, "run"):
        ap.print_help()
        return

    settings = Settings.load()
    if not settings.any_activation_enabled():
        LOG.error(
            "Enable at least one activation: EASIFY_ACTIVATION_PREFIX=1, "
            "EASIFY_ACTIVATION_DOUBLE_SPACE=1, or set EASIFY_PALETTE_HOTKEY"
        )
        sys.exit(2)
    if settings.use_prefix_trigger and not settings.trigger.strip():
        LOG.error("EASIFY_TRIGGER is required when prefix activation is enabled")
        sys.exit(2)

    service = ExpansionService(settings)
    service.start()
    service.preload_cache_metadata()
    if settings.prewarm:
        service.prewarm_cache()

    LOG.info(
        "Easify L0→L3 | provider=%s | cache_model=%s | tray=%s | palette=%s | context_words=%s",
        settings.ai_provider,
        service.cache_model_id,
        "on" if settings.tray_enabled else "off",
        "on" if settings.palette_hotkey.strip() else "off",
        settings.context_buffer_words,
    )

    stop = threading.Event()
    hotkey_listener = None

    listener = KeyboardListener(
        service=service,
        settings=settings,
        trigger=settings.trigger,
        enter_backspaces=settings.enter_backspaces,
        debug=settings.debug_keys,
    )

    if settings.palette_hotkey.strip():
        try:
            from pynput import keyboard as kb

            from app.ui.palette import open_expansion_palette

            hk_str = settings.palette_hotkey.strip()

            def _palette() -> None:
                pw = listener._prior_context_string()

                def _run() -> None:
                    open_expansion_palette(service, settings, prior_words=pw)

                threading.Thread(target=_run, daemon=True).start()

            hotkey_listener = kb.GlobalHotKeys({hk_str: _palette})
            hotkey_listener.start()
            LOG.info("palette hotkey registered: %s", hk_str)
        except Exception as e:
            LOG.warning("palette hotkey failed (%s); check pynput hotkey grammar", e)

    undo_listener = None
    if settings.undo_hotkey.strip():
        try:
            from pynput import keyboard as kb

            hk_u = settings.undo_hotkey.strip()

            def _undo_expansion() -> None:
                service.try_undo()

            undo_listener = kb.GlobalHotKeys({hk_u: _undo_expansion})
            undo_listener.start()
            LOG.info("undo hotkey registered: %s", hk_u)
        except Exception as e:
            LOG.warning("undo hotkey failed (%s); check pynput hotkey grammar", e)

    if settings.tray_enabled:

        def _tray_stop() -> None:
            stop.set()

        from app.ui.tray import run_tray_app

        threading.Thread(
            target=lambda: run_tray_app(service, stop, _tray_stop),
            daemon=True,
            name="easify-tray",
        ).start()

    def _stop(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)
    try:
        listener.run_blocking(stop)
    finally:
        if hotkey_listener is not None:
            try:
                hotkey_listener.stop()
            except Exception:
                pass
        if undo_listener is not None:
            try:
                undo_listener.stop()
            except Exception:
                pass
        service.cache.close()


if __name__ == "__main__":
    main()
