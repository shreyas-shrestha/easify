"""`easify autostart` — install/remove login startup (macOS / Linux / Windows)."""

from __future__ import annotations

import os
import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List


def resolve_program_argv() -> List[str]:
    """Command to run Easify main listener (same as bare `easify`)."""
    exe = shutil.which("easify")
    if exe:
        return [exe]
    return [sys.executable, "-m", "app"]


def _launch_agent_plist(label: str, argv: List[str]) -> str:
    parts = "\n    ".join(f"<string>{_esc_xml(a)}</string>" for a in argv)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{_esc_xml(label)}</string>
  <key>ProgramArguments</key>
  <array>
    {parts}
  </array>
  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
"""


def _esc_xml(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def launch_agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def systemd_user_dir() -> Path:
    return Path.home() / ".config" / "systemd" / "user"


LABEL = "com.easify.app"
SERVICE = "easify.service"
PLIST_NAME = f"{LABEL}.plist"


def autostart_install() -> int:
    argv = resolve_program_argv()
    system = platform.system()
    if system == "Darwin":
        launch_agents_dir().mkdir(parents=True, exist_ok=True)
        plist = launch_agents_dir() / PLIST_NAME
        plist.write_text(_launch_agent_plist(LABEL, argv), encoding="utf-8")
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)], check=False, capture_output=True)
        r = subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            r2 = subprocess.run(["launchctl", "load", str(plist)], capture_output=True, text=True)
            if r2.returncode != 0:
                err = (r.stderr or r.stdout or r2.stderr or r2.stdout or "unknown error").strip()
                print(f"launchctl failed: {err}", file=sys.stderr)
                return 1
        print(f"Installed LaunchAgent: {plist}")
        print("Easify starts at login. To start now: launchctl kickstart -k gui/$(id -u)/com.easify.app")
        return 0

    if system == "Linux":
        systemd_user_dir().mkdir(parents=True, exist_ok=True)
        unit = systemd_user_dir() / SERVICE
        exec_line = " ".join(shlex.quote(a) for a in argv)
        unit.write_text(
            f"""[Unit]
Description=Easify text expansion
After=graphical-session.target

[Service]
Type=simple
ExecStart={exec_line}
Restart=on-failure

[Install]
WantedBy=default.target
""",
            encoding="utf-8",
        )
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        r = subprocess.run(["systemctl", "--user", "enable", "--now", SERVICE], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"systemctl --user enable failed: {r.stderr or r.stdout}", file=sys.stderr)
            print(
                "Ensure a user systemd session is active (graphical login), or enable lingering.",
                file=sys.stderr,
            )
            return 1
        print(f"Installed systemd user unit: {unit}")
        return 0

    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            print("APPDATA not set", file=sys.stderr)
            return 1
        startup = Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        startup.mkdir(parents=True, exist_ok=True)
        bat = startup / "easify_autostart.bat"
        qargv = " ".join(f'"{a}"' if " " in a else a for a in argv)
        bat.write_text(f"@echo off\r\nstart \"\" /MIN {qargv}\r\n", encoding="utf-8")
        print(f"Installed startup script: {bat}")
        return 0

    print(f"autostart install not implemented for {system}", file=sys.stderr)
    return 2


def autostart_remove() -> int:
    system = platform.system()
    if system == "Darwin":
        plist = launch_agents_dir() / PLIST_NAME
        if plist.is_file():
            subprocess.run(
                ["launchctl", "bootout", f"gui/{os.getuid()}", str(plist)],
                check=False,
                capture_output=True,
            )
            subprocess.run(["launchctl", "unload", str(plist)], check=False, capture_output=True)
            plist.unlink(missing_ok=True)
            print(f"Removed {plist}")
        else:
            print(f"No plist at {plist}")
        return 0

    if system == "Linux":
        subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE], check=False, capture_output=True)
        unit = systemd_user_dir() / SERVICE
        unit.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        print(f"Removed user unit {SERVICE} (if present)")
        return 0

    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        bat = (
            Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "easify_autostart.bat"
        )
        if bat.is_file():
            bat.unlink()
            print(f"Removed {bat}")
        else:
            print(f"No {bat}")
        return 0

    print(f"autostart remove not implemented for {system}", file=sys.stderr)
    return 2


def autostart_status() -> int:
    system = platform.system()
    if system == "Darwin":
        plist = launch_agents_dir() / PLIST_NAME
        print(f"plist exists: {plist.is_file()} ({plist})")
        r = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
            capture_output=True,
            text=True,
        )
        out = (r.stdout or r.stderr or "(not loaded)").strip()
        print(out[:1200])
        return 0

    if system == "Linux":
        r = subprocess.run(
            ["systemctl", "--user", "is-enabled", SERVICE],
            capture_output=True,
            text=True,
        )
        print(f"systemctl --user is-enabled {SERVICE}: {r.stdout.strip()} (exit {r.returncode})")
        return 0

    if system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        bat = (
            Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "easify_autostart.bat"
        )
        print(f"startup bat exists: {bat.is_file()} ({bat})")
        return 0

    print(f"autostart status not implemented for {system}", file=sys.stderr)
    return 2
