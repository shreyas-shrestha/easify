"""Global pynput listener — prefix / double-space capture + optional live word buffer."""

from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import TYPE_CHECKING, Callable, Iterator, Optional

if TYPE_CHECKING:
    from app.engine.engine import EasifyEngine

from pynput.keyboard import Controller, Key, Listener

from app.config.settings import Settings
from app.context.focus import get_focused_app_name_fresh
from app.engine.buffer import CaptureBuffer, TriggerState
from app.keyboard import buffer as input_buffer
from app.keyboard.capture_fsm import CaptureInputSession, CapturingKeyKind, PrefixTriggerResult
from app.engine.guards import is_safe_phrase_tokens, is_safe_word, text_suggests_ime_mid_composition
from app.engine.live_word import LiveFixCooldown, LiveWordResolver
from app.engine.service import ExpansionJob, ExpansionService
from app.keyboard.keys import pynput_key_char, pynput_skip_key
from app.utils import clipboard as cb
from app.utils.log import get_logger

LOG = get_logger(__name__)


class KeyboardListener:
    def __init__(
        self,
        *,
        service: ExpansionService,
        settings: Settings,
        trigger: str,
        enter_backspaces: int,
        debug: bool = False,
    ) -> None:
        self.service = service
        self.settings = settings
        self.trigger = trigger
        self.enter_backspaces = enter_backspaces
        self.debug = debug
        self._trigger = TriggerState()
        self._capture = CaptureBuffer(max_chars=settings.capture_max_chars)
        self._listener_io_lock = threading.Lock()
        self._recent_chars: deque[str] = deque(maxlen=16)
        self._capture_session = CaptureInputSession(
            settings,
            self._capture,
            self._trigger,
            self._recent_chars,
        )
        self._inject_depth = 0
        self._inject_depth_lock = threading.Lock()
        self._listener: Optional[Listener] = None
        self._ctrl: Optional[Controller] = None
        self._delete_n: Optional[Callable[[int], None]] = None
        self._paste_text: Optional[Callable[[str], None]] = None

        self._rolling_words: Optional[deque[str]] = (
            deque(maxlen=settings.context_buffer_words) if settings.context_buffer_words > 0 else None
        )
        self._ctx_chars: list[str] = []

        self._live_resolver: Optional[LiveWordResolver] = None
        self._live_chars: list[str] = []
        self._phrase_deque: Optional[deque[str]] = (
            deque(maxlen=settings.phrase_buffer_max) if settings.phrase_buffer_max > 0 else None
        )
        self._live_cooldown = LiveFixCooldown(settings.live_cooldown_ms / 1000.0)
        self._live_replace_lock = threading.Lock()
        self._easify_engine: Optional["EasifyEngine"] = None
        # Live «no //» path: word/phrase replace on Space. With EASIFY_ENGINE_V2, EasifyEngine handles resolution.
        if settings.engine_v2:
            self._live_resolver = None
        elif (
            settings.live_autocorrect
            or settings.live_fuzzy
            or settings.live_cache
            or settings.live_cache_enrich
            or settings.phrase_buffer_max > 0
        ):
            self._live_resolver = LiveWordResolver(
                snippets=service.snippets,
                autocorrect=service.autocorrect,
                cache=service.cache_service,
                model=service.cache_model_id,
                min_word_len=settings.live_min_word_len,
                fuzzy_enabled=settings.live_fuzzy,
                cache_enabled=settings.live_cache,
                fuzzy_threshold=settings.live_fuzzy_threshold,
                perf=settings.perf,
            )

    def _live_capable(self) -> bool:
        if self.settings.engine_v2 and self._easify_engine is not None:
            return True
        return self._live_resolver is not None

    def _inject_depth_get(self) -> int:
        with self._inject_depth_lock:
            return self._inject_depth

    @contextmanager
    def _inject_depth_hold(self) -> Iterator[None]:
        with self._inject_depth_lock:
            self._inject_depth += 1
        try:
            yield
        finally:
            with self._inject_depth_lock:
                self._inject_depth -= 1

    def _live_clear(self) -> None:
        self._live_chars.clear()
        if self._phrase_deque is not None:
            self._phrase_deque.clear()

    def _push_rolling_word(self, word: str) -> None:
        w = word.strip()
        if not w or self._rolling_words is None:
            return
        self._rolling_words.append(w)

    def _context_idle_key(self, ch: Optional[str]) -> None:
        if self._rolling_words is None:
            return
        if ch == "\b":
            if self._ctx_chars:
                self._ctx_chars.pop()
            return
        if ch is not None and len(ch) == 1 and ch.isalpha():
            self._ctx_chars.append(ch)
            return
        if ch in (" ", "\n"):
            w = "".join(self._ctx_chars).strip()
            self._ctx_chars.clear()
            if w:
                self._rolling_words.append(w)
            return
        self._ctx_chars.clear()

    def _prior_context_string(self) -> str:
        if not self._rolling_words:
            return ""
        return " ".join(self._rolling_words)

    def _handle_live_key(self, key: object, ch: Optional[str]) -> None:
        if not self._live_capable():
            return
        if ch == "\b":
            if self._live_chars:
                self._live_chars.pop()
            return
        if ch is not None and len(ch) == 1 and ch.isalpha():
            self._live_chars.append(ch)
            return
        if ch in (" ", "\n"):
            self._live_flush()
            return
        # Word boundary without space: "hello," should still push "hello" for rolling context + live resolve.
        if self._live_chars and ch is not None and len(ch) == 1 and ch in ",.;:!?)]}\"'":
            self._live_flush()
            return
        self._live_clear()

    def _live_flush(self) -> None:
        if not self._live_capable():
            self._live_clear()
            return
        word = "".join(self._live_chars)
        self._live_chars.clear()
        if not word.strip():
            if self._phrase_deque is not None:
                self._phrase_deque.clear()
            return
        self._push_rolling_word(word)
        if text_suggests_ime_mid_composition(word):
            if self._phrase_deque is not None:
                self._phrase_deque.append(word)
            LOG.debug("live fix skipped: possible IME / script composition in %r", word[:48])
            return
        if not self._live_cooldown.can_fix():
            return
        if self.settings.engine_v2 and self._easify_engine is not None:
            if self._phrase_deque is not None:
                self._phrase_deque.append(word)
                if len(self._phrase_deque) >= 2:
                    phrase = " ".join(self._phrase_deque)
                    replaced = self._easify_engine.handle_event(input_buffer.live_phrase_completed(phrase))
                    if replaced:
                        self._phrase_deque.clear()
                        self._live_cooldown.mark()
                        return
            replaced = self._easify_engine.handle_event(input_buffer.live_word_completed(word))
            if replaced:
                if self._phrase_deque is not None:
                    self._phrase_deque.clear()
                self._live_cooldown.mark()
            return

        if self._phrase_deque is not None:
            self._phrase_deque.append(word)
            if len(self._phrase_deque) >= 2:
                phrase = " ".join(self._phrase_deque)
                rep = self._live_resolver.resolve_phrase(phrase)
                if rep and rep != phrase:
                    self._perform_live_replace(phrase, rep)
                    self._phrase_deque.clear()
                    self._live_cooldown.mark()
                    return
        rep = self._live_resolver.resolve(word)
        if rep and rep != word:
            self._perform_live_replace(word, rep)
            if self._phrase_deque is not None:
                self._phrase_deque.clear()
            self._live_cooldown.mark()
            return

        if self.settings.live_cache_enrich and self.settings.live_cache:
            if self._phrase_deque is not None and len(self._phrase_deque) >= 2:
                phrase = " ".join(self._phrase_deque)
                toks = phrase.split()
                if is_safe_phrase_tokens(toks, min_len=self.settings.live_min_word_len):
                    self.service.schedule_live_cache_enrich_phrase(phrase)
            elif is_safe_word(word, min_len=self.settings.live_min_word_len):
                self.service.schedule_live_cache_enrich_word(word)

    def _live_flush_context_only(self) -> None:
        """Update rolling / phrase buffers without live replace (expansion tail in flight)."""
        if not self._live_capable():
            self._live_clear()
            return
        word = "".join(self._live_chars)
        self._live_chars.clear()
        if not word.strip():
            if self._phrase_deque is not None:
                self._phrase_deque.clear()
            return
        self._push_rolling_word(word)
        if self._phrase_deque is not None:
            self._phrase_deque.append(word)

    def _handle_live_key_context_only(self, key: object, ch: Optional[str]) -> None:
        if not self._live_capable():
            return
        if ch == "\b":
            if self._live_chars:
                self._live_chars.pop()
            return
        if ch is not None and len(ch) == 1 and ch.isalpha():
            self._live_chars.append(ch)
            return
        if ch in (" ", "\n"):
            self._live_flush_context_only()
            return
        if self._live_chars and ch is not None and len(ch) == 1 and ch in ",.;:!?)]}\"'":
            self._live_flush_context_only()
            return
        self._live_clear()

    def _finalize_capture_submit(
        self,
        raw_buf: str,
        from_prefix: bool,
        *,
        entered_with_newline: bool,
    ) -> None:
        meta = input_buffer.compute_capture_submit_metadata(
            raw_buf=raw_buf,
            close=self.settings.capture_close.strip(),
            from_prefix=from_prefix,
            use_prefix_trigger=self.settings.use_prefix_trigger,
            trigger=self.trigger,
            enter_backspaces=self.enter_backspaces,
            entered_with_newline=entered_with_newline,
        )
        if meta is None:
            LOG.warning("empty intent — type between delimiters or press Enter")
            return
        run_prompt, dc, undo = meta
        if self.debug:
            LOG.debug("submit %r", run_prompt)
        focused = (
            get_focused_app_name_fresh()
            if self.settings.pre_inject_refocus
            else ""
        )
        if self.settings.engine_v2 and self._easify_engine is not None:
            self._easify_engine.handle_event(
                input_buffer.capture_submit(
                    capture_text=run_prompt,
                    delete_count=dc,
                    undo_restore=undo,
                    prior_words=self._prior_context_string(),
                    focused_app_at_submit=focused,
                )
            )
            return
        self.service.submit(
            ExpansionJob(
                capture=run_prompt,
                delete_count=dc,
                prior_words=self._prior_context_string(),
                undo_restore=undo,
                focused_app_at_submit=focused,
            )
        )

    def _enter_capture_from_double_space(self) -> None:
        if self._delete_n is None:
            return
        with self._inject_depth_hold():
            self._delete_n(2)
        self._capture_session.enter_from_double_space()
        self._live_clear()
        if self.debug:
            LOG.debug("capture mode (double-space)")
        LOG.info("capture mode (double-space)")

    def _perform_live_replace(self, old_word: str, new_text: str) -> None:
        if self._delete_n is None:
            return
        if text_suggests_ime_mid_composition(old_word):
            LOG.debug("live replace skipped: IME heuristic on token %r", old_word[:48])
            return
        parent = self
        ow, nt = old_word, new_text

        def _run() -> None:
            from app.inject.accessibility import focused_field_appears_secure

            if focused_field_appears_secure():
                LOG.debug("live replace skipped: secure/password field")
                return
            with parent._live_replace_lock:
                try:
                    with parent.service.inject_lock:
                        parent._delete_n(len(ow) + 1)
                    time.sleep(parent.settings.after_delete_ms / 1000.0)
                    with parent.service.inject_lock:
                        with parent._inject_depth_hold():
                            try:
                                parent._type_text(nt + " ")
                                if parent.service.metrics is not None:
                                    parent.service.metrics.incr("live_replacements")
                            except Exception as e:
                                LOG.warning("live type failed: %s", e)
                except Exception as e:
                    LOG.warning("live replace failed: %s", e)

        threading.Thread(target=_run, daemon=True, name="easify-live-replace").start()

    def _type_text(self, text: str) -> None:
        if self._ctrl is None:
            return
        typed = False
        if hasattr(self._ctrl, "type"):
            try:
                self._ctrl.type(text)
                typed = True
            except Exception as e:
                LOG.debug("controller.type failed: %s", e)
        if typed:
            return
        if not self.settings.live_use_clipboard_fallback:
            for c in text:
                try:
                    self._ctrl.press(c)
                    self._ctrl.release(c)
                except Exception:
                    pass
            return
        prev = cb.get_clipboard()
        try:
            cb.set_clipboard(text)
            time.sleep(self.settings.paste_delay_ms / 1000.0)
            if self._paste_text is not None:
                self._paste_text(text)
        finally:
            if prev is not None and self.settings.clipboard_restore:

                def _restore() -> None:
                    time.sleep(0.25)
                    try:
                        cb.set_clipboard(prev)
                    except Exception:
                        pass

                threading.Thread(target=_restore, daemon=True).start()

    def _on_press(self, key: object) -> None:
        if self._inject_depth_get() > 0:
            return
        if self.service.inject_lock.locked():
            return
        with self._listener_io_lock:
            if pynput_skip_key(key, capture_active=self._capture_session.is_capturing()):
                return
            ch = pynput_key_char(key)

            if not self._capture_session.is_capturing() and ch is not None and len(ch) == 1:
                self._capture_session.record_idle_char(ch)

            if self._capture_session.is_capturing():
                res = self._capture_session.handle_capturing_key(key, ch, debug=self.debug)
                if res.kind == CapturingKeyKind.CANCEL:
                    return
                if res.kind == CapturingKeyKind.SUBMIT:
                    self._finalize_capture_submit(
                        res.raw_buf,
                        res.from_prefix,
                        entered_with_newline=res.entered_with_newline,
                    )
                    return
                return

            # If a capture expansion is in flight, buffer subsequent keystrokes so the eventual
            # inject can replace capture+tail atomically. Still allow starting a new capture
            # with the trigger: while a trigger prefix is in progress, do not add chars to tail.
            if self.service.has_pending_expansion_tail():
                if self.settings.use_prefix_trigger and self.trigger:
                    pr = self._capture_session.try_prefix_trigger(
                        ch, trigger=self.trigger, use_prefix=self.settings.use_prefix_trigger
                    )
                    if pr is PrefixTriggerResult.SUPPRESSED_URL:
                        LOG.debug("skip capture: // is part of http(s): / file: / ftp: URL")
                        return
                    if pr is PrefixTriggerResult.ENTERED_CAPTURE:
                        if self.debug:
                            LOG.debug("capture mode on (prefix)")
                        self._live_clear()
                        return
                    if self._capture_session.trigger_in_progress():
                        # Don't buffer into tail while we're determining whether a new trigger begins.
                        self._live_clear()
                        return

                if ch is not None:
                    self.service.append_expansion_tail_char(ch)
                if self._live_capable():
                    self._handle_live_key_context_only(key, ch)
                else:
                    self._context_idle_key(ch)
                return

            self._capture_session.on_non_space_while_idle(ch)

            if self._capture_session.try_double_space_open_capture(ch):
                self._enter_capture_from_double_space()
                return

            if self.settings.use_prefix_trigger and self.trigger:
                pr = self._capture_session.try_prefix_trigger(
                    ch, trigger=self.trigger, use_prefix=self.settings.use_prefix_trigger
                )
                if pr is PrefixTriggerResult.SUPPRESSED_URL:
                    LOG.debug("skip capture: // is part of http(s): / file: / ftp: URL")
                    return
                if pr is PrefixTriggerResult.ENTERED_CAPTURE:
                    if self.debug:
                        LOG.debug("capture mode on (prefix)")
                    self._live_clear()
                    return
                if self._capture_session.trigger_in_progress():
                    self._live_clear()
                    return

            if self._live_capable():
                self._handle_live_key(key, ch)
            else:
                self._context_idle_key(ch)

    def _setup_inject(self, ctrl: Controller) -> None:
        import platform

        mod_key = Key.cmd if platform.system() == "Darwin" else Key.ctrl
        delay_bs = self.service.settings.backspace_delay_ms / 1000.0
        parent = self

        def delete_n(n: int) -> None:
            with parent._inject_depth_hold():
                for _ in range(max(0, n)):
                    ctrl.tap(Key.backspace)
                    if delay_bs:
                        time.sleep(delay_bs)

        def paste_text(_: str) -> None:
            with parent._inject_depth_hold():
                with ctrl.pressed(mod_key):
                    ctrl.press("v")
                    ctrl.release("v")

        def type_expansion(text: str) -> None:
            with parent._inject_depth_hold():
                if hasattr(ctrl, "type"):
                    ctrl.type(text)
                else:
                    for c in text:
                        ctrl.press(c)
                        ctrl.release(c)

        def cursor_left_n(n: int) -> None:
            with parent._inject_depth_hold():
                for _ in range(max(0, n)):
                    ctrl.tap(Key.left)
                    if delay_bs:
                        time.sleep(delay_bs)

        parent._delete_n = delete_n
        parent._paste_text = paste_text
        self.service.set_inject(
            delete_n, paste_text, type_expansion, cursor_left_fn=cursor_left_n
        )

    def _run_pynput_blocking(self, stop: threading.Event) -> None:
        self._ctrl = Controller()
        self._setup_inject(self._ctrl)
        self._listener = Listener(on_press=self._on_press)
        self._listener.start()
        extra = " + live word buffer" if self._live_capable() else ""
        LOG.info(
            "listening (pynput) prefix=%s double_space=%s%s",
            self.trigger if self.settings.use_prefix_trigger else "(off)",
            self.settings.double_space_activation,
            extra,
        )
        while not stop.wait(timeout=0.25):
            pass
        if self._listener is not None:
            self._listener.stop()

    def run_blocking(self, stop: threading.Event) -> None:
        from app.keyboard.runner import run_keyboard_backend

        run_keyboard_backend(self, stop)
