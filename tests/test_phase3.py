from pathlib import Path

from app.cache.store import SqliteExpansionCache
from app.snippets.engine import SnippetEngine
from app.snippets.promote import maybe_promote_cache_hit, promote_key_for_line


def test_namespace_snippets_focus(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text('{"slack:thanks": "TY", "thanks": "plain"}', encoding="utf-8")
    eng = SnippetEngine([p])
    assert eng.resolve_exact("slack:thanks", focused_app="", namespace_lenient=False) is None
    hit = eng.resolve_exact("slack:thanks", focused_app="Slack", namespace_lenient=False)
    assert hit is not None and hit.value == "TY"
    hit2 = eng.resolve_exact("slack:thanks", focused_app="", namespace_lenient=True)
    assert hit2 is not None
    assert eng.resolve_exact("thanks", focused_app="", namespace_lenient=False) is not None


def test_cache_lookup_increments(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    c = SqliteExpansionCache(db)
    c.put("m", "user line", "OUT", source="ai")
    t1, h1, s1 = c.lookup("m", "user line")
    assert t1 == "OUT" and s1 == "ai" and h1 >= 2
    _, h2, _ = c.lookup("m", "user line")
    assert h2 > h1


def test_promote_slug() -> None:
    assert "promoted-" in promote_key_for_line("Hello World")


def test_promote_writes_user_snippets(tmp_path: Path) -> None:
    user = tmp_path / "snippets.json"
    cfg = tmp_path
    prompt = "phi\nsys\nmy test phrase"
    did = maybe_promote_cache_hit(
        user_snippets=user,
        config_dir=cfg,
        cache_prompt=prompt,
        response="expanded text",
        hit_count=5,
        source="ai",
        min_hits=3,
        allowed_sources=frozenset({"ai", "bg"}),
    )
    assert did is True
    assert user.is_file()
    eng = SnippetEngine([user])
    k = promote_key_for_line("my test phrase")
    hit = eng.resolve_exact(k)
    assert hit is not None and hit.value == "expanded text"
    did2 = maybe_promote_cache_hit(
        user_snippets=user,
        config_dir=cfg,
        cache_prompt=prompt,
        response="expanded text",
        hit_count=99,
        source="ai",
        min_hits=3,
        allowed_sources=frozenset({"ai", "bg"}),
    )
    assert did2 is False
