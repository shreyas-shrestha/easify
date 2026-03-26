# Easify

**Easify turns short phrases you type into full text**—definitions, fixes, conversions, snippets, and answers—using your keyboard everywhere you write. It tries **fast local shortcuts first**, then **cached AI answers**, and only then talks to an **LLM** (typically **Ollama** on your machine) so normal typing stays snappy.

---

## What it does for you

### Deliberate expansion (`//` by default)

- Type a **trigger** (default `//`), your **request**, then **close** with the same characters again (e.g. `//hello world//`)—or press **Enter** to submit if you set it up that way.
- **Esc** cancels without sending anything to the AI.
- You can **keep typing while it works**; Easify merges your extra keystrokes with the result so you are not blocked waiting.
- **Undo** with an optional hotkey (e.g. restore what was there before the last expansion).

### Works like a smart stack

1. **Instant math & units** — Arithmetic, dates like “today + 14 days”, **unit conversions** (e.g. inches → cm), **currency** (live rates with a small on-disk cache).
2. **Snippets** — Your **exact** shortcuts from JSON (`~/.config/easify/snippets.json`).
3. **Autocorrect** — Fixes typos in what you captured before matching snippets.
4. **Fuzzy snippets** — Close matches when you slightly mistype a snippet key.
5. **Semantic snippets** *(optional)* — Similar meaning when exact/fuzzy miss (`pip install easify[semantic]`).
6. **Answer cache** — Reuses past AI answers for the same kind of prompt.
7. **LLM** — **Ollama** (default), or **OpenAI** / **Anthropic** if you configure keys.

So: many requests never hit the network; repeated questions reuse the cache.

### While you type (live mode)

- After you press **Space**, Easify can **fix the word you just finished** using autocorrect, snippets, fuzzy match, and cache—**without** opening `//` capture.
- Optional **background** jobs can **fill the cache** for common words so the next time is instant.

### Snippets extras

- **Placeholders** in snippet text: dates, time, clipboard, focused app name, and **`{input:...}`** prompts on the capture path for fill-in-the-blank expansions.
- **Namespaces** like `slack:thanks` so the same key can mean different things per app.
- **Web UI** — `easify ui` to edit snippets in the browser (with a simple token for safety).
- **Promote cache hits** to snippets *(optional)* after enough repeats—so your best AI answers become shortcuts.

### Safety & comfort

- **System tray** — Status (thinking / idle / error), model id, queue info; menu to **copy the last error** or **dismiss** it.
- **Expansion preview** *(optional)* — Confirm before inserting the AI text.
- **Accessibility inject** *(optional, macOS/Windows)* — Swap text in the focused field in one step when the OS allows; falls back to typing/paste. Password-style fields are skipped when detectable.
- **URL awareness** — Default `//` is ignored right after `https://`, `http://`, etc., so links do not accidentally start capture.

### Tools

- **`easify doctor`** — Quick check of config, disk paths, and whether your AI backend responds.
- **`easify init`** — Seeds default config/snippets under `~/.config/easify/`.
- **`easify autostart`** — Install or remove login startup (macOS / Linux / Windows).

---

## Quick start

1. Install **[Ollama](https://ollama.com)** and pull a model, e.g. `ollama pull phi3`.
2. Install Easify:

   ```bash
   pip install git+https://github.com/shreyas-shrestha/easify.git
   # or: clone the repo and pip install .
   ```

3. *(Optional)* `easify init`
4. Run:

   ```bash
   easify
   # or: python -m app
   ```

5. **macOS:** allow **Accessibility** and **Input Monitoring** for the app that runs Easify (Terminal, etc.).

**Try:** `//5 inches to cm//`, `//fix recieve//`, or a snippet key you add to `snippets.json`.

---

## Other ways to open capture

- **Palette hotkey** — Set `EASIFY_PALETTE_HOTKEY` to a chord; a small window opens so you type intent without `//`.
- **Double-space** — Opt in with `EASIFY_ACTIVATION_DOUBLE_SPACE=1` (off by default so normal sentence spacing does not trigger capture).

---

## Configuration (basics)

- Most options use **`EASIFY_*`** environment variables.
- Optional **TOML**: `~/.config/easify/config.toml` — see `data/config.example.toml` in the repo. **Env wins** over the file.
- Common knobs:

  | Variable | What it does |
  |----------|----------------|
  | `EASIFY_TRIGGER` / `EASIFY_CAPTURE_CLOSE` | Delimiters (default `//`) |
  | `OLLAMA_URL` / `EASIFY_MODEL` / `OLLAMA_MODEL` | Ollama endpoint and model |
  | `EASIFY_AI_PROVIDER` | `ollama` (default), `openai`, `anthropic` |
  | `EASIFY_TRAY` | `0` to disable tray on headless servers |
  | `EASIFY_EXPANSION_PREVIEW` | `1` to confirm each expansion |
  | `EASIFY_PALETTE_HOTKEY` | Global hotkey for the palette |

For the full list, see `app/config/settings.py`.

---

## Optional installs

| Extra | Command | Purpose |
|-------|---------|---------|
| Semantic snippets | `pip install easify[semantic]` | “Meaning-close” snippet match |
| Accessibility inject | `pip install easify[accessibility]` | macOS AX / Windows UIA text swap |
| Dev / tests | `pip install easify[dev]` | `pytest`, etc. |

---

## Project layout (short)

- `app/main.py` — CLI: `run`, `init`, `ui`, `doctor`, `autostart`
- `app/engine/` — Pipeline, background worker, expansion queue
- `app/keyboard/` — Listener and capture logic
- `app/snippets/`, `app/autocorrect/`, `app/cache/` — Data and storage
- `app/ai/` — LLM clients and prompts

---

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

---

## License

MIT
