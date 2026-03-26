"""Central configuration: env-first (EASIFY_*), paths, tuning."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


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
    trigger: str = field(default_factory=lambda: _env("TRIGGER", "///"))
    ollama_url: str = field(
        default_factory=lambda: os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
    )
    ollama_model: str = field(
        default_factory=lambda: os.environ.get("EASIFY_MODEL") or os.environ.get("OLLAMA_MODEL", "phi3")
    )

    snippets_paths: list[Path] = field(default_factory=list)
    autocorrect_path: Optional[Path] = None
    warmup_prompts_path: Optional[Path] = None
    cache_db_path: Path = field(default_factory=lambda: _config_dir() / "cache.db")

    fuzzy_score_cutoff: int = field(default_factory=lambda: max(60, min(100, int(_env("FUZZY_SCORE", "82")))))
    fuzzy_max_keys: int = field(default_factory=lambda: int(_env("FUZZY_MAX_KEYS", "5000")))

    live_autocorrect: bool = field(default_factory=lambda: _env_bool("LIVE_AUTOCORRECT", False))
    live_fuzzy: bool = field(default_factory=lambda: _env_bool("LIVE_FUZZY", True))
    live_cache: bool = field(default_factory=lambda: _env_bool("LIVE_CACHE", True))
    live_min_word_len: int = field(default_factory=lambda: max(1, int(_env("LIVE_MIN_WORD_LEN", "3"))))
    live_fuzzy_threshold: int = field(default_factory=lambda: max(50, min(99, int(_env("LIVE_FUZZY_THRESHOLD", "92")))))
    live_cooldown_ms: int = field(default_factory=lambda: max(0, int(_env("LIVE_COOLDOWN_MS", "150"))))
    live_use_clipboard_fallback: bool = field(default_factory=lambda: _env_bool("LIVE_CLIPBOARD_FALLBACK", True))
    prewarm: bool = field(default_factory=lambda: _env_bool("PREWARM", False))

    phrase_buffer_max: int = field(default_factory=lambda: max(0, min(20, int(_env("PHRASE_BUFFER_MAX", "0")))))
    perf: bool = field(default_factory=lambda: _env_bool("PERF", False))
    inject_prefer_type: bool = field(default_factory=lambda: _env_bool("INJECT_TYPE_FIRST", True))

    backend: str = field(default_factory=lambda: _env("BACKEND", "pynput"))
    clipboard_restore: bool = field(default_factory=lambda: _env_bool("CLIPBOARD_RESTORE", False))

    debug_keys: bool = field(default_factory=lambda: _env_bool("DEBUG", False))
    verbose: bool = field(default_factory=lambda: _env_bool("VERBOSE", False))

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

    @classmethod
    def load(cls) -> "Settings":
        """Default paths + env overrides."""
        return cls()
