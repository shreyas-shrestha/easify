"""macOS input-monitoring preflight."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.utils import darwin_permissions


def test_preflight_is_ok_off_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(darwin_permissions.platform, "system", lambda: "Linux")

    result = darwin_permissions.preflight_input_monitoring()

    assert result.ok is True
    assert result.message == ""


def test_preflight_uses_quartz_listen_access_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    quartz = SimpleNamespace(
        CGPreflightListenEventAccess=lambda: False,
        CGPreflightPostEventAccess=lambda: True,
    )

    monkeypatch.setattr(darwin_permissions.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(darwin_permissions, "_import_hiservices", lambda: None)
    monkeypatch.setattr(darwin_permissions, "_import_quartz", lambda: quartz)

    result = darwin_permissions.preflight_input_monitoring()

    assert result.ok is False
    assert "Input Monitoring" in result.message


def test_preflight_uses_accessibility_trust_when_available(monkeypatch: pytest.MonkeyPatch) -> None:
    hiservices = SimpleNamespace(AXIsProcessTrusted=lambda: False)

    monkeypatch.setattr(darwin_permissions.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(darwin_permissions, "_import_hiservices", lambda: hiservices)

    result = darwin_permissions.preflight_input_monitoring()

    assert result.ok is False
    assert "Accessibility" in result.message
