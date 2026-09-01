"""darwin_dispatch: off-macOS runs work inline; on macOS targets the real main queue."""

from __future__ import annotations

import ctypes
import platform

import pytest

from app.utils import darwin_dispatch


def test_run_on_main_thread_non_darwin_runs_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(darwin_dispatch.platform, "system", lambda: "Linux")
    ran: list[int] = []

    def work() -> None:
        ran.append(1)

    darwin_dispatch.run_on_darwin_main_thread(work)
    assert ran == [1]


@pytest.mark.skipif(platform.system() != "Darwin", reason="macOS-only")
def test_dispatches_to_address_of_main_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queue argument must be &_dispatch_main_q, not the isa pointer stored there.

    Passing the contents instead of the address hands libdispatch an Objective-C class
    pointer, which it dereferences into a SIGBUS on the main thread.
    """
    real = ctypes.CDLL("/usr/lib/system/libdispatch.dylib")
    calls: list[int | None] = []

    class RecordingLib:
        _handle = real._handle

        class dispatch_async_f:  # noqa: N801 - mimics a ctypes function attribute
            argtypes: object = None
            restype: object = None

            def __call__(self, queue, ctx, fn) -> None:  # noqa: ANN001
                calls.append(queue.value)

        dispatch_async_f = dispatch_async_f()  # type: ignore[assignment]

    monkeypatch.setattr(darwin_dispatch.ctypes, "CDLL", lambda _path: RecordingLib())
    try:
        darwin_dispatch.run_on_darwin_main_thread(lambda: None)
    finally:
        darwin_dispatch._jobs.clear()  # the faked dispatch never drains the queue

    expected = ctypes.addressof(ctypes.c_void_p.in_dll(real, "_dispatch_main_q"))
    assert calls == [expected]
    # Guard against the regression specifically: the contents are a different address.
    assert ctypes.c_void_p.in_dll(real, "_dispatch_main_q").value != expected
