# AI Chat Toolkit

> **Repository description:** Local-first backup, topic discovery, and branch matching for ChatGPT, Claude, Gemini, and other AI chats.

AI Chat Toolkit is a local-first toolkit for keeping, exploring, and connecting conversations exported from AI assistants.

It contains **two companion tools**:

1. **AI Chat Backup** — a browser userscript for exporting conversations and their available artifacts, attachments, generated media, and tool/script output from supported AI chat sites.
2. **Chat Topic Finder** — a Python application that indexes exported conversations, finds related topics, identifies likely forked conversation branches, and produces a searchable HTML report plus CSV/JSON data.

The tools can be used independently. Together, the backup userscript can create ZIP archives that Chat Topic Finder understands, and Chat Topic Finder can emit a repair list that the userscript can import.

> **Status:** community-ready project structure / early public beta. Site adapters depend on changing private web-app interfaces and may need maintenance when a provider changes its UI or API. Review the limitations and privacy notes before using it on important archives.

## Why two tools?

The backup and analysis jobs have different trust and runtime requirements. The browser userscript can access the signed-in chat page and download its content. The Python tool can analyse previously exported files without needing a browser session. Keeping them separate avoids mixing account access, archive storage, and analysis logic.

## Features

### AI Chat Backup

- Platform adapters are separated by site: Claude, ChatGPT, and Gemini.
- Saves raw chat data and Markdown transcripts, where available.
- Captures supported artifacts, canvas revisions, code snippets, uploads, generated files, and media on a best-effort basis.
- Supports chunked ZIP output, optional direct-to-disk streaming in compatible Chromium browsers, configurable file filters, retry limits, and export history.
- Includes a bilingual English/Hebrew interface and an offline archive viewer.
- Optional **script runs and execution results** setting adds supported tool/code execution calls and textual results to the Markdown transcript. Raw JSON capture remains controlled by its own setting.

The userscript is assembled from maintainable source modules but distributed as **one self-contained `.user.js` file** for Tampermonkey/Violentmonkey compatibility.

### Chat Topic Finder

- Reads backup ZIPs, `chat.md`, `raw.json`, Markdown, and text files.
- Uses an explainable lexical/TF-IDF matching pipeline, with optional LLM-generated topic reports.
- Identifies similar conversations and clusters them into topic groups.
- Detects likely **conversation branches** using a shared, ordered transcript prefix followed by divergent continuations. It does not treat same-topic conversations as branches merely because their subjects overlap.
- Provides a full-text SQLite FTS5 index when the Python SQLite build supports it (with a fallback search path).
- Exports an interactive HTML report, CSV files, JSON data, a SQLite index, and a repair list for missing backup items.
- Supports English and Hebrew UI/report translations in editable locale JSON files.

## Quick start

### 1. Get a browser backup

1. Install Tampermonkey or another compatible userscript manager.
2. Open `browser/dist/ai-chat-backup.user.js` from this repository and install it in the userscript manager.
3. Sign in to a supported chat site and open the backup panel.
4. Choose conversations and settings, then create a ZIP export.

The userscript needs to run on the relevant signed-in site to read the conversations. It does not require a separate server or database.

### 2. Analyse the exported chats

Python 3.10 or later is required. The analysis application uses the Python standard library; there are no mandatory third-party runtime packages.

```bash
# Run from a source checkout
python -m chat_topic_finder

# Or install the command-line entry point
python -m pip install -e .
chat-topic-finder --help
```

Choose one or more backup ZIPs or exported conversation files in the GUI. The default workflow is local/offline; optional AI analysis is disabled until a model and provider are configured.

To run a non-interactive analysis:

```bash
python -m chat_topic_finder --input /path/to/backup.zip --output /path/to/report
```

Use `python -m chat_topic_finder --help` for all options.

## Optional AI providers

AI analysis is optional. Topic matching, indexing, branch detection, and report generation work without an LLM.

The client supports three request styles:

| Provider setting | Protocol | Example base URL |
|---|---|---|
| `ollama` | Ollama `/api/chat` | `http://localhost:11434` |
| `openai-compatible` | `/chat/completions` | `https://api.openai.com/v1` |
| `anthropic` | Anthropic Messages API | `https://api.anthropic.com/v1` |
| `auto` | Chooses from URL clues | Defaults to local Ollama URL |

OpenAI-compatible services can include cloud services and self-hosted servers such as vLLM, LM Studio, or LocalAI when they implement the expected chat-completions API. Gemini's OpenAI-compatible endpoint can also be used by supplying Google's endpoint and API key.

Examples (replace `MODEL_ID` with a model offered by your provider):

