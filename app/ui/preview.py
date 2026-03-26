"""Optional tkinter preview before injecting an expansion."""

from __future__ import annotations

from app.utils.log import get_logger

LOG = get_logger(__name__)


def confirm_expansion(text: str, title: str = "Easify — preview") -> bool:
    """Modal accept/reject; returns True if user accepts. Always False on error."""
    try:
        import tkinter as tk
        from tkinter import scrolledtext
    except ImportError:
        LOG.warning("tkinter unavailable — skipping preview")
        return True

    result = {"ok": False}
    root = tk.Tk()
    root.withdraw()
    win = tk.Toplevel(root)
    win.title(title)
    try:
        win.attributes("-topmost", True)
    except tk.TclError:
        pass

    lbl = tk.Label(win, text="Enter = inject   Esc = cancel", font=("TkDefaultFont", 10))
    lbl.pack(padx=10, pady=(10, 4))

    h = min(18, max(6, text.count("\n") + 3))
    box = scrolledtext.ScrolledText(win, width=80, height=h, wrap="word")
    box.pack(padx=10, pady=6, fill="both", expand=True)
    box.insert("1.0", text)
    box.config(state="disabled")

    def accept() -> None:
        result["ok"] = True
        win.destroy()
        root.quit()

    def reject() -> None:
        result["ok"] = False
        win.destroy()
        root.quit()

    win.bind("<Return>", lambda _e: accept())
    win.bind("<Escape>", lambda _e: reject())

    btns = tk.Frame(win)
    btns.pack(pady=(4, 12))
    tk.Button(btns, text="Inject", command=accept, width=12).pack(side="left", padx=6)
    tk.Button(btns, text="Cancel", command=reject, width=12).pack(side="left", padx=6)

    win.protocol("WM_DELETE_WINDOW", reject)
    box.focus_set()
    win.lift()
    root.mainloop()
    try:
        root.destroy()
    except tk.TclError:
        pass
    return bool(result["ok"])
