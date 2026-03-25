# Easify
Supercharge writing with llm-based text expansion anywhere you want to write, and for anything you want to write. clarification, spell check, unit conversion, emojis, now happens automatically.

Type a trigger (default `///`), your intent, **Enter** → local **Ollama** returns plain text → pasted inline. JSON **snippets** resolve first (exact + optional fuzzy match). 

## Install

```bash
git clone https://github.com/shreyas-shrestha/easify.git
cd easify
pip install .
# or: pip install git+https://github.com/shreyas-shrestha/easify.git

easify init    # optional: ~/.config/easify/snippets.json
easify         # or: python -m easify
```

**macOS:** grant **Accessibility** and **Input Monitoring** to Terminal (or your IDE). Default backend is **pynput** (no sudo).

**Ollama:** run `ollama serve` and e.g. `ollama pull phi3`.

## Environment

Prefer **`EASIFY_*`** variables. **`OLLAMA_EXPANDER_*`** still works for compatibility.

| Variable | Meaning |
|----------|---------|
| `EASIFY_TRIGGER` | Prefix (default `///`) |
| `EASIFY_SNIPPETS` | Path to snippets JSON (default `~/.config/easify/snippets.json`) |
| `EASIFY_FUZZY_MAX` | Levenshtein radius for snippet keys (default `2`; `0` = exact only) |
| `EASIFY_BACKEND` | `auto`, `pynput`, `keyboard` |
| `EASIFY_CLIPBOARD_RESTORE` | `1` = restore clipboard shortly after paste |
| `EASIFY_RETRIES` | Ollama HTTP retries (default `2`) |
| `EASIFY_DEBUG` | `1` = log keys on stderr |
| `OLLAMA_URL`, `OLLAMA_MODEL` | Ollama endpoint and model name |

Intent hints in the captured text steer the model, e.g. `emoji happy`, `fix teh`, `convert 5 ft to meters`.

## Snippets

JSON object of lowercase-ish keys → expansions. See `easify/snippets.example.json`.

**Repo:** [github.com/shreyas-shrestha/easify](https://github.com/shreyas-shrestha/easify)
