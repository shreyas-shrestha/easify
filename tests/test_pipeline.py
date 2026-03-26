import asyncio
from pathlib import Path

import httpx

from app.ai.chat_provider import OllamaChatProvider
from app.ai.ollama import OllamaClient
from app.autocorrect.engine import AutocorrectEngine
from app.cache.store import SqliteExpansionCache
from app.engine.l0_compute import FxRateCache
from app.engine.pipeline import ExpansionPipeline
from app.snippets.engine import SnippetEngine


def test_pipeline_snippet_instant(tmp_path: Path) -> None:
    sn = tmp_path / "s.json"
    sn.write_text('{"hi": "hello"}', encoding="utf-8")
    snippets = SnippetEngine([sn])
    ac = AutocorrectEngine(None)
    cache = SqliteExpansionCache(tmp_path / "db.sqlite")
    fx = FxRateCache(tmp_path / "fx.json")
    llm = OllamaChatProvider(OllamaClient("http://127.0.0.1:9/nope", "noop", timeout_s=0.1, retries=0))
    pipe = ExpansionPipeline(
        snippets=snippets,
        autocorrect=ac,
        cache=cache,
        llm=llm,
        fx_cache=fx,
    )

    async def _run() -> object:
        async with httpx.AsyncClient() as client:
            return await pipe.expand("hi", client)

    out = asyncio.run(_run())
    assert out.layer == "L1-snippet-exact"
    assert out.text == "hello"


def test_pipeline_snippet_expands_date_placeholder(tmp_path: Path) -> None:
    sn = tmp_path / "s.json"
    sn.write_text('{"sig": "— {date:%Y}"}', encoding="utf-8")
    snippets = SnippetEngine([sn])
    ac = AutocorrectEngine(None)
    cache = SqliteExpansionCache(tmp_path / "db.sqlite")
    fx = FxRateCache(tmp_path / "fx.json")
    llm = OllamaChatProvider(OllamaClient("http://127.0.0.1:9/nope", "noop", timeout_s=0.1, retries=0))
    pipe = ExpansionPipeline(
        snippets=snippets,
        autocorrect=ac,
        cache=cache,
        llm=llm,
        fx_cache=fx,
    )

    async def _run() -> object:
        async with httpx.AsyncClient() as client:
            return await pipe.expand("sig", client, clipboard_snippet="")

    out = asyncio.run(_run())
    assert out.layer == "L1-snippet-exact"
    assert out.text.startswith("— 20") and len(out.text) == 6
