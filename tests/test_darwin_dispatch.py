"""darwin_dispatch: off-macOS runs work inline."""

from __future__ import annotations

import pytest

from app.utils import darwin_dispatch


def test_run_on_main_thread_non_darwin_runs_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(darwin_dispatch.platform, "system", lambda: "Linux")
    ran: list[int] = []

    def work() -> None:
        ran.append(1)

    darwin_dispatch.run_on_darwin_main_thread(work)
    assert ran == [1]
