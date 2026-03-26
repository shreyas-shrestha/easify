from pathlib import Path

from app.snippets.engine import SnippetEngine


def test_exact_before_fuzzy(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    a.write_text('{"hello": "HELLO", "hallo": "no"}', encoding="utf-8")
    eng = SnippetEngine([a], fuzzy_score_cutoff=70)
    h = eng.resolve_exact("hello")
    assert h is not None and h.value == "HELLO"


def test_autocorrect_phrase() -> None:
    from app.autocorrect.engine import AutocorrectEngine

    p = Path(__file__).resolve().parents[1] / "app" / "bundled" / "autocorrect.json"
    eng = AutocorrectEngine(p)
    assert "the" in eng.apply_to_phrase("teh cat")
