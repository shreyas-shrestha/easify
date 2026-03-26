from unittest.mock import MagicMock, patch

import httpx

from app.cli.l3_probe import ollama_tags_url, probe_l3_backend
from app.config.settings import Settings


def test_ollama_tags_url_default() -> None:
    assert ollama_tags_url("http://127.0.0.1:11434/api/generate") == "http://127.0.0.1:11434/api/tags"


def test_probe_openai_no_key(monkeypatch) -> None:
    monkeypatch.setenv("EASIFY_AI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("EASIFY_OPENAI_API_KEY", raising=False)
    s = Settings.load()
    out = probe_l3_backend(s, httpx_timeout=1.0)
    assert len(out.issues) == 1
    assert out.issues[0].level == "fail"


def test_probe_ollama_ok(monkeypatch) -> None:
    monkeypatch.setenv("EASIFY_AI_PROVIDER", "ollama")
    monkeypatch.setenv("EASIFY_MODEL", "phi3")
    s = Settings.load()

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"models": [{"name": "phi3:latest"}]}

    with patch("httpx.Client") as client_cls:
        inst = MagicMock()
        client_cls.return_value.__enter__.return_value = inst
        inst.get.return_value = mock_resp
        out = probe_l3_backend(s, httpx_timeout=1.0)

    assert out.ollama_reachable is True
    assert not out.issues


def test_probe_ollama_network_error(monkeypatch) -> None:
    monkeypatch.setenv("EASIFY_AI_PROVIDER", "ollama")
    s = Settings.load()

    with patch("httpx.Client") as client_cls:
        inst = MagicMock()
        client_cls.return_value.__enter__.return_value = inst
        inst.get.side_effect = httpx.ConnectError("refused")
        out = probe_l3_backend(s, httpx_timeout=1.0)

    assert not out.ollama_reachable
    assert len(out.issues) == 1
    assert out.issues[0].level == "fail"
