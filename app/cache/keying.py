"""Cache row keys for capture path (model + prompts fingerprint)."""


def capture_cache_row_key(model_id: str, user_prompt: str, system: str) -> str:
    """Stable key for SQLite cache rows (must match historical pipeline behavior)."""
    return f"{model_id}\n{system}\n{user_prompt}"
