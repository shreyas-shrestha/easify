"""
Runtime: keyboard hooks, async Ollama pipeline, inject, snippets, prompts.
"""

from __future__ import annotations

import asyncio
import os
import platform
import signal
import sys
import threading
import time
from typing import Any, Callable, Optional

import aiohttp
import keyboard

from easify import clipboard as cb
from easify import ollama_client
from easify import prompts
from easify import snippets as snippets_mod


def _env(key: str, default: str) -> str:
    """EASIFY_* wins; OLLAMA_EXPANDER_* kept for backward compatibility."""
    return os.environ.get(f"EASIFY_{key}") or os.environ.get(f"OLLAMA_EXPANDER_{key}") or default


# --- env config ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434/api/generate")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "phi3")
BACKSPACES_FOR_ENTER = int(_env("ENTER_BACKSPACES", "1"))
TRIGGER = _env("TRIGGER", "///")
_BACKSPACE_DELAY_MS = max(0, int(_env("BACKSPACE_DELAY_MS", "2")))
_PASTE_SETTLE_MS = max(0, int(_env("PASTE_DELAY_MS", "50")))
_AFTER_DELETE_MS = max(0, int(_env("AFTER_DELETE_MS", "30")))
NOTIFY_ERRORS = _env("NOTIFY_ERRORS", "").lower() in ("1", "true", "yes")
DEBUG_KEYS = _env("DEBUG", "").lower() in ("1", "true", "yes")
_RAW_BACKEND = _env("BACKEND", "auto").lower()
_FUZZY_MAX = int(_env("FUZZY_MAX", "2"))
_CLIPBOARD_RESTORE = _env("CLIPBOARD_RESTORE", "0").lower() in ("1", "true", "yes")
OLLAMA_RETRIES = int(_env("RETRIES", "2"))

_DARWIN_SLASH_SCAN = 0x2C

SNIPPETS_PATH = _env(
    "SNIPPETS",
    os.path.join(os.path.expanduser("~"), ".config", "easify", "snippets.json"),
)

_key_lock = threading.Lock()
_state_idle, _state_capturing = "idle", "capturing"
_state = _state_idle
_capture: list[str] = []
_trigger_matched = 0
_processing = False
_inject_depth = 0
_delete_impl: Optional[Callable[[int], None]] = None
_paste_impl: Optional[Callable[[str], None]] = None

_SNIPPETS: dict[str, str] = {}

_SHIFT_DIGIT = str.maketrans("1234567890", "!@#$%^&*()")

# async loop in background thread
_async_loop: Optional[asyncio.AbstractEventLoop] = None
_async_thread: Optional[threading.Thread] = None


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _notify(message: str, title: str = "Easify") -> None:
    if not NOTIFY_ERRORS:
        return
    import subprocess

    msg = message.replace("\\", "\\\\").replace('"', '\\"')
    ttl = title.replace("\\", "\\\\").replace('"', '\\"')
    try:
        if platform.system() == "Darwin":
            subprocess.run(
                ["/usr/bin/osascript", "-e", f'display notification "{msg}" with title "{ttl}"'],
                check=False,
                capture_output=True,
            )
        elif platform.system() == "Linux":
            subprocess.run(["notify-send", title, message], check=False, capture_output=True)
    except OSError:
        pass


def _kbd_pressed(hotkey: str) -> bool:
    try:
        return bool(keyboard.is_pressed(hotkey))
    except (ValueError, OSError, TypeError):
        return False


def _shift_held() -> bool:
    return _kbd_pressed("shift") or _kbd_pressed("left shift") or _kbd_pressed("right shift")


def _option_held_darwin() -> bool:
    return _kbd_pressed("option") or _kbd_pressed("alt") or _kbd_pressed("left alt") or _kbd_pressed("right alt")


