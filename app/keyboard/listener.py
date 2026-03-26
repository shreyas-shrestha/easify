"""Global pynput listener — prefix / double-space capture + optional live word buffer."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable, Optional

from pynput.keyboard import Controller, Key, Listener

from app.config.settings import Settings
from app.context.focus import get_focused_app_name_fresh
from app.engine.buffer import CaptureBuffer, CloseDelimiterMatcher, TriggerState
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
        self._close_matcher: Optional[CloseDelimiterMatcher] = None
        self._recent_chars: deque[str] = deque(maxlen=16)

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
        # Live «no //» path: word/phrase replace on Space. Run whenever any stage or phrase buffer is enabled
        # (previously gated only on live_autocorrect, which broke fuzzy+snippet+cache with autocorrect off).
        if (
            settings.live_autocorrect
            or settings.live_fuzzy
            or settings.live_cache
            or settings.live_cache_enrich
            or settings.phrase_buffer_max > 0
        ):
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
        # Word boundary without space: "hello," should still push "hello" for rolling context + live resolve.
        if self._live_chars and ch is not None and len(ch) == 1 and ch in ",.;:!?)]}\"'":
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

    def _live_flush_context_only(self) -> None:
        """Update rolling / phrase buffers without live replace (expansion tail in flight)."""
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
        if self._phrase_deque is not None:
            self._phrase_deque.append(word)

    def _handle_live_key_context_only(self, key: object, ch: Optional[str]) -> None:
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
            self._live_flush_context_only()
            return
        if self._live_chars and ch is not None and len(ch) == 1 and ch in ",.;:!?)]}\"'":
            self._live_flush_context_only()
            return
        self._live_clear()

    def _cancel_capture(self) -> None:
        """Exit capture mode without submitting (document unchanged beyond what user typed)."""
        if self._close_matcher is not None:
            self._close_matcher.reset()
        self._close_matcher = None
        self._capture.clear()
        self._trigger.reset()
        self._capture_from_prefix = False
        self._state = _STATE_IDLE
        LOG.info("capture cancelled (Esc) — not submitted")

    def _suppress_capture_for_url_scheme_slash_slash(self) -> bool:
        """Avoid treating // in https://, http://, file://, ftp:// as the capture trigger."""
        if self.trigger != "//":
            return False
        s = "".join(self._recent_chars)
        if len(s) < 2 or not s.endswith("//"):
            return False
        pre = s[:-2]
        return pre.endswith(("http:", "https:", "file:", "ftp:"))

    def _submit_capture(self, *, entered_with_newline: bool) -> None:
        raw = self._capture.text()
        run_prompt = raw.strip()
        if self._close_matcher is not None:
            self._close_matcher.reset()
        self._close_matcher = None
        from_prefix = self._capture_from_prefix
        self._state = _STATE_IDLE
        self._capture.clear()
        self._trigger.reset()
        self._capture_from_prefix = False
        if not run_prompt:
            LOG.warning("empty intent — type between delimiters or press Enter")
            return
        close = self.settings.capture_close.strip()
        if from_prefix and self.settings.use_prefix_trigger and self.trigger:
            if close and not entered_with_newline:
                dc = len(self.trigger) + len(raw) + len(close)
                undo = f"{self.trigger}{raw}{close}"
            else:
                dc = len(self.trigger) + len(raw) + max(0, self.enter_backspaces)
                undo = f"{self.trigger}{raw}"
        else:
            if close and not entered_with_newline:
                dc = len(raw) + len(close)
                undo = f"{raw}{close}"
            else:
                dc = len(raw) + max(0, self.enter_backspaces)
                undo = raw
        if self.debug:
            LOG.debug("submit %r", run_prompt)
        focused = (
            get_focused_app_name_fresh()
            if self.settings.pre_inject_refocus
            else ""
        )
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
        self._inject_depth += 1
        try:
            self._delete_n(2)
        finally:
            self._inject_depth -= 1
        # Immediate state transition — blocking sleeps on this thread drop keystrokes.
        # Legacy settle-after-delete (double_space_settle_ms) was removed; use app-side
        # delays only if unavoidable.
        self._state = _STATE_CAPTURING
        self._capture.clear()
        self._trigger.reset()
        self._capture_from_prefix = False
        self._close_matcher = (
            CloseDelimiterMatcher(self.settings.capture_close)
            if self.settings.capture_close.strip()
            else None
        )
        self._live_clear()
        self._dbl_armed = False
        if self.debug:
            LOG.debug("capture mode (double-space)")
        LOG.info("capture mode (double-space)")

    def _perform_live_replace(self, old_word: str, new_text: str) -> None:
        if self._delete_n is None:
            return
        from app.inject.accessibility import focused_field_appears_secure

        if focused_field_appears_secure():
            LOG.debug("live replace skipped: secure/password field")
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
        if pynput_skip_key(key, capture_active=(self._state == _STATE_CAPTURING)):
            return

        ch = pynput_key_char(key)

        if self._state == _STATE_IDLE and ch is not None and len(ch) == 1:
            self._recent_chars.append(ch)

        if self._state == _STATE_CAPTURING:
            if key == Key.esc:
                self._cancel_capture()
                return
            if key in (Key.enter, getattr(Key, "kp_enter", Key.enter)):
                self._submit_capture(entered_with_newline=True)
                return

            if ch == "\b":
                if self._close_matcher is not None and self._close_matcher.backspace():
                    return
                self._capture.backspace()
                return

            if self._close_matcher is not None and ch is not None and ch != "\n":
                for ev in self._close_matcher.feed(ch):
                    if ev[0] == "submit":
                        self._submit_capture(entered_with_newline=False)
                        return
                    append_ch = ev[1]
                    if append_ch is not None:
                        self._capture.push(append_ch)
                if self.debug and len(self._capture.chars) <= 80:
                    LOG.debug("capture %r", self._capture.text())
                return

            if ch is not None and ch != "\n":
                self._capture.push(ch)
                if self.debug and len(self._capture.chars) <= 80:
                    LOG.debug("capture %r", self._capture.text())
            return

        # If a capture expansion is in flight, buffer subsequent keystrokes so the eventual
        # inject can replace capture+tail atomically. Still allow starting a new capture
        # with the trigger: while a trigger prefix is in progress, do not add chars to tail.
        if self._state == _STATE_IDLE and self.service.has_pending_expansion_tail():
            if self.settings.use_prefix_trigger and self.trigger:
                completed = self._trigger.try_advance(ch, self.trigger)
                if completed:
                    if self._suppress_capture_for_url_scheme_slash_slash():
                        LOG.debug("skip capture: // is part of http(s): / file: / ftp: URL")
                        return
                    if self.debug:
                        LOG.debug("capture mode on (prefix)")
                    self._state = _STATE_CAPTURING
                    self._capture_from_prefix = True
                    self._capture.clear()
                    self._close_matcher = (
                        CloseDelimiterMatcher(self.settings.capture_close)
                        if self.settings.capture_close.strip()
                        else None
                    )
                    self._live_clear()
                    return
                if self._trigger.in_progress:
                    # Don't buffer into tail while we're determining whether a new trigger begins.
                    self._live_clear()
                    return

            if ch is not None:
                self.service.append_expansion_tail_char(ch)
            if self._live_resolver is not None:
                self._handle_live_key_context_only(key, ch)
            else:
                self._context_idle_key(ch)
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
                if self._suppress_capture_for_url_scheme_slash_slash():
                    LOG.debug("skip capture: // is part of http(s): / file: / ftp: URL")
                    return
                if self.debug:
                    LOG.debug("capture mode on (prefix)")
                self._state = _STATE_CAPTURING
                self._capture_from_prefix = True
                self._capture.clear()
                self._close_matcher = (
                    CloseDelimiterMatcher(self.settings.capture_close)
                    if self.settings.capture_close.strip()
                    else None
                )
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

        def cursor_left_n(n: int) -> None:
            parent._inject_depth += 1
            try:
                for _ in range(max(0, n)):
                    ctrl.tap(Key.left)
                    if delay_bs:
                        time.sleep(delay_bs)
            finally:
                parent._inject_depth -= 1

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
