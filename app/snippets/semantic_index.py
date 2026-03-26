"""Optional embedding similarity over snippet keys (Phase 3)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.snippets.engine import SnippetEngine, SnippetHit
from app.utils.log import get_logger

if TYPE_CHECKING:
    from app.config.settings import Settings

LOG = get_logger(__name__)


class SnippetSemanticIndex:
    """Lazy-built key embeddings; skipped if sentence-transformers unavailable."""

    def __init__(self, snippets: SnippetEngine, settings: "Settings") -> None:
        self._snippets = snippets
        self._model_id = (settings.semantic_model or "sentence-transformers/all-MiniLM-L6-v2").strip()
        self._min_sim = max(0.05, min(0.99, float(settings.semantic_min_similarity)))
        self._namespace_lenient = bool(settings.snippet_namespace_lenient)
        self._model = None
        self._keys: list[str] = []
        self._emb = None
        self._mtime = -1.0

    def _try_import(self):  # noqa: ANN201
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

            return SentenceTransformer
        except ImportError:
            LOG.warning(
                "semantic snippets enabled but sentence-transformers not installed; "
                "install `easify[semantic]` or `pip install sentence-transformers`"
            )
            return None

    def _rebuild(self) -> None:
        ST = self._try_import()
        self._snippets.maybe_reload()
        self._mtime = float(self._snippets.content_version)
        if ST is None:
            self._keys = []
            self._emb = None
            return
        store = self._snippets.iter_snippets()
        self._keys = list(store.keys())
        if not self._keys:
            self._emb = None
            return
        if self._model is None:
            LOG.info("loading semantic model %s", self._model_id)
            self._model = ST(self._model_id)
        texts = [self._display_key(k) for k in self._keys]
        self._emb = self._model.encode(texts, convert_to_numpy=True, show_progress_bar=False)

    @staticmethod
    def _display_key(k: str) -> str:
        return k.replace(":", " ")

    def _sync(self) -> None:
        self._snippets.maybe_reload()
        if float(self._snippets.content_version) != self._mtime or self._emb is None:
            self._rebuild()

    def find_best(self, query: str, focused_app: str) -> Optional[SnippetHit]:
        q = (query or "").strip()
        if not q:
            return None
        self._sync()
        if self._emb is None or not self._keys:
            return None
        import numpy as np  # type: ignore[import-untyped]

        assert self._model is not None
        qv = self._model.encode([q], convert_to_numpy=True, show_progress_bar=False)[0]
        qn = np.linalg.norm(qv) or 1.0
        best_i = -1
        best_s = -1.0
        for i, key in enumerate(self._keys):
            if not self._snippets.key_visible_for_focus(key, focused_app, lenient=self._namespace_lenient):
                continue
            row = self._emb[i]
            rn = float(np.linalg.norm(row)) or 1.0
            sim = float(np.dot(qv, row) / (qn * rn))
            if sim > best_s:
                best_s = sim
                best_i = i
        if best_i < 0 or best_s < self._min_sim:
            return None
        key = self._keys[best_i]
        val = self._snippets.get_value(key)
        if val is None:
            return None
        return SnippetHit(layer=3, key=key, value=val, score=best_s * 100.0)
