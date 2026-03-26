from app.cli.l3_probe import ollama_tags_url


def test_ollama_tags_url_default() -> None:
    assert ollama_tags_url("http://127.0.0.1:11434/api/generate") == "http://127.0.0.1:11434/api/tags"


def test_ollama_tags_url_custom_host() -> None:
    assert ollama_tags_url("http://blob:11434/v1/whatever") == "http://blob:11434/api/tags"
