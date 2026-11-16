# Architecture

## Design principle

Keep authenticated-site extraction separate from offline analysis. The browser tool knows how to read supported web apps. The Python tool only consumes exported files. Their integration is file-based: ZIP archives, manifests, transcripts, and a retry list.

## Browser userscript

`browser/src/main.template.js` contains shared UI, configuration, ZIP writing, download orchestration, manifest generation, and the standalone archive viewer. Each provider adapter exports the site-specific operations needed by the shared driver:

- `adapters/claude.js`
- `adapters/chatgpt.js`
- `adapters/gemini.js`

`browser/build.py` inserts the adapters and required locale strings into the template and emits one userscript at `browser/dist/ai-chat-backup.user.js`. The distribution is intentionally self-contained because userscript managers expect a single installable file.

When adding an adapter, keep provider-specific endpoint discovery, pagination, parsing, and artifact enumeration inside that adapter. Shared UI, persistence, retry policy, and ZIP writing belong in the template only when they are genuinely platform-independent.

## Python analysis package

- `common.py`: data models and shared constants.
- `text.py`: normalization, transcript parsing, tokenization, and turn extraction.
- `ingest.py`: ZIP, manifest, Markdown, JSON, and loose-file loading.
- `similarity.py`: lexical features, pair scoring, and topic grouping.
- `indexing.py`: persistent SQLite cache and full-text search.
- `branches.py`: branch/fork candidate detection from ordered transcript prefixes.
- `llm.py`: optional LLM provider requests, report normalization, cache, and cross-chat grading.
- `reports.py`: HTML and machine-readable report generation.
- `app.py`: orchestration, CLI, and Tkinter interface.
- `i18n.py` plus `locales/*.json`: editable translations.

## Branch-matching method

The branch matcher builds a candidate index from title and opening-user-message trigrams, then compares candidate pairs in order. Pair scoring aligns roles, compares consecutive transcript turns, measures the shared-prefix length, and checks whether each conversation continues beyond the common prefix. Exact duplicate digests are skipped. Accepted pairs are joined into connected candidate families.

The matcher is intentionally conservative and heuristic. It does not have access to a provider's internal branch/tree metadata in ordinary exported Markdown. It can miss a fork when edits alter the beginning of a transcript or when the export omits ordered message turns. Do not describe a match as a confirmed provider-side branch unless the source export itself supplies that relationship.

## LLM providers

The LLM layer supports:

- Ollama's native `/api/chat` request shape.
- Anthropic's Messages API.
- OpenAI-compatible `/chat/completions` endpoints, including compatible self-hosted servers and services that document this API.

Provider, base URL, model name, and credentials are configuration, not hard-coded machine assumptions. Local processing remains the default. Remote requests are opt-in and require a selected model/provider. Cache keys include the provider, endpoint, and model so reports from different backends are not silently mixed.

## Translation flow

`locales/en.json` is the English base. `locales/he.json` contains Hebrew strings for the Python UI, userscript, and generated report. Python loads locale files at runtime. The browser build embeds only the userscript dictionary in the generated self-contained file.