```bash
# Local Ollama
python -m chat_topic_finder --input ./backup.zip \
  --llm-provider ollama \
  --llm-url http://localhost:11434 \
  --llm-model MODEL_ID

# OpenAI-compatible API
export OPENAI_API_KEY="..."
python -m chat_topic_finder --input ./backup.zip \
  --llm-provider openai-compatible \
  --llm-url https://api.openai.com/v1 \
  --llm-model MODEL_ID

# Gemini via Google's OpenAI-compatible endpoint
export GEMINI_API_KEY="..."
python -m chat_topic_finder --input ./backup.zip \
  --llm-provider openai-compatible \
  --llm-url https://generativelanguage.googleapis.com/v1beta/openai \
  --llm-model MODEL_ID

# Anthropic Messages API
export ANTHROPIC_API_KEY="..."
python -m chat_topic_finder --input ./backup.zip \
  --llm-provider anthropic \
  --llm-url https://api.anthropic.com/v1 \
  --llm-model MODEL_ID
```

Set credentials in the environment or enter them in the GUI. For Windows PowerShell, set an environment variable with `$env:OPENAI_API_KEY = "..."` (or the corresponding `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`). Avoid putting API keys directly in shell history, source files, screenshots, or committed configuration. The application does not need an API key for local Ollama use.

**Privacy:** when a remote provider is selected, conversation excerpts are sent to that provider for analysis. The `--llm-max-chars` limit controls the per-chat excerpt size, not the provider's retention policy. Check the provider's terms and data controls before sending sensitive archives. The application does not silently send content to a remote AI provider when AI analysis is not configured.

## Automatic branch matching

Branch matching is enabled by default and can be disabled with `--no-branch-matching`.

A likely branch pair must have:

- multiple consecutive, role-aligned turns with a strong text match;
- a substantial shared opening transcript;
- evidence of a related title or near-identical opening user prompt; and
- different continuation on both sides after the shared prefix.

This deliberately conservative rule helps distinguish sibling forks from conversations that merely discuss the same theme. Results are **heuristic candidates, not proof**. Edited prompts, missing turns, different export formats, or very short shared prefixes can cause missed matches; boilerplate-heavy transcripts can still create false positives.

The analysis writes:

- `branch_matches.csv` — pairwise match scores and shared-prefix metrics.
- `branch_families.json` — connected groups of candidate sibling conversations.
- A “Related conversation branches” section in `topic_report.html`.

Raw message order is best preserved when the input contains the userscript's Markdown transcript or a JSON export with an ordered message list / supported message mapping.

## Project layout

```text
.
├── browser/
│   ├── src/
│   │   ├── main.template.js
│   │   └── adapters/
│   │       ├── claude.js
│   │       ├── chatgpt.js
│   │       └── gemini.js
│   ├── dist/ai-chat-backup.user.js
│   └── build.py
├── chat_topic_finder/
│   ├── app.py          # CLI and Tkinter UI
│   ├── branches.py     # shared-prefix branch matching
│   ├── common.py       # data models and constants
│   ├── indexing.py     # SQLite/FTS indexing
│   ├── ingest.py       # ZIP and file ingestion
│   ├── llm.py          # local/remote AI providers
│   ├── reports.py      # HTML, CSV and JSON reports
│   ├── similarity.py   # similarity and grouping
│   ├── text.py         # parsing and language-aware text features
│   └── locales/        # editable English/Hebrew strings
├── tests/
├── docs/
└── pyproject.toml
```

## Build and test from source

The browser bundle is generated from the template, three site adapters, and the Hebrew locale file:

```bash
python browser/build.py
```

The generated `browser/dist/ai-chat-backup.user.js` is the installable userscript. Do not install the template or individual adapter files separately.

Run tests:

```bash
python -m compileall -q chat_topic_finder tests
python -m unittest discover -s tests -v
node --check browser/dist/ai-chat-backup.user.js
```

No Node packages are required; the build script uses Python's standard library.

## Translation

Translations are kept outside the main application code:

- `chat_topic_finder/locales/en.json`
- `chat_topic_finder/locales/he.json`

The Python UI and generated HTML report load their strings from these files. The browser build embeds the Hebrew userscript strings into the self-contained distribution, so the installed userscript does not make a runtime request for a locale file. When changing userscript UI text, update `he.json` and rebuild the bundle.

## Privacy, security, and data handling

- Back up only accounts and conversations you are authorized to access.
- Archive files may contain private prompts, assistant replies, names, attachments, generated files, and account metadata. Treat ZIPs and generated reports as sensitive data.
- Do not commit exported conversations, backup ZIPs, API keys, cookies, session tokens, or local database files.
- The browser userscript uses the active site's authenticated session to retrieve content and requests. Inspect the source before installing it; it is not a passive page-only viewer.
- Remote LLM providers receive the excerpt content needed for analysis. Prefer local inference for sensitive archives.
- The scripts are provided as-is. Site changes can break extraction, and no backup system can guarantee every transient image, video, artifact revision, or tool output is recoverable.

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for module boundaries.

## Contributing

Bug reports and adapter fixes are welcome. Please use synthetic or redacted sample exports; never attach real private chat archives, cookies, API keys, or session data to an issue. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

This project is released under the [MIT License](LICENSE). You may use, copy, modify, merge, publish, distribute, sublicense, and sell copies of the Software subject to the license terms.
