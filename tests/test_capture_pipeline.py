import asyncio
from pathlib import Path

import httpx
import pytest

from app.ai.chat_provider import OllamaChatProvider
from app.ai.ollama import OllamaClient
from app.autocorrect.engine import AutocorrectEngine
from app.cache.service import CacheService
from app.cache.store import SqliteExpansionCache
from app.engine.expansion_contracts import ExpansionLayer
from app.engine.l0_compute import FxRateCache
from app.engine.events import CaptureSubmitPayload, EngineEventType
from app.engine.pipeline import ExpansionPipeline
from app.keyboard import buffer as input_buffer
from app.pipelines.capture_pipeline import capture_result_from_outcome, run_capture_expand_async
from app.snippets.engine import SnippetEngine


def test_compute_capture_submit_metadata():
    m = input_buffer.compute_capture_submit_metadata(
        raw_buf="hello//",
        close="//",
        from_prefix=True,
        use_prefix_trigger=True,
        trigger="//",
        enter_backspaces=1,
        entered_with_newline=False,
    )
    assert m is not None
    run_prompt, dc, undo = m
    assert run_prompt == "hello"
    assert "//" in undo
    assert input_buffer.compute_capture_submit_metadata(
        raw_buf="  ",
        close="",
        from_prefix=False,
        use_prefix_trigger=False,
        trigger="",
        enter_backspaces=0,
        entered_with_newline=True,
    ) is None


def test_buffer_capture_submit_event():
    ev = input_buffer.capture_submit(
        capture_text="hello",
        delete_count=5,
        undo_restore="//hello//",
        prior_words="a b",
        focused_app_at_submit="Notes",
    )
    assert ev.type is EngineEventType.CAPTURE_SUBMIT
    assert isinstance(ev.payload, CaptureSubmitPayload)
    assert ev.payload.capture_text == "hello"
    assert ev.payload.delete_count == 5
    assert ev.payload.focused_app_at_submit == "Notes"


def test_capture_result_from_outcome_cache_hit():
    from app.engine.expansion_contracts import ExpansionOutcome

    r = capture_result_from_outcome(
        ExpansionOutcome("x", ExpansionLayer.L2_CACHE.value, 12.3),
        citation_mode=True,
    )
    assert r.text == "x"
    assert r.source == ExpansionLayer.L2_CACHE.value
    assert r.cached is True
    assert r.citation_mode is True
    assert "cache" in r.stages_run
    assert r.latency_ms["total"] == pytest.approx(12.3)


def test_capture_result_from_outcome_l3_includes_store_when_text():
    from app.engine.expansion_contracts import ExpansionOutcome

    r = capture_result_from_outcome(
        ExpansionOutcome("out", "L3-ollama", 100.0),
        citation_mode=False,
    )
    assert "ai_generate" in r.stages_run
    assert "store_cache" in r.stages_run


@pytest.mark.parametrize("layer,expect_cached", [(ExpansionLayer.L2_CACHE.value, True), ("L1-snippet-exact", False)])
def test_capture_cached_flag(layer: str, expect_cached: bool):
    from app.engine.expansion_contracts import ExpansionOutcome

    r = capture_result_from_outcome(ExpansionOutcome("t", layer, 1.0), citation_mode=False)
    assert r.cached is expect_cached


def test_run_capture_expand_async_snippet(tmp_path: Path) -> None:
    sn = tmp_path / "s.json"
    sn.write_text('{"hi": "hello"}', encoding="utf-8")
    snippets = SnippetEngine([sn])
    ac = AutocorrectEngine(None)
    store = SqliteExpansionCache(tmp_path / "db.sqlite")
    cache = CacheService(store)
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
            return await run_capture_expand_async(pipe, "hi", client)

    cap = asyncio.run(_run())
    assert cap.text == "hello"
    assert cap.source == ExpansionLayer.L1_SNIPPET_EXACT.value
    assert cap.cached is False
    assert "snippet_exact" in cap.stages_run
    store.close()
