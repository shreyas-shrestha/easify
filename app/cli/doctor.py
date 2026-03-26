"""`easify doctor` — environment and L3 readiness checks."""

from __future__ import annotations

import json
import os
import platform
import sys
from typing import Any, Dict, List, Literal, TypedDict

from app.cli.l3_probe import probe_l3_backend
from app.config.settings import Settings, _config_dir


class DoctorCheckDict(TypedDict):
    id: str
    level: Literal["ok", "warn", "fail"]
    message: str


def _pkg_version() -> str:
    try:
        from importlib.metadata import version

        return version("easify")
    except Exception:
        return "unknown"


def gather_doctor_report(settings: Settings) -> Dict[str, Any]:
    """Structured report for `--json` and human output."""
    checks: List[DoctorCheckDict] = []

    def ok(cid: str, message: str) -> None:
        checks.append({"id": cid, "level": "ok", "message": message})

    def warn(cid: str, message: str) -> None:
        checks.append({"id": cid, "level": "warn", "message": message})

    def fail(cid: str, message: str) -> None:
        checks.append({"id": cid, "level": "fail", "message": message})

    ok("config_dir", f"config dir {_config_dir()}")
    sp = settings.snippets_paths
    if not sp:
        warn("snippets_paths", "no snippets_paths — unusual")
    else:
        found = False
        for p in sp:
            if p.is_file():
                ok("snippets_file", str(p))
                found = True
        if not found:
            warn(
                "snippets_file",
                f"no snippets.json found in {len(sp)} configured path(s) — run `easify init`",
            )

    cdb = settings.cache_db_path
    try:
        cdb.parent.mkdir(parents=True, exist_ok=True)
        probe = cdb.parent / ".easify_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        ok("cache_writable", str(cdb.parent))
    except OSError as e:
        fail("cache_writable", f"cannot write cache directory {cdb.parent}: {e}")

    prov = (settings.ai_provider or "ollama").strip().lower()
    ok("ai_provider", prov)

    outcome = probe_l3_backend(settings, httpx_timeout=10.0)
    l3_json = {
        "ollama_reachable": outcome.ollama_reachable,
        "ollama_tags_url": outcome.ollama_tags_url,
        "issues": [{"level": i.level, "message": i.message} for i in outcome.issues],
    }

    if prov in ("openai", "gpt"):
        for issue in outcome.issues:
            if issue.level == "fail":
                fail("l3_backend", issue.message)
            else:
                warn("l3_backend", issue.message)
        if not outcome.issues:
            ok("openai_key", "OpenAI: API key set")
    elif prov in ("anthropic", "claude"):
        for issue in outcome.issues:
            if issue.level == "fail":
                fail("l3_backend", issue.message)
            else:
                warn("l3_backend", issue.message)
        if not outcome.issues:
            ok("anthropic_key", "Anthropic: API key set")
    else:
        for issue in outcome.issues:
            if issue.level == "fail":
                fail("l3_backend", issue.message)
            else:
                warn("l3_backend", issue.message)
        if outcome.ollama_reachable:
            ok("ollama_reachable", f"Ollama: reachable at {outcome.ollama_tags_url}")
            want = (settings.ollama_model or "").strip()
            model_warned = any("not in tags" in i.message for i in outcome.issues if i.level == "warn")
            if want and not model_warned:
                ok("ollama_model", f'Ollama: model "{settings.ollama_model}" present')

    if settings.semantic_snippets:
        try:
            import sentence_transformers  # noqa: F401

            ok("semantic", "sentence-transformers importable")
        except ImportError:
            warn("semantic", "install `easify[semantic]` or `sentence-transformers`")

    if settings.palette_hotkey.strip() or settings.expansion_preview:
        try:
            import tkinter as tk
        except ImportError:
            warn("tkinter", "tkinter not installed — palette/preview need it")
        else:
            try:
                r = tk.Tk()
                r.withdraw()
                r.destroy()
                ok("tkinter", "display available")
            except tk.TclError:
                warn("tkinter", "no display ($DISPLAY / headless) — palette/preview will skip")

    if settings.backend.strip().lower() == "evdev" and not settings.evdev_device.strip():
        warn("evdev", "EASIFY_BACKEND=evdev but EASIFY_EVDEV_DEVICE is empty")
    if platform.system() == "Linux":
        try:
            from app.context.focus import linux_session_is_wayland

            if linux_session_is_wayland():
                warn(
                    "wayland",
                    "Wayland session: app/window focus via xdotool is unavailable; "
                    "namespace snippets need EASIFY_SNIPPET_NAMESPACE_LENIENT=1 or X11. "
                    "For keyboard capture, prefer EASIFY_BACKEND=evdev with device permissions.",
                )
        except Exception:
            pass
        ed = settings.evdev_device.strip()
        if ed:
            if not os.path.exists(ed):
                warn("evdev_device", f"EASIFY_EVDEV_DEVICE path does not exist: {ed}")
            elif not os.access(ed, os.R_OK):
                warn(
                    "evdev_device",
                    f"No read access to {ed} — add user to the 'input' group or use a udev rule",
                )

    if platform.system() == "Darwin":
        ok("macos_permissions", "grant Accessibility + Input Monitoring to your terminal (or easify binary)")

    fails = sum(1 for c in checks if c["level"] == "fail")
    warns = sum(1 for c in checks if c["level"] == "warn")

    return {
        "easify_version": _pkg_version(),
        "python": sys.version.split()[0],
        "platform": platform.system(),
        "ai_provider": prov,
        "checks": checks,
        "l3_probe": l3_json,
        "summary": {"fail": fails, "warn": warns},
    }


def run_doctor(settings: Settings, *, strict: bool = False, json_format: bool = False) -> int:
    report = gather_doctor_report(settings)
    fails = report["summary"]["fail"]
    warns = report["summary"]["warn"]
    exit_code = 1 if fails else (1 if strict and warns else 0)

    if json_format:
        payload = {**report, "exit_code": exit_code}
        print(json.dumps(payload, indent=2))
        return exit_code

    print(f"Easify doctor (python {report['python']} on {report['platform']})")
    print()

    for c in report["checks"]:
        msg = c["message"]
        if c["level"] == "ok":
            print(f"  ok  {msg}")
        elif c["level"] == "warn":
            print(f"  warn {msg}")
        else:
            print(f"  FAIL {msg}")

    print()
    if fails:
        print(f"Summary: {fails} error(s), {warns} warning(s). Fix errors before relying on L3.")
    elif warns:
        print(f"Summary: {warns} warning(s).")
    else:
        print("Summary: all checks passed.")
    return exit_code
