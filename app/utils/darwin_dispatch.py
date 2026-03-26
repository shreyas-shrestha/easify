"""Schedule work on the Darwin main dispatch queue (for AppKit / AX safety)."""

from __future__ import annotations

import ctypes
import platform
import threading
from collections import deque
from ctypes import CFUNCTYPE, c_void_p
from typing import Callable, Deque, Optional

from app.utils.log import get_logger

LOG = get_logger(__name__)

_jobs: Deque[Callable[[], None]] = deque()
_jobs_lock = threading.Lock()
_dispatch_trampoline: Optional[object] = None


def _trampoline(_ctx: c_void_p) -> None:  # noqa: ARG001
    gil = ctypes.pythonapi.PyGILState_Ensure()
    try:
        with _jobs_lock:
            if not _jobs:
                return
            job = _jobs.popleft()
        job()
    finally:
        ctypes.pythonapi.PyGILState_Release(gil)


def run_on_darwin_main_thread(work: Callable[[], None]) -> None:
    """Enqueue ``work`` on libdispatch's main queue. Safe to call from pynput / thread-pool threads.

    Requires something on the process main thread to run a CoreFoundation / AppKit run loop
    (e.g. ``pystray`` ``icon.run()`` on macOS). If ``dispatch_async_f`` is unavailable, runs
    ``work()`` synchronously on the current thread and logs a warning.
    """
    if platform.system() != "Darwin":
        work()
        return
    global _dispatch_trampoline
    with _jobs_lock:
        _jobs.append(work)
        pending = work
    if _dispatch_trampoline is None:
        _dispatch_trampoline = CFUNCTYPE(None, c_void_p)(_trampoline)
    try:
        lib = ctypes.CDLL("/usr/lib/system/libdispatch.dylib")
        lib.dispatch_async_f.argtypes = [c_void_p, c_void_p, CFUNCTYPE(None, c_void_p)]
        lib.dispatch_async_f.restype = None
        # Newer macOS builds may not export dispatch_get_main_queue via dlsym.
        # _dispatch_main_q is the underlying queue object and is exported.
        try:
            mq = c_void_p.in_dll(lib, "_dispatch_main_q").value
        except Exception:
            lib.dispatch_get_main_queue.restype = c_void_p
            lib.dispatch_get_main_queue.argtypes = []
            mq = lib.dispatch_get_main_queue()
        if not mq:
            raise RuntimeError("main dispatch queue unavailable")
        lib.dispatch_async_f(c_void_p(mq), None, _dispatch_trampoline)
    except Exception as e:
        with _jobs_lock:
            if _jobs and _jobs[-1] is pending:
                _jobs.pop()
        LOG.warning("main-queue dispatch failed (%s) — running inline (AX may be unsafe)", e)
        work()