def _char_from_key_event(event: Any) -> Optional[str]:
    name = (event.name or "").lower()
    if name in {
        "shift", "left shift", "right shift", "ctrl", "left ctrl", "right ctrl",
        "alt", "left alt", "right alt", "option", "left option", "right option",
        "cmd", "left cmd", "right cmd", "windows", "left windows", "right windows",
        "caps lock", "esc", "escape",
    }:
        return None
    shift = _shift_held()
    if platform.system() == "Darwin" and _option_held_darwin():
        return None
    if name in ("enter", "return"):
        return "\n"
    if name == "tab":
        return "\t"
    if name == "space":
        return " "
    if name == "backspace":
        return "\b"
    if name in ("slash", "/"):
        return "?" if shift else "/"
    unshifted = {
        "minus": "-", "equal": "=", "left bracket": "[", "right bracket": "]",
        "backslash": "\\", "semicolon": ";", "quote": "'", "comma": ",",
        "period": ".", "grave": "`",
    }
    shifted = {
        "minus": "_", "equal": "+", "left bracket": "{", "right bracket": "}",
        "backslash": "|", "semicolon": ":", "quote": '"', "comma": "<",
        "period": ">", "grave": "~",
    }
    if name in unshifted:
        return shifted[name] if shift else unshifted[name]
    if len(name) == 1:
        ch = name
        if ch.isalpha():
            return ch.upper() if shift else ch.lower()
        if ch.isdigit():
            return ch.translate(_SHIFT_DIGIT) if shift else ch
        if shift:
            sym = {
                "`": "~", "-": "_", "=": "+", "[": "{", "]": "}", "\\": "|",
                ";": ":", "'": '"', ",": "<", ".": ">", "/": "?",
            }
            return sym.get(ch, ch)
        return ch
    if platform.system() == "Darwin" and getattr(event, "scan_code", None) == _DARWIN_SLASH_SCAN:
        return "?" if _shift_held() else "/"
    return None


def _delete_n_chars(n: int) -> None:
    assert _delete_impl is not None
    _delete_impl(n)


def _paste_raw(text: str) -> None:
    assert _paste_impl is not None
    _paste_impl(text)


def _paste_with_clipboard_restore(text: str) -> None:
    previous = cb.get_clipboard() if _CLIPBOARD_RESTORE else None
    try:
        cb.set_clipboard(text)
        time.sleep(_PASTE_SETTLE_MS / 1000.0)
        _paste_raw(text)
    finally:
        if previous is not None and _CLIPBOARD_RESTORE:

            def _restore() -> None:
                time.sleep(0.35)
                try:
                    cb.set_clipboard(previous)
                except Exception:
                    pass

            threading.Thread(target=_restore, daemon=True).start()


def _try_advance_trigger(ch: Optional[str]) -> bool:
    global _trigger_matched
    if ch is None:
        return False
    next_i = _trigger_matched
    if next_i < len(TRIGGER) and ch == TRIGGER[next_i]:
        _trigger_matched += 1
        if _trigger_matched >= len(TRIGGER):
            _trigger_matched = 0
            return True
        return False
    if ch == TRIGGER[0]:
        _trigger_matched = 1
        return _trigger_matched >= len(TRIGGER)
    _trigger_matched = 0
    return False


def _require_trigger() -> None:
    if not TRIGGER:
        sys.exit("[easify] EASIFY_TRIGGER (or trigger value) must be non-empty.")
    if _RAW_BACKEND not in ("auto", "pynput", "keyboard"):
        sys.exit("[easify] EASIFY_BACKEND must be auto, pynput, or keyboard.")


async def _expand_async(session: aiohttp.ClientSession, capture: str) -> str:
    snippet = snippets_mod.resolve_snippet(capture, _SNIPPETS, _FUZZY_MAX)
    if snippet is not None:
        _log("[easify] snippet hit (fuzzy or exact)")
        return snippet
    user_prompt, system = prompts.classify(capture)
    return await ollama_client.generate(
        session,
        OLLAMA_URL,
        DEFAULT_MODEL,
        user_prompt,
        system,
        retries=OLLAMA_RETRIES,
    )


async def _job_worker(session: aiohttp.ClientSession, q: asyncio.Queue[str]) -> None:
    global _processing
    while True:
        raw = await q.get()
        delete_count = len(TRIGGER) + len(raw) + max(0, BACKSPACES_FOR_ENTER)
        try:
            if not raw.strip():
                continue
            result = await _expand_async(session, raw)
            try:
                _log(f"[easify] expanding, replacing {delete_count} chars…")
                await asyncio.to_thread(_delete_n_chars, delete_count)
                await asyncio.sleep(_AFTER_DELETE_MS / 1000.0)
                if result:
                    await asyncio.to_thread(_paste_with_clipboard_restore, result)
            except Exception as e:
                _log(f"[easify] Replace/paste failed: {e}")
                _notify(str(e)[:200])
        except Exception as e:
            _log(f"[easify] expand failed: {e}")
            _notify(str(e)[:200])
        finally:
            with _key_lock:
                _processing = False


