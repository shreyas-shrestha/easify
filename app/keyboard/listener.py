"""Global pynput listener — prefix / double-space capture + optional live word buffer."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Optional

from pynput.keyboard import Controller, Key, Listener

from app.config.settings import Settings
from app.engine.buffer import CaptureBuffer, TriggerState
from app.engine.guards import is_safe_phrase_tokens, is_safe_word
from app.engine.live_word import LiveFixCooldown, LiveWordResolver
from app.engine.service import ExpansionJob, ExpansionService
from app.keyboard.keys import pynput_key_char, pynput_skip_key
from app.utils import clipboard as cb
from app.utils.log import get_logger

LOG = get_logger(__name__)

_STATE_IDLE, _STATE_CAPTURING = "idle", "capturing"


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
        self._state = _STATE_IDLE
        self._trigger = TriggerState()
        self._capture = CaptureBuffer(max_chars=settings.capture_max_chars)
        self._capture_from_prefix = False
        self._inject_depth = 0
        self._listener: Optional[Listener] = None
        self._ctrl: Optional[Controller] = None
        self._delete_n: Optional[Callable[[int], None]] = None
        self._paste_text: Optional[Callable[[str], None]] = None

        self._dbl_armed = False
        self._dbl_last_mono = 0.0

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
        if settings.live_autocorrect:
            self._live_resolver = LiveWordResolver(
                snippets=service.snippets,
                autocorrect=service.autocorrect,
                cache=service.cache,
                model=service.cache_model_id,
                min_word_len=settings.live_min_word_len,
                fuzzy_enabled=settings.live_fuzzy,
                cache_enabled=settings.live_cache,
                fuzzy_threshold=settings.live_fuzzy_threshold,
                perf=settings.perf,
            )

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
        if self._live_resolver is None:
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
        self._live_clear()

    def _live_flush(self) -> None:
        if self._live_resolver is None:
            self._live_clear()
            return
        word = "".join(self._live_chars)
        self._live_chars.clear()
        if not word.strip():
            if self._phrase_deque is not None:
                self._phrase_deque.clear()
            return
        self._push_rolling_word(word)
        if not self._live_cooldown.can_fix():
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

    def _enter_capture_from_double_space(self) -> None:
        if self._delete_n is None:
            return
        self._inject_depth += 1
        try:
            self._delete_n(2)
        finally:
            self._inject_depth -= 1
        self._state = _STATE_CAPTURING
        self._capture.clear()
        self._trigger.reset()
        self._capture_from_prefix = False
        self._live_clear()
        self._dbl_armed = False
        LOG.info("capture mode (double-space)")

    def _perform_live_replace(self, old_word: str, new_text: str) -> None:
        if self._delete_n is None:
            return
        with self.service.inject_lock:
            try:
                self._delete_n(len(old_word) + 1)
                time.sleep(self.settings.after_delete_ms / 1000.0)
                self._inject_depth += 1
                try:
                    self._type_text(new_text + " ")
                    if self.service.metrics is not None:
                        self.service.metrics.incr("live_replacements")
                except Exception as e:
                    LOG.warning("live type failed: %s", e)
                finally:
                    self._inject_depth -= 1
            except Exception as e:
                LOG.warning("live replace failed: %s", e)

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
        if self._inject_depth > 0:
            return
        if self.service.inject_lock.locked():
            return
        if pynput_skip_key(key):
            return

        ch = pynput_key_char(key)

        if self._state == _STATE_CAPTURING:
            if key in (Key.enter, getattr(Key, "kp_enter", Key.enter)):
                run_prompt = self._capture.text()
                if self.debug:
                    LOG.debug("submit %r", run_prompt)
                from_prefix = self._capture_from_prefix
                self._state = _STATE_IDLE
                self._capture.clear()
                self._trigger.reset()
                self._capture_from_prefix = False
                if not run_prompt.strip():
                    LOG.warning("empty intent — type text after trigger then Enter")
                    return
                if from_prefix and self.settings.use_prefix_trigger and self.trigger:
                    dc = len(self.trigger) + len(run_prompt) + max(0, self.enter_backspaces)
                    undo = f"{self.trigger}{run_prompt}"
                else:
                    dc = len(run_prompt) + max(0, self.enter_backspaces)
                    undo = run_prompt
                self.service.submit(
                    ExpansionJob(
                        capture=run_prompt,
                        delete_count=dc,
                        prior_words=self._prior_context_string(),
                        undo_restore=undo,
                    )
                )
                return

            if ch == "\b":
                self._capture.backspace()
            elif ch is not None and ch != "\n":
                self._capture.push(ch)
                if self.debug and len(self._capture.chars) <= 80:
                    LOG.debug("capture %r", self._capture.text())
            return

        if ch != " " and self._state == _STATE_IDLE:
            self._dbl_armed = False

        if (
            self._state == _STATE_IDLE
            and ch == " "
            and self.settings.double_space_activation
        ):
            now = time.monotonic()
            win = self.settings.double_space_window_ms / 1000.0
            if self._dbl_armed and (now - self._dbl_last_mono) > win:
                self._dbl_armed = False
            if self._dbl_armed and (now - self._dbl_last_mono) <= win:
                self._enter_capture_from_double_space()
                return
            self._dbl_armed = True
            self._dbl_last_mono = now

        if self.settings.use_prefix_trigger and self.trigger:
            completed = self._trigger.try_advance(ch, self.trigger)
            if completed:
                if self.debug:
                    LOG.debug("capture mode on (prefix)")
                self._state = _STATE_CAPTURING
                self._capture_from_prefix = True
                self._capture.clear()
                self._live_clear()
                return
            if self._trigger.in_progress:
                self._live_clear()
                return

        if self._live_resolver is not None:
            self._handle_live_key(key, ch)
        else:
            self._context_idle_key(ch)

    def _setup_inject(self, ctrl: Controller) -> None:
        import platform

        mod_key = Key.cmd if platform.system() == "Darwin" else Key.ctrl
        delay_bs = self.service.settings.backspace_delay_ms / 1000.0
        parent = self

        def delete_n(n: int) -> None:
            parent._inject_depth += 1
            try:
                for _ in range(max(0, n)):
                    ctrl.tap(Key.backspace)
                    if delay_bs:
                        time.sleep(delay_bs)
            finally:
                parent._inject_depth -= 1

        def paste_text(_: str) -> None:
            parent._inject_depth += 1
            try:
                with ctrl.pressed(mod_key):
                    ctrl.press("v")
                    ctrl.release("v")
            finally:
                parent._inject_depth -= 1

        def type_expansion(text: str) -> None:
            parent._inject_depth += 1
            try:
                if hasattr(ctrl, "type"):
                    ctrl.type(text)
                else:
                    for c in text:
                        ctrl.press(c)
                        ctrl.release(c)
            finally:
                parent._inject_depth -= 1

        parent._delete_n = delete_n
        parent._paste_text = paste_text
        self.service.set_inject(delete_n, paste_text, type_expansion)

    def _run_pynput_blocking(self, stop: threading.Event) -> None:
        self._ctrl = Controller()
        self._setup_inject(self._ctrl)
        self._listener = Listener(on_press=self._on_press)
        self._listener.start()
        extra = " + live word buffer" if self._live_resolver else ""
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
