# Changelog

## Unreleased

- Add the MIT License (copyright holder: `kug-dev`, 2026).
- Declare the project license in package metadata and link it from the README.


## 2.3.0 / userscript 6.3 — repository modularization

- Split Chat Topic Finder into focused Python modules.
- Split browser extraction into Claude, ChatGPT, and Gemini source adapters while retaining a single installable userscript build.
- Moved Hebrew UI/report strings into editable locale JSON.
- Generalized optional AI analysis to Ollama, Anthropic Messages, and OpenAI-compatible endpoints.
- Added conservative conversation branch-family matching based on shared ordered transcript prefixes.
- Added tests for branch matching, provider request shapes, and userscript assembly.
