"""Global pynput listener — `///` capture + optional live word buffer (SPACE boundary)."""

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
        self._capture = CaptureBuffer()
        self._inject_depth = 0
        self._listener: Optional[Listener] = None
        self._ctrl: Optional[Controller] = None
        self._delete_n: Optional[Callable[[int], None]] = None
        self._paste_text: Optional[Callable[[str], None]] = None

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
                model=settings.ollama_model,
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

    def _perform_live_replace(self, old_word: str, new_text: str) -> None:
        if self._delete_n is None:
            return
        self.service.inject_busy.set()
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
        finally:
            self.service.inject_busy.clear()

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
        if self.service.inject_busy.is_set():
            return
        if pynput_skip_key(key):
            return

        ch = pynput_key_char(key)

        if self._state == _STATE_CAPTURING:
            if key in (Key.enter, getattr(Key, "kp_enter", Key.enter)):
                run_prompt = self._capture.text()
                if self.debug:
                    LOG.debug("submit %r", run_prompt)
                self._state = _STATE_IDLE
                self._capture.clear()
                self._trigger.reset()
                if not run_prompt.strip():
                    LOG.warning("empty intent — type text after %r then Enter", self.trigger)
                    return
                dc = len(self.trigger) + len(run_prompt) + max(0, self.enter_backspaces)
                self.service.submit(ExpansionJob(capture=run_prompt, delete_count=dc))
                return

            if ch == "\b":
                self._capture.backspace()
            elif ch is not None and ch != "\n":
                self._capture.push(ch)
                if self.debug and len(self._capture.chars) <= 80:
                    LOG.debug("capture %r", self._capture.text())
            return

        completed = self._trigger.try_advance(ch, self.trigger)
        if completed:
            if self.debug:
                LOG.debug("capture mode on")
            self._state = _STATE_CAPTURING
            self._capture.clear()
            self._live_clear()
            return
        if self._trigger.in_progress:
            self._live_clear()
            return

        if self._live_resolver is not None:
            self._handle_live_key(key, ch)

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

    def run_blocking(self, stop: threading.Event) -> None:
        self._ctrl = Controller()
        self._setup_inject(self._ctrl)
        self._listener = Listener(on_press=self._on_press)
        self._listener.start()
        extra = " + live word buffer" if self._live_resolver else ""
        LOG.info("listening (pynput) trigger=%r%s", self.trigger, extra)
        while not stop.wait(timeout=0.25):
            pass
        if self._listener is not None:
            self._listener.stop()