def _start_async_worker() -> None:
    global _async_loop, _queue_holder
    ready = threading.Event()
    box: list[asyncio.Queue[str]] = []

    def runner() -> None:
        global _async_loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _async_loop = loop
        q: asyncio.Queue[str] = asyncio.Queue()
        box.append(q)
        ready.set()

        async def main_co() -> None:
            async with aiohttp.ClientSession() as session:
                await _job_worker(session, q)

        loop.run_until_complete(main_co())

    threading.Thread(target=runner, daemon=True).start()
    if not ready.wait(timeout=15.0):
        sys.exit("[easify] async worker failed to start.")
    _queue_holder["q"] = box[0]


_queue_holder: dict[str, Any] = {}


def _submit_capture(capture: str) -> None:
    loop = _async_loop
    if loop is None:
        return
    asyncio.run_coroutine_threadsafe(_queue_holder["q"].put(capture), loop)


def _process_prompt_sync_bridge(capture: str) -> None:
    """Called from key thread; hands work to async worker."""
    global _processing
    try:
        _submit_capture(capture)
    except Exception as e:
        _log(f"[easify] enqueue failed: {e}")
        with _key_lock:
            _processing = False


def _on_key_keyboard(event: keyboard.KeyboardEvent) -> None:
    global _state, _capture, _trigger_matched, _processing
    if event.event_type != getattr(keyboard, "KEY_DOWN", "down"):
        return
    run_prompt: Optional[str] = None
    with _key_lock:
        if _processing:
            return
        if _state == _state_idle:
            ch0 = _char_from_key_event(event)
            if _try_advance_trigger(ch0):
                if DEBUG_KEYS:
                    _log("[easify] capture mode ON")
                _state = _state_capturing
                _capture = []
            return
        name = (event.name or "").lower()
        if name in ("enter", "return"):
            if DEBUG_KEYS:
                _log(f"[easify] submit: {''.join(_capture)!r}")
            run_prompt = "".join(_capture)
            _processing = True
            _state = _state_idle
            _capture = []
            _trigger_matched = 0
        else:
            ch = _char_from_key_event(event)
            if ch == "\b":
                if _capture:
                    _capture.pop()
            elif ch not in (None, "\n"):
                _capture.append(ch)
                if DEBUG_KEYS and len(_capture) <= 80:
                    _log(f"[easify] capture: {''.join(_capture)!r}")
    if run_prompt is not None:
        threading.Thread(target=_process_prompt_sync_bridge, args=(run_prompt,), daemon=True).start()


def _pynput_key_char(key: Any) -> Optional[str]:
    from pynput.keyboard import Key

    if key == Key.enter:
        return "\n"
    if key == Key.backspace:
        return "\b"
    if key == Key.space:
        return " "
    if key == Key.tab:
        return "\t"
    if getattr(key, "char", None) is not None:
        return key.char
    return None


def _pynput_on_press(key: Any) -> None:
    global _state, _capture, _trigger_matched, _processing
    if _inject_depth > 0:
        return
    from pynput.keyboard import Key

    _skip_names = (
        "shift", "shift_l", "shift_r", "ctrl", "ctrl_l", "ctrl_r",
        "alt", "alt_l", "alt_r", "cmd", "cmd_l", "cmd_r", "caps_lock", "esc",
    )
    if key in tuple(getattr(Key, n, None) for n in _skip_names if hasattr(Key, n)):
        return
    run_prompt: Optional[str] = None
    with _key_lock:
        if _processing:
            return
        if _state == _state_idle:
            ch0 = _pynput_key_char(key)
            if _try_advance_trigger(ch0):
                if DEBUG_KEYS:
                    _log("[easify] capture mode ON (pynput)")
                _state = _state_capturing
                _capture = []
            return
        if key == Key.enter:
            if DEBUG_KEYS:
                _log(f"[easify] submit: {''.join(_capture)!r}")
            run_prompt = "".join(_capture)
            _processing = True
            _state = _state_idle
            _capture = []
            _trigger_matched = 0
        else:
            ch = _pynput_key_char(key)
            if ch == "\b":
                if _capture:
                    _capture.pop()
            elif ch not in (None, "\n"):
                _capture.append(ch)
                if DEBUG_KEYS and len(_capture) <= 80:
                    _log(f"[easify] capture: {''.join(_capture)!r}")
    if run_prompt is not None:
        threading.Thread(target=_process_prompt_sync_bridge, args=(run_prompt,), daemon=True).start()


