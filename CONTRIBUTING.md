# Contributing

Thanks for helping improve the AI Conversation Archive Toolkit.

## Before opening an issue or pull request

- Search existing issues and check whether the behavior changed in the supported website.
- Include the application version, browser/userscript manager or Python version, operating system, and a minimal reproduction.
- Use synthetic or carefully redacted sample data only. Never upload real conversation archives, cookies, authorization headers, API keys, session tokens, or personal account identifiers.

## Code changes

- Keep site-specific extraction in `browser/src/adapters/<site>.js`.
- Keep common userscript UI, ZIP writing, and orchestration in `browser/src/main.template.js`.
- Rebuild the distribution with `python browser/build.py` after changing browser sources.
- Keep UI strings in locale JSON; avoid adding hard-coded user-facing text when the translation system applies.
- Keep Python modules focused and use the standard library unless a new dependency is justified and documented.
- Keep branch matching conservative. A same-topic pair is not necessarily a fork. Add positive and negative synthetic tests for matcher changes.
- Add provider tests using mocked HTTP responses; do not send test transcripts or credentials to real services.

## Validation

```bash
python -m compileall -q chat_topic_finder tests
python -m unittest discover -s tests -v
python browser/build.py
node --check browser/dist/ai-chat-backup.user.js
```

## Pull request checklist

- [ ] No private user data, real API keys, tokens, cookies, or local absolute paths added.
- [ ] Tests cover the change.
- [ ] Browser bundle rebuilt if userscript sources changed.
- [ ] Locale JSON updated for added visible text.
- [ ] Remote-data behavior and privacy implications documented.
