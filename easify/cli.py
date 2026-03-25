"""CLI: run (default) | init (snippets + config dir)."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from easify.app import run


def _init_config() -> None:
    cfg = Path.home() / ".config" / "easify"
    cfg.mkdir(parents=True, exist_ok=True)
    dst = cfg / "snippets.json"
    src = Path(__file__).resolve().parent / "snippets.example.json"
    if not dst.exists() and src.is_file():
        shutil.copy(src, dst)
        print(f"Created {dst}", file=sys.stderr)
    elif dst.exists():
        print(f"Already exists: {dst}", file=sys.stderr)
    elif not src.is_file():
        print("snippets.example.json missing from package.", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(prog="easify")
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("run", help="Start global listener (default)")
    sub.add_parser("init", help="Create ~/.config/easify/ and default snippets.json")
    args = ap.parse_args()
    if args.command == "init":
        _init_config()
        return
    if args.command in (None, "run"):
        run()
        return
    ap.print_help()


if __name__ == "__main__":
    main()
