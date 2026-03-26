from unittest.mock import MagicMock, patch

from app.cli.doctor import gather_doctor_report
from app.config.settings import Settings


def test_gather_doctor_report_has_schema(monkeypatch) -> None:
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
        report = gather_doctor_report(s)

    assert "checks" in report
    assert "l3_probe" in report
    assert "summary" in report
    assert report["summary"]["fail"] == 0
    assert report["l3_probe"]["ollama_reachable"] is True
    assert "easify_version" in report
    assert "exit_code" not in report


def test_gather_doctor_report_openai_fail(monkeypatch) -> None:
    monkeypatch.setenv("EASIFY_AI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("EASIFY_OPENAI_API_KEY", raising=False)
    s = Settings.load()
    report = gather_doctor_report(s)
    assert report["summary"]["fail"] >= 1
