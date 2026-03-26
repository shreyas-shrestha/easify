"""`easify doctor` — environment and L3 readiness checks."""

from __future__ import annotations

import platform
import sys
from typing import List

from app.cli.l3_probe import probe_l3_backend
from app.config.settings import Settings, _config_dir

Issue = tuple[str, str]  # level, message


def run_doctor(settings: Settings, *, strict: bool = False) -> int:
    issues: List[Issue] = []

    def ok(msg: str) -> None:
        print(f"  ok  {msg}")

    def warn(msg: str) -> None:
        issues.append(("warn", msg))
        print(f"  warn {msg}")

    def fail(msg: str) -> None:
        issues.append(("fail", msg))
        print(f"  FAIL {msg}")

    print(f"Easify doctor (python {sys.version.split()[0]} on {platform.system()})")
    print()

    ok(f"config dir {_config_dir()!s}")
    sp = settings.snippets_paths
    if not sp:
        warn("no snippets_paths — unusual")
    else:
        found = False
        for p in sp:
            if p.is_file():
                ok(f"snippets file {p}")
                found = True
        if not found:
            warn(f"no snippets.json found in {len(sp)} configured path(s) — run `easify init`")

    cdb = settings.cache_db_path
    try:
        cdb.parent.mkdir(parents=True, exist_ok=True)
        probe = cdb.parent / ".easify_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        ok(f"cache parent writable ({cdb.parent})")
    except OSError as e:
        fail(f"cannot write cache directory {cdb.parent}: {e}")

    prov = (settings.ai_provider or "ollama").strip().lower()
    ok(f"AI provider = {prov}")

    if prov in ("openai", "gpt"):
        outcome = probe_l3_backend(settings, httpx_timeout=10.0)
        for issue in outcome.issues:
            if issue.level == "fail":
                fail(issue.message)
            else:
                warn(issue.message)
        if not outcome.issues:
            ok("OpenAI: API key set")
    elif prov in ("anthropic", "claude"):
        outcome = probe_l3_backend(settings, httpx_timeout=10.0)
        for issue in outcome.issues:
            if issue.level == "fail":
                fail(issue.message)
            else:
                warn(issue.message)
        if not outcome.issues:
            ok("Anthropic: API key set")
    else:
        outcome = probe_l3_backend(settings, httpx_timeout=10.0)
        for issue in outcome.issues:
            if issue.level == "fail":
                fail(issue.message)
            else:
                warn(issue.message)
        if outcome.ollama_reachable:
            ok(f"Ollama: reachable at {outcome.ollama_tags_url}")
            want = (settings.ollama_model or "").strip()
            model_warned = any("not in tags" in i.message for i in outcome.issues if i.level == "warn")
            if want and not model_warned:
                ok(f'Ollama: model "{settings.ollama_model}" present')

    if settings.semantic_snippets:
        try:
            import sentence_transformers  # noqa: F401

            ok("semantic: sentence-transformers importable")
        except ImportError:
            warn("semantic: install `easify[semantic]` or `sentence-transformers`")

    if settings.palette_hotkey.strip() or settings.expansion_preview:
        try:
            import tkinter as tk
        except ImportError:
            warn("tkinter not installed — palette/preview need it")
        else:
            try:
                r = tk.Tk()
                r.withdraw()
                r.destroy()
                ok("tkinter: display available")
            except tk.TclError:
                warn("tkinter: no display ($DISPLAY / headless) — palette/preview will skip")

    if settings.backend.strip().lower() == "evdev" and not settings.evdev_device.strip():
        warn("EASIFY_BACKEND=evdev but EASIFY_EVDEV_DEVICE is empty")

    if platform.system() == "Darwin":
        ok("macOS: grant Accessibility + Input Monitoring to your terminal (or easify binary)")

    fails = sum(1 for lvl, _ in issues if lvl == "fail")
    warns = sum(1 for lvl, _ in issues if lvl == "warn")
    print()
    if fails:
        print(f"Summary: {fails} error(s), {warns} warning(s). Fix errors before relying on L3.")
        return 1
    if warns:
        print(f"Summary: {warns} warning(s).")
    else:
        print("Summary: all checks passed.")
    return 1 if (strict and warns) else 0


