# Contributing

This repository's [AGENTS.md](AGENTS.md) defines project engineering conventions. No formal branch naming, commit message convention, pull-request template, or public contribution workflow was found. The workflow below is recommended guidance, not an existing maintainer policy.

## Prerequisites and setup

Use Python 3.12+ and install the editable package with development dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

See [INSTALLATION.md](INSTALLATION.md) for the full setup and platform-specific commands.

## Before proposing a change

- Search for the owning module and nearby tests; keep changes scoped to the behavior being changed.
- Add or update tests for behavior changes. The default tests should remain deterministic and offline.
- Run `python -m pytest` and `python -m ruff check src tests` from the repository root.
- Update documentation when commands, configuration, API behavior, data contracts, architecture, or verification status changes.
- Never commit `.env`, credentials, `storage/`, generated deliverables, or cassettes containing private data.

## Code conventions

The project guidance calls for Python type hints, Pydantic v2 models for cross-component data, Ruff formatting/lint conventions, small single-purpose modules, deterministic rendering, and project-owned adapters for external services. New external integrations should have a fake or fixture counterpart for tests. Agents should use the `LLMClient` abstraction rather than importing provider SDKs directly.

## Suggested pull-request workflow

These are recommendations, not established repository rules:

1. Create a focused branch from the repository's current default branch.
2. Keep each change reviewable and describe the behavior and rationale.
3. Include test results and note any tests requiring credentials or optional tools that were not run.
4. Update relevant docs and add screenshots/output examples only when they contain no secrets or private user content.
5. Report known limitations and configuration changes clearly.

## Bug reports

Include the operating system, Python version, command or API route, sanitized error output, and steps to reproduce. Remove API keys, bearer tokens, uploaded business data, database files, and private cassettes. For suspected security issues, follow the reporting guidance in [SECURITY.md](SECURITY.md); a private contact should be added by the repository owner.