def _setup_keyboard_inject() -> None:
    global _delete_impl, _paste_impl

    def delete_n(n: int) -> None:
        delay = _BACKSPACE_DELAY_MS / 1000.0
        for _ in range(max(0, n)):
            keyboard.send("backspace")
            if delay:
                time.sleep(delay)

    def paste_text(_text: str) -> None:
        mod = "cmd" if platform.system() == "Darwin" else "ctrl"
        keyboard.send(f"{mod}+v")

    _delete_impl = delete_n
    _paste_impl = paste_text


def _setup_pynput_inject(ctrl: Any) -> None:
    global _delete_impl, _paste_impl
    from pynput.keyboard import Key

    mod_key = Key.cmd if platform.system() == "Darwin" else Key.ctrl

    def delete_n(n: int) -> None:
        global _inject_depth
        delay = _BACKSPACE_DELAY_MS / 1000.0
        _inject_depth += 1
        try:
            for _ in range(max(0, n)):
                ctrl.tap(Key.backspace)
                if delay:
                    time.sleep(delay)
        finally:
            _inject_depth -= 1

    def paste_text(_text: str) -> None:
        global _inject_depth
        _inject_depth += 1
        try:
            with ctrl.pressed(mod_key):
                ctrl.press("v")
                ctrl.release("v")
        finally:
            _inject_depth -= 1

    _delete_impl = delete_n
    _paste_impl = paste_text


def _resolved_backend() -> str:
    if _RAW_BACKEND == "auto":
        return "pynput" if platform.system() == "Darwin" else "keyboard"
    return _RAW_BACKEND


def _require_root_macos_keyboard() -> None:
    if platform.system() != "Darwin":
        return
    if os.geteuid() == 0:
        return
    _log("[easify] keyboard backend on macOS needs sudo, or use pynput (default on macOS).")
    sys.exit(1)


def load_snippets_from_disk() -> None:
    global _SNIPPETS
    alt = os.path.join(os.getcwd(), "snippets.json")
    if os.path.isfile(SNIPPETS_PATH):
        _SNIPPETS = snippets_mod.load_snippets(SNIPPETS_PATH)
    elif os.path.isfile(alt):
        _SNIPPETS = snippets_mod.load_snippets(alt)
    else:
        _SNIPPETS = {}


def run() -> None:
    _require_trigger()
    load_snippets_from_disk()

    stop = threading.Event()

    def _stop(*_: object) -> None:
        stop.set()

    backend = _resolved_backend()
    if backend == "keyboard":
        _require_root_macos_keyboard()

    _start_async_worker()

    _log(
        "Easify — LLM text expander\n"
        f"  • Backend: {backend}\n"
        f"  • Trigger: {TRIGGER!r}\n"
        f"  • Snippets: {len(_SNIPPETS)} entries"
        f" ({SNIPPETS_PATH if os.path.isfile(SNIPPETS_PATH) else 'cwd/snippets.json if present'})\n"
        f"  • Model: {DEFAULT_MODEL}\n"
        f"  • Clipboard restore after paste: {_CLIPBOARD_RESTORE}\n"
        "  • Quit: Ctrl+C\n"
    )

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    listener: Any = None
    try:
        if backend == "pynput":
            from pynput.keyboard import Controller, Listener

            ctrl = Controller()
            _setup_pynput_inject(ctrl)
            listener = Listener(on_press=_pynput_on_press)
            listener.start()
            _log("[easify] listening (pynput)…")
        else:
            _setup_keyboard_inject()
            keyboard.hook(_on_key_keyboard, suppress=False)
            time.sleep(0.6)
            t = getattr(keyboard._listener, "listening_thread", None)
            if t is not None and not t.is_alive():
                _log("[easify] keyboard listener died.")
                sys.exit(1)
            _log("[easify] listening (keyboard)…")

        while not stop.wait(timeout=0.25):
            pass
    finally:
        if listener is not None:
            listener.stop()
        if backend == "keyboard":
            keyboard.unhook_all()
