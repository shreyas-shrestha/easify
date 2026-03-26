"""Optional `config.toml` — applied only when env does not already set the same knob."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


def config_file_candidates() -> list[Path]:
    import os

    paths: list[Path] = []
    explicit = os.environ.get("EASIFY_CONFIG")
    if explicit:
        paths.append(Path(explicit).expanduser())
    paths.append(Path.home() / ".config" / "easify" / "config.toml")
    paths.append(Path.home() / ".easify" / "config.toml")
    return paths


def load_first_config_toml() -> Optional[Mapping[str, Any]]:
    for p in config_file_candidates():
        if p.is_file():
            try:
                with p.open("rb") as f:
                    data = tomllib.load(f)
            except (OSError, TypeError, ValueError):
                return None
            if isinstance(data, dict):
                return data
            return None
    return None


def env_sets_any(*keys: str) -> bool:
    import os

    return any(k in os.environ for k in keys)


def apply_toml_to_settings(obj: Any, data: Mapping[str, Any]) -> None:
    """Mutate a Settings instance in place. Env always wins — skip if env already set."""

    def take_str(attr: str, *env_keys: str, key: Optional[str] = None) -> None:
        kmap = key or attr
        if kmap not in data or env_sets_any(*env_keys):
            return
        val = data[kmap]
        if val is not None:
            setattr(obj, attr, str(val).strip())

    def take_bool(attr: str, *env_keys: str, key: Optional[str] = None) -> None:
        kmap = key or attr
        if kmap not in data or env_sets_any(*env_keys):
            return
        v = data[kmap]
        if isinstance(v, bool):
            setattr(obj, attr, v)
        elif isinstance(v, (int, float)):
            setattr(obj, attr, bool(v))
        elif isinstance(v, str):
            setattr(obj, attr, v.lower() in ("1", "true", "yes", "on"))

    def take_int(attr: str, *env_keys: str, key: Optional[str] = None, lo: int = 0, hi: int = 10**9) -> None:
        kmap = key or attr
        if kmap not in data or env_sets_any(*env_keys):
            return
        try:
            n = int(data[kmap])
            setattr(obj, attr, max(lo, min(hi, n)))
        except (TypeError, ValueError):
            pass

    def take_float(attr: str, *env_keys: str, key: Optional[str] = None) -> None:
        kmap = key or attr
        if kmap not in data or env_sets_any(*env_keys):
            return
        try:
            setattr(obj, attr, float(data[kmap]))
        except (TypeError, ValueError):
            pass

    def take_path(attr: str, *env_keys: str, key: Optional[str] = None) -> None:
        kmap = key or attr
        if kmap not in data or env_sets_any(*env_keys):
            return
        val = data[kmap]
        if val is not None:
            setattr(obj, attr, Path(str(val).strip()).expanduser())

    take_str("trigger", "EASIFY_TRIGGER", "OLLAMA_EXPANDER_TRIGGER")
    take_str("capture_close", "EASIFY_CAPTURE_CLOSE", key="capture_close")
    take_bool("use_prefix_trigger", "EASIFY_ACTIVATION_PREFIX", key="activation_prefix")
    take_bool("double_space_activation", "EASIFY_ACTIVATION_DOUBLE_SPACE", key="activation_double_space")
    take_int(
        "double_space_window_ms",
        "EASIFY_DOUBLE_SPACE_WINDOW_MS",
        key="double_space_window_ms",
        lo=100,
        hi=3000,
    )
    take_str("palette_hotkey", "EASIFY_PALETTE_HOTKEY", key="palette_hotkey")
    take_str("palette_hotkey_alt", "EASIFY_PALETTE_HOTKEY_ALT", key="palette_hotkey_alt")
    take_int(
        "capture_max_chars",
        "EASIFY_CAPTURE_MAX_CHARS",
        key="capture_max_chars",
        lo=256,
        hi=100_000,
    )
    take_bool("tray_enabled", "EASIFY_TRAY", key="tray")
    take_str("ollama_url", "OLLAMA_URL", key="ollama_url")
    take_str("ollama_model", "EASIFY_MODEL", "OLLAMA_MODEL", key="model")
    take_str("ai_provider", "EASIFY_AI_PROVIDER", key="ai_provider")
    take_str("openai_api_key", "EASIFY_OPENAI_API_KEY", "OPENAI_API_KEY", key="openai_api_key")
    take_str("openai_base_url", "EASIFY_OPENAI_BASE_URL", "OPENAI_BASE_URL", key="openai_base_url")
    take_str("openai_model", "EASIFY_OPENAI_MODEL", key="openai_model")
    take_str("anthropic_api_key", "EASIFY_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", key="anthropic_api_key")
    take_str("anthropic_model", "EASIFY_ANTHROPIC_MODEL", key="anthropic_model")
    take_bool("context_include_focused_app", "EASIFY_CONTEXT_FOCUSED_APP", key="context_include_focused_app")
    take_int(
        "context_buffer_words",
        "EASIFY_CONTEXT_BUFFER_WORDS",
        key="context_buffer_words",
        lo=0,
        hi=96,
    )
    take_bool("context_clipboard_for_l3", "EASIFY_CONTEXT_CLIPBOARD_L3", key="context_clipboard_l3")
    take_int(
        "context_clipboard_max_chars",
        "EASIFY_CONTEXT_CLIPBOARD_MAX_CHARS",
        key="context_clipboard_max_chars",
        lo=0,
        hi=8000,
    )
    take_bool("expansion_preview", "EASIFY_EXPANSION_PREVIEW", key="expansion_preview")
    take_str("evdev_device", "EASIFY_EVDEV_DEVICE", key="evdev_device")
    take_str("backend", "EASIFY_BACKEND", key="backend")
    take_str("settings_preset", "EASIFY_PRESET", key="preset")

    take_int("fuzzy_score_cutoff", "EASIFY_FUZZY_SCORE", "OLLAMA_EXPANDER_FUZZY_SCORE", key="fuzzy_score", lo=50, hi=100)
    take_int("fuzzy_max_keys", "EASIFY_FUZZY_MAX_KEYS", "OLLAMA_EXPANDER_FUZZY_MAX_KEYS", key="fuzzy_max_keys", lo=100, hi=500_000)

    take_bool("live_autocorrect", "EASIFY_LIVE_AUTOCORRECT", "OLLAMA_EXPANDER_LIVE_AUTOCORRECT", key="live_autocorrect")
    take_bool("live_fuzzy", "EASIFY_LIVE_FUZZY", "OLLAMA_EXPANDER_LIVE_FUZZY", key="live_fuzzy")
    take_bool("live_cache", "EASIFY_LIVE_CACHE", "OLLAMA_EXPANDER_LIVE_CACHE", key="live_cache")
    take_int("live_min_word_len", "EASIFY_LIVE_MIN_WORD_LEN", key="live_min_word_len", lo=1, hi=50)
    take_int(
        "live_fuzzy_threshold",
        "EASIFY_LIVE_FUZZY_THRESHOLD",
        "EASIFY_LIVE_FUZZY_CUTOFF",
        "OLLAMA_EXPANDER_LIVE_FUZZY_THRESHOLD",
        "OLLAMA_EXPANDER_LIVE_FUZZY_CUTOFF",
        key="live_fuzzy_threshold",
        lo=50,
        hi=99,
    )
    take_int(
        "live_cooldown_ms",
        "EASIFY_LIVE_COOLDOWN_MS",
        "EASIFY_LIVE_FIX_COOLDOWN",
        "OLLAMA_EXPANDER_LIVE_COOLDOWN_MS",
        "OLLAMA_EXPANDER_LIVE_FIX_COOLDOWN",
        key="cooldown_ms",
        lo=0,
        hi=60_000,
    )
    take_bool("live_use_clipboard_fallback", "EASIFY_LIVE_CLIPBOARD_FALLBACK", key="live_clipboard_fallback")
    take_bool("prewarm", "EASIFY_PREWARM", key="prewarm")
    take_bool("startup_health_check", "EASIFY_STARTUP_HEALTH", key="startup_health")
    take_float("startup_health_timeout_s", "EASIFY_STARTUP_HEALTH_TIMEOUT", key="startup_health_timeout")
    take_int("cache_ttl_sec", "EASIFY_CACHE_TTL_SEC", key="cache_ttl_sec", lo=0, hi=86400 * 365)
    take_bool("live_cache_enrich", "EASIFY_LIVE_CACHE_ENRICH", key="live_cache_enrich")
    take_int("live_enrich_min_len", "EASIFY_LIVE_ENRICH_MIN_LEN", key="live_enrich_min_len", lo=1, hi=64)
    take_int(
        "live_enrich_max_per_minute",
        "EASIFY_LIVE_ENRICH_MAX_PER_MINUTE",
        key="live_enrich_max_per_minute",
        lo=0,
        hi=600,
    )
    take_int(
        "live_enrich_max_concurrent",
        "EASIFY_LIVE_ENRICH_MAX_CONCURRENT",
        key="live_enrich_max_concurrent",
        lo=1,
        hi=8,
    )
    take_int(
        "live_enrich_queue_max",
        "EASIFY_LIVE_ENRICH_QUEUE_MAX",
        key="live_enrich_queue_max",
        lo=4,
        hi=256,
    )
    take_bool("live_enrich_skip_same", "EASIFY_LIVE_ENRICH_SKIP_SAME", key="live_enrich_skip_same")
    take_int("phrase_buffer_max", "EASIFY_PHRASE_BUFFER_MAX", key="phrase_buffer_max", lo=0, hi=20)
    take_bool("engine_v2", "EASIFY_ENGINE_V2", key="engine_v2")
    take_bool("perf", "EASIFY_PERF", key="perf")
    take_bool("inject_prefer_type", "EASIFY_INJECT_TYPE_FIRST", key="inject_prefer_type")
    take_bool("metrics_enabled", "EASIFY_METRICS", key="metrics")
    take_bool("expansion_log_enabled", "EASIFY_EXPANSION_LOG", key="expansion_log")
    take_path("expansion_log_path", "EASIFY_EXPANSION_LOG_PATH", key="expansion_log_path")

    take_bool("clipboard_restore", "EASIFY_CLIPBOARD_RESTORE", key="clipboard_restore")
    take_bool("debug_keys", "EASIFY_DEBUG", key="debug")
    take_bool("verbose", "EASIFY_VERBOSE", key="verbose")

    take_float("ollama_timeout_s", "EASIFY_OLLAMA_TIMEOUT", key="ollama_timeout")
    take_int("ollama_retries", "EASIFY_RETRIES", "OLLAMA_EXPANDER_RETRIES", key="ollama_retries", lo=0, hi=20)
    take_int("enter_backspaces", "EASIFY_ENTER_BACKSPACES", key="enter_backspaces", lo=0, hi=5)
    take_int("backspace_delay_ms", "EASIFY_BACKSPACE_DELAY_MS", key="backspace_delay_ms", lo=0, hi=500)
    take_int("paste_delay_ms", "EASIFY_PASTE_DELAY_MS", key="paste_delay_ms", lo=0, hi=5000)
    take_int("after_delete_ms", "EASIFY_AFTER_DELETE_MS", key="after_delete_ms", lo=0, hi=2000)
    take_bool("pre_inject_refocus", "EASIFY_PRE_INJECT_REFOCUS", key="pre_inject_refocus")
    take_int("inject_settle_ms", "EASIFY_INJECT_SETTLE_MS", key="inject_settle_ms", lo=0, hi=2000)
    take_int(
        "inject_settle_max_wait_ms",
        "EASIFY_INJECT_SETTLE_MAX_WAIT_MS",
        key="inject_settle_max_wait_ms",
        lo=50,
        hi=30_000,
    )
    take_bool(
        "inject_tail_via_cursor_left",
        "EASIFY_INJECT_TAIL_CURSOR_LEFT",
        key="inject_tail_via_cursor_left",
    )
    take_bool(
        "inject_via_accessibility",
        "EASIFY_INJECT_ACCESSIBILITY",
        key="inject_via_accessibility",
    )
    take_bool(
        "inject_accessibility_match_last",
        "EASIFY_INJECT_ACCESSIBILITY_MATCH_LAST",
        key="inject_accessibility_match_last",
    )
    take_bool(
        "inject_accessibility_unique_match_only",
        "EASIFY_INJECT_ACCESSIBILITY_UNIQUE_MATCH_ONLY",
        key="inject_accessibility_unique_match_only",
    )

    take_bool("semantic_snippets", "EASIFY_SEMANTIC_SNIPPETS", key="semantic_snippets")
    take_str("semantic_model", "EASIFY_SEMANTIC_MODEL", key="semantic_model")
    take_float("semantic_min_similarity", "EASIFY_SEMANTIC_MIN_SIMILARITY", key="semantic_min_similarity")
    take_bool(
        "snippet_namespace_lenient",
        "EASIFY_SNIPPET_NAMESPACE_LENIENT",
        key="snippet_namespace_lenient",
    )
    take_int(
        "cache_promote_min_hits",
        "EASIFY_CACHE_PROMOTE_MIN_HITS",
        key="cache_promote_min_hits",
        lo=0,
        hi=1_000_000,
    )
    take_str("cache_promote_sources", "EASIFY_CACHE_PROMOTE_SOURCES", key="cache_promote_sources")
    take_str("undo_hotkey", "EASIFY_UNDO_HOTKEY", key="undo_hotkey")
    take_int("undo_stack_max", "EASIFY_UNDO_STACK_MAX", key="undo_stack_max", lo=1, hi=256)
    take_str("ui_host", "EASIFY_UI_HOST", key="ui_host")
    take_int("ui_port", "EASIFY_UI_PORT", key="ui_port", lo=1, hi=65535)
    take_int(
        "snippet_reload_listen_port",
        "EASIFY_SNIPPET_RELOAD_LISTEN_PORT",
        key="snippet_reload_listen_port",
        lo=0,
        hi=65535,
    )
    take_float(
        "tray_thinking_hint_after_s",
        "EASIFY_TRAY_THINKING_HINT_AFTER_S",
        key="tray_thinking_hint_after_s",
    )
    take_str("ui_secret_token", "EASIFY_UI_SECRET_TOKEN", key="ui_secret_token")
    take_int(
        "cache_promote_max_keys",
        "EASIFY_CACHE_PROMOTE_MAX_KEYS",
        key="cache_promote_max_keys",
        lo=0,
        hi=100_000,
    )
    take_int(
        "double_space_settle_ms",
        "EASIFY_DOUBLE_SPACE_SETTLE_MS",
        key="double_space_settle_ms",
        lo=0,
        hi=500,
    )


def merge_config_into_settings(obj: Any) -> None:
    data = load_first_config_toml()
    if data:
        apply_toml_to_settings(obj, data)
