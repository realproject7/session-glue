# Contributing

Session Glue is intended to be an open-source project. Keep all project content safe to publish.

## Sensitive Information Policy

Do not include:

- API keys, access tokens, cookies, session IDs, passwords, or private keys
- `.env` file contents
- production credentials or secret-dependent command output
- private customer data, private repo contents, or proprietary logs
- personal local paths when a generic path is enough
- screenshots that reveal secrets, account identifiers, dashboards, or private chats

Use placeholders instead:

- `/path/to/project`
- `<API_KEY>`
- `<TOKEN>`
- `<PRIVATE_REPO>`
- `<REDACTED>`

## Pull Request Expectations

Before opening a PR:

- run the relevant tests
- keep scope tied to one issue when practical
- update docs when behavior changes
- check that new fixtures and examples contain no real credentials or private data
- avoid adding daemons, MCP dependencies, embeddings, databases, watchers, product UI, telemetry, or cloud sync unless maintainers explicitly approve a scope change first

## Issues And Comments

GitHub issues and PR comments are public once the repository is public. Do not paste raw agent transcripts, local handoff files, logs, or screenshots unless they have been checked for sensitive content.
