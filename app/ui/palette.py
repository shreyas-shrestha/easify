"""Floating capture palette (tkinter) — single worker thread, one Tk root (macOS-safe)."""

from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING

from app.engine.service import ExpansionJob
from app.utils.log import get_logger

LOG = get_logger(__name__)

if TYPE_CHECKING:
    from app.config.settings import Settings
    from app.engine.service import ExpansionService

_palette_queue: queue.Queue[str] | None = None
_palette_thread: threading.Thread | None = None
_palette_lock = threading.Lock()


def start_palette_worker(service: "ExpansionService", settings: "Settings") -> None:
    """Call once when palette hotkey is enabled. Owns the only Tk root in this process."""
    global _palette_queue, _palette_thread
    with _palette_lock:
        if _palette_thread is not None and _palette_thread.is_alive():
            return
        _palette_queue = queue.Queue()
        _palette_thread = threading.Thread(
            target=_palette_mainloop,
            args=(service, settings, _palette_queue),
            daemon=True,
            name="easify-palette",
        )
        _palette_thread.start()
        LOG.info("palette worker thread started")


def enqueue_palette_request(prior_words: str) -> None:
    if _palette_queue is None:
        LOG.warning("palette worker not started")
        return
    _palette_queue.put(prior_words or "")


def _palette_mainloop(
    service: "ExpansionService",
    settings: "Settings",
    q: queue.Queue[str],
) -> None:
    import tkinter as tk

    _ = settings
    try:
        root = tk.Tk()
    except tk.TclError as e:
        LOG.warning("palette: no display (%s)", e)
        return
    root.withdraw()
    state: dict[str, object] = {"win": None}

    def pump() -> None:
        try:
            pw = q.get_nowait()
        except queue.Empty:
            root.after(80, pump)
            return
        w = state["win"]
        if w is not None:
            try:
                alive = w.winfo_exists()
            except tk.TclError:
                alive = False
            if alive:
                try:
                    w.lift()
                    w.focus_force()
                except tk.TclError:
                    state["win"] = None
                else:
                    root.after(0, pump)
                    return
            state["win"] = None
        _open_palette_window(root, service, pw, state, on_done=lambda: root.after(0, pump))

    root.after(0, pump)
    try:
        root.mainloop()
    except Exception as e:
        LOG.warning("palette mainloop: %s", e)


def _open_palette_window(
    root,
    service: "ExpansionService",
    prior_words: str,
    state: dict[str, object],
    *,
    on_done: object,
) -> None:
    import tkinter as tk

    win = tk.Toplevel(root)
    state["win"] = win
    win.title("Easify — expansion")
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass
    var = tk.StringVar()
    entry = tk.Entry(win, textvariable=var, width=64)
    entry.pack(padx=14, pady=14, fill="x")

    def close_and_continue() -> None:
        state["win"] = None
        try:
            on_done()
        except Exception as e:
            LOG.debug("palette on_done: %s", e)

    def submit() -> None:
        text = var.get().strip()
        try:
            win.destroy()
        except tk.TclError:
            pass
        if text:
            service.submit(ExpansionJob(capture=text, delete_count=0, prior_words=prior_words))
        close_and_continue()

    def cancel() -> None:
        try:
            win.destroy()
        except tk.TclError:
            pass
        close_and_continue()

    win.bind("<Return>", lambda _e: submit())
    win.bind("<Escape>", lambda _e: cancel())
    btn = tk.Frame(win)
    btn.pack(pady=(0, 12))
    tk.Button(btn, text="Expand", command=submit, width=12).pack(side="left", padx=6)
    tk.Button(btn, text="Cancel", command=cancel, width=12).pack(side="left", padx=6)
    win.protocol("WM_DELETE_WINDOW", cancel)
    entry.focus_set()
    win.lift()
