"""Central configuration: env-first (EASIFY_*), paths, tuning."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.config.toml_loader import merge_config_into_settings


def _env(name: str, default: str) -> str:
    return os.environ.get(f"EASIFY_{name}") or os.environ.get(f"OLLAMA_EXPANDER_{name}") or default


def _env_bool(name: str, default: bool) -> bool:
    v = _env(name, str(default)).lower()
    return v in ("1", "true", "yes", "on")


def default_data_dir() -> Path:
    """Prefer repo `data/` when developing; else package `app/bundled/`."""
    here = Path(__file__).resolve().parent
    app_root = here.parent
    repo_root = app_root.parent
    legacy = repo_root / "data" / "snippets.json"
    if legacy.is_file():
        return repo_root / "data"
    return app_root / "bundled"


def _config_dir() -> Path:
    return Path.home() / ".config" / "easify"


@dataclass
class Settings:
    trigger: str = field(default_factory=lambda: _env("TRIGGER", "//"))
    capture_close: str = field(default_factory=lambda: _env("CAPTURE_CLOSE", "//").strip())
    use_prefix_trigger: bool = field(default_factory=lambda: _env_bool("ACTIVATION_PREFIX", True))
    double_space_activation: bool = field(default_factory=lambda: _env_bool("ACTIVATION_DOUBLE_SPACE", False))
    double_space_window_ms: int = field(
        default_factory=lambda: max(100, min(3000, int(_env("DOUBLE_SPACE_WINDOW_MS", "400"))))
    )
    palette_hotkey: str = field(default_factory=lambda: _env("PALETTE_HOTKEY", "").strip())
    palette_hotkey_alt: str = field(default_factory=lambda: _env("PALETTE_HOTKEY_ALT", "").strip())
    capture_max_chars: int = field(
        default_factory=lambda: max(256, min(100_000, int(_env("CAPTURE_MAX_CHARS", "4000"))))
    )
    tray_enabled: bool = field(default_factory=lambda: _env_bool("TRAY", True))
    ollama_url: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
    )
    ollama_model: str = field(
        default_factory=lambda: os.environ.get("EASIFY_MODEL") or os.environ.get("OLLAMA_MODEL", "phi3")
    )

    ai_provider: str = field(default_factory=lambda: _env("AI_PROVIDER", "ollama").lower().strip())
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("EASIFY_OPENAI_API_KEY")
        or os.environ.get("OPENAI_API_KEY", "")
    )
    openai_base_url: str = field(
        default_factory=lambda: os.environ.get("EASIFY_OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    )
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini"))
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("EASIFY_ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    anthropic_model: str = field(default_factory=lambda: _env("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022"))

    context_include_focused_app: bool = field(default_factory=lambda: _env_bool("CONTEXT_FOCUSED_APP", True))
    context_buffer_words: int = field(
        default_factory=lambda: max(0, min(96, int(_env("CONTEXT_BUFFER_WORDS", "8"))))
    )
    context_clipboard_for_l3: bool = field(default_factory=lambda: _env_bool("CONTEXT_CLIPBOARD_L3", False))
    context_clipboard_max_chars: int = field(
        default_factory=lambda: max(0, min(8000, int(_env("CONTEXT_CLIPBOARD_MAX_CHARS", "2000"))))
    )
    expansion_preview: bool = field(default_factory=lambda: _env_bool("EXPANSION_PREVIEW", False))
    evdev_device: str = field(default_factory=lambda: _env("EVDEV_DEVICE", "").strip())

    snippets_paths: list[Path] = field(default_factory=list)
    autocorrect_path: Optional[Path] = None
    warmup_prompts_path: Optional[Path] = None
    cache_db_path: Path = field(default_factory=lambda: _config_dir() / "cache.db")
    cache_ttl_sec: int = field(default_factory=lambda: max(0, int(_env("CACHE_TTL_SEC", "0"))))

    fuzzy_score_cutoff: int = field(default_factory=lambda: max(60, min(100, int(_env("FUZZY_SCORE", "82")))))
    fuzzy_max_keys: int = field(default_factory=lambda: int(_env("FUZZY_MAX_KEYS", "5000")))

    live_autocorrect: bool = field(default_factory=lambda: _env_bool("LIVE_AUTOCORRECT", True))
    live_fuzzy: bool = field(default_factory=lambda: _env_bool("LIVE_FUZZY", True))
    live_cache: bool = field(default_factory=lambda: _env_bool("LIVE_CACHE", True))
    live_min_word_len: int = field(default_factory=lambda: max(1, int(_env("LIVE_MIN_WORD_LEN", "3"))))
    live_fuzzy_threshold: int = field(default_factory=lambda: max(50, min(99, int(_env("LIVE_FUZZY_THRESHOLD", "92")))))
    live_cooldown_ms: int = field(default_factory=lambda: max(0, int(_env("LIVE_COOLDOWN_MS", "150"))))
    live_use_clipboard_fallback: bool = field(default_factory=lambda: _env_bool("LIVE_CLIPBOARD_FALLBACK", True))
    prewarm: bool = field(default_factory=lambda: _env_bool("PREWARM", True))
    startup_health_check: bool = field(default_factory=lambda: _env_bool("STARTUP_HEALTH", True))
    startup_health_timeout_s: float = field(
        default_factory=lambda: max(0.5, min(60.0, float(_env("STARTUP_HEALTH_TIMEOUT", "3"))))
    )

    live_cache_enrich: bool = field(default_factory=lambda: _env_bool("LIVE_CACHE_ENRICH", True))
    live_enrich_min_len: int = field(default_factory=lambda: max(3, min(48, int(_env("LIVE_ENRICH_MIN_LEN", "4")))))
    live_enrich_max_per_minute: int = field(
        default_factory=lambda: max(0, min(600, int(_env("LIVE_ENRICH_MAX_PER_MINUTE", "12"))))
    )
    live_enrich_max_concurrent: int = field(
        default_factory=lambda: max(1, min(8, int(_env("LIVE_ENRICH_MAX_CONCURRENT", "2"))))
    )
    live_enrich_queue_max: int = field(
        default_factory=lambda: max(4, min(256, int(_env("LIVE_ENRICH_QUEUE_MAX", "32"))))
    )
    live_enrich_skip_same: bool = field(default_factory=lambda: _env_bool("LIVE_ENRICH_SKIP_SAME", True))

    phrase_buffer_max: int = field(default_factory=lambda: max(0, min(20, int(_env("PHRASE_BUFFER_MAX", "2")))))
    perf: bool = field(default_factory=lambda: _env_bool("PERF", False))
    inject_prefer_type: bool = field(default_factory=lambda: _env_bool("INJECT_TYPE_FIRST", True))
    pre_inject_refocus: bool = field(default_factory=lambda: _env_bool("PRE_INJECT_REFOCUS", True))
    # After parallel tail typing stops (ms), before inject; 0 = off. Reduces Notes/Terminal races with synthetic keys.
    inject_settle_ms: int = field(
        default_factory=lambda: max(0, min(2000, int(_env("INJECT_SETTLE_MS", "55"))))
    )
    inject_settle_max_wait_ms: int = field(
        default_factory=lambda: max(50, min(30_000, int(_env("INJECT_SETTLE_MAX_WAIT_MS", "3000"))))
    )
    # Move cursor left across parallel tail, delete only //capture//, type replacement (tail never deleted).
    inject_tail_via_cursor_left: bool = field(default_factory=lambda: _env_bool("INJECT_TAIL_CURSOR_LEFT", True))
    # macOS AX / Windows UIA: swap capture substring in focused field (pip install easify[accessibility]).
    inject_via_accessibility: bool = field(default_factory=lambda: _env_bool("INJECT_ACCESSIBILITY", True))
    # True = replace last occurrence (rfind); False = first (find) when the capture text appears more than once.
    inject_accessibility_match_last: bool = field(
        default_factory=lambda: _env_bool("INJECT_ACCESSIBILITY_MATCH_LAST", True)
    )
    # AX/UIA: only replace when `old` occurs exactly once in the focused value (multi-field / split editor safe).
    inject_accessibility_unique_match_only: bool = field(
        default_factory=lambda: _env_bool("INJECT_ACCESSIBILITY_UNIQUE_MATCH_ONLY", True)
    )
    metrics_enabled: bool = field(default_factory=lambda: _env_bool("METRICS", False))
    expansion_log_enabled: bool = field(default_factory=lambda: _env_bool("EXPANSION_LOG", False))
    expansion_log_path: Path = field(default_factory=lambda: _config_dir() / "expansion_log.jsonl")

    backend: str = field(default_factory=lambda: _env("BACKEND", "pynput"))
    clipboard_restore: bool = field(default_factory=lambda: _env_bool("CLIPBOARD_RESTORE", True))

    debug_keys: bool = field(default_factory=lambda: _env_bool("DEBUG", False))
    verbose: bool = field(default_factory=lambda: _env_bool("VERBOSE", False))

    semantic_snippets: bool = field(default_factory=lambda: _env_bool("SEMANTIC_SNIPPETS", True))
    semantic_model: str = field(
        default_factory=lambda: _env(
            "SEMANTIC_MODEL",
            "sentence-transformers/all-MiniLM-L6-v2",
        ).strip()
        or "sentence-transformers/all-MiniLM-L6-v2"
    )
    semantic_min_similarity: float = field(
        default_factory=lambda: max(0.05, min(0.99, float(_env("SEMANTIC_MIN_SIMILARITY", "0.35"))))
    )
    snippet_namespace_lenient: bool = field(
        default_factory=lambda: _env_bool("SNIPPET_NAMESPACE_LENIENT", True)
    )
    cache_promote_min_hits: int = field(
        default_factory=lambda: max(0, min(1_000_000, int(_env("CACHE_PROMOTE_MIN_HITS", "0"))))
    )
    cache_promote_sources: str = field(default_factory=lambda: _env("CACHE_PROMOTE_SOURCES", "ai,bg").strip())
    undo_hotkey: str = field(default_factory=lambda: _env("UNDO_HOTKEY", "").strip())
    undo_stack_max: int = field(
        default_factory=lambda: max(1, min(256, int(_env("UNDO_STACK_MAX", "32"))))
    )
    ui_host: str = field(default_factory=lambda: _env("UI_HOST", "127.0.0.1").strip() or "127.0.0.1")
    ui_port: int = field(default_factory=lambda: max(1, min(65535, int(_env("UI_PORT", "8765")))))
    ui_secret_token: str = field(default_factory=lambda: _env("UI_SECRET_TOKEN", "").strip())
    # `easify run` binds this localhost port for POST /hooks/reload-snippets (snippet UI notifies). 0 = off.
    snippet_reload_listen_port: int = field(
        default_factory=lambda: max(0, min(65535, int(_env("SNIPPET_RELOAD_LISTEN_PORT", "8766"))))
    )
    # After N seconds in "thinking", tray tooltip adds a slow-LLM / timeout-cap reminder.
    tray_thinking_hint_after_s: float = field(
        default_factory=lambda: max(0.5, min(120.0, float(_env("TRAY_THINKING_HINT_AFTER_S", "2"))))
    )
    cache_promote_max_keys: int = field(
        default_factory=lambda: max(0, min(100_000, int(_env("CACHE_PROMOTE_MAX_KEYS", "500"))))
    )
    # Unused by current listener (immediate double-space capture); kept for config compatibility.
    double_space_settle_ms: int = field(
        default_factory=lambda: max(0, min(500, int(_env("DOUBLE_SPACE_SETTLE_MS", "0"))))
    )

    ollama_timeout_s: float = field(default_factory=lambda: float(_env("OLLAMA_TIMEOUT", "120")))
    ollama_retries: int = field(default_factory=lambda: int(_env("RETRIES", "2")))

    enter_backspaces: int = field(default_factory=lambda: int(_env("ENTER_BACKSPACES", "1")))
    backspace_delay_ms: int = field(default_factory=lambda: int(_env("BACKSPACE_DELAY_MS", "2")))
    paste_delay_ms: int = field(default_factory=lambda: int(_env("PASTE_DELAY_MS", "50")))
    after_delete_ms: int = field(default_factory=lambda: int(_env("AFTER_DELETE_MS", "30")))

    def __post_init__(self) -> None:
        snip_override = os.environ.get("EASIFY_SNIPPETS") or os.environ.get("OLLAMA_EXPANDER_SNIPPETS")
        if snip_override:
            self.snippets_paths = [Path(os.path.expanduser(snip_override.strip()))]
        cache_override = os.environ.get("EASIFY_CACHE_DB")
        if cache_override:
            self.cache_db_path = Path(os.path.expanduser(cache_override.strip()))
        if not self.snippets_paths:
            user_snip = _config_dir() / "snippets.json"
            dd = default_data_dir()
            bundled = dd / "snippets.json"
            self.snippets_paths = []
            if bundled.is_file():
                self.snippets_paths.append(bundled)
            self.snippets_paths.append(user_snip)
        if self.autocorrect_path is None:
            dd = default_data_dir()
            p = dd / "autocorrect.json"
            self.autocorrect_path = p if p.is_file() else _config_dir() / "autocorrect.json"
        if self.warmup_prompts_path is None:
            wp = default_data_dir() / "warmup_prompts.json"
            self.warmup_prompts_path = wp if wp.is_file() else None
        for key in ("EASIFY_LIVE_FIX_COOLDOWN", "OLLAMA_EXPANDER_LIVE_FIX_COOLDOWN"):
            if key in os.environ:
                try:
                    self.live_cooldown_ms = max(0, int(float(os.environ[key]) * 1000))
                except ValueError:
                    pass
                break
        for key in ("EASIFY_LIVE_FUZZY_CUTOFF", "OLLAMA_EXPANDER_LIVE_FUZZY_CUTOFF"):
            if key in os.environ:
                try:
                    v = int(os.environ[key])
                    self.live_fuzzy_threshold = max(50, min(99, v - 1))
                except ValueError:
                    pass
                break
        merge_config_into_settings(self)
        expansion_log_override = os.environ.get("EASIFY_EXPANSION_LOG_PATH")
        if expansion_log_override and str(expansion_log_override).strip():
            self.expansion_log_path = Path(os.path.expanduser(str(expansion_log_override).strip()))

    def user_snippets_path(self) -> Path:
        """Primary user-writable snippets file (for promotions and UI)."""
        return _config_dir() / "snippets.json"

    def cache_promote_source_set(self) -> frozenset[str]:
        parts = {p.strip().lower() for p in self.cache_promote_sources.replace(";", ",").split(",") if p.strip()}
        return frozenset(parts) if parts else frozenset({"ai", "bg"})

    def any_activation_enabled(self) -> bool:
        if self.use_prefix_trigger:
            return True
        if self.double_space_activation:
            return True
        if self.palette_hotkey.strip():
            return True
        return False

    @classmethod
    def load(cls) -> "Settings":
        """Default paths + env overrides."""
        return cls()
