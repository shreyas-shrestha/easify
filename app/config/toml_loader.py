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

    take_str("trigger", "EASIFY_TRIGGER", "OLLAMA_EXPANDER_TRIGGER")
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
    take_bool("perf", "EASIFY_PERF", key="perf")
    take_bool("inject_prefer_type", "EASIFY_INJECT_TYPE_FIRST", key="inject_prefer_type")
    take_bool("metrics_enabled", "EASIFY_METRICS", key="metrics")

    take_bool("clipboard_restore", "EASIFY_CLIPBOARD_RESTORE", key="clipboard_restore")
    take_bool("debug_keys", "EASIFY_DEBUG", key="debug")
    take_bool("verbose", "EASIFY_VERBOSE", key="verbose")

    take_float("ollama_timeout_s", "EASIFY_OLLAMA_TIMEOUT", key="ollama_timeout")
    take_int("ollama_retries", "EASIFY_RETRIES", "OLLAMA_EXPANDER_RETRIES", key="ollama_retries", lo=0, hi=20)
    take_int("enter_backspaces", "EASIFY_ENTER_BACKSPACES", key="enter_backspaces", lo=0, hi=5)
    take_int("backspace_delay_ms", "EASIFY_BACKSPACE_DELAY_MS", key="backspace_delay_ms", lo=0, hi=500)
    take_int("paste_delay_ms", "EASIFY_PASTE_DELAY_MS", key="paste_delay_ms", lo=0, hi=5000)
    take_int("after_delete_ms", "EASIFY_AFTER_DELETE_MS", key="after_delete_ms", lo=0, hi=2000)


def merge_config_into_settings(obj: Any) -> None:
    data = load_first_config_toml()
    if data:
        apply_toml_to_settings(obj, data)
