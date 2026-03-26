"""Floating capture palette (tkinter) — submit expansions without typing the prefix."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.engine.service import ExpansionJob
from app.utils.log import get_logger

LOG = get_logger(__name__)

if TYPE_CHECKING:
    from app.config.settings import Settings
    from app.engine.service import ExpansionService


def open_expansion_palette(
    service: "ExpansionService",
    settings: "Settings",
    *,
    prior_words: str = "",
) -> None:
    import tkinter as tk

    _ = settings  # reserved for future (preview, model label)
    try:
        root = tk.Tk()
    except tk.TclError as e:
        LOG.warning("no display for palette (%s)", e)
        return
    root.withdraw()
    win = tk.Toplevel(root)
    win.title("Easify — expansion")
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass
    var = tk.StringVar()
    entry = tk.Entry(win, textvariable=var, width=64)
    entry.pack(padx=14, pady=14, fill="x")

    def submit() -> None:
        text = var.get().strip()
        win.destroy()
        root.quit()
        root.destroy()
        if text:
            service.submit(ExpansionJob(capture=text, delete_count=0, prior_words=prior_words))

    def cancel() -> None:
        win.destroy()
        root.quit()
        root.destroy()

    win.bind("<Return>", lambda _e: submit())
    win.bind("<Escape>", lambda _e: cancel())
    btn = tk.Frame(win)
    btn.pack(pady=(0, 12))
    tk.Button(btn, text="Expand", command=submit, width=12).pack(side="left", padx=6)
    tk.Button(btn, text="Cancel", command=cancel, width=12).pack(side="left", padx=6)
    entry.focus_set()
    win.lift()
    root.mainloop()
