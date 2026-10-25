# Development

## Environment

Use Python 3.12+ and install the project with development extras from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

See [INSTALLATION.md](INSTALLATION.md) for activation, `.env`, and macOS/Linux steps. Tests should use the fakes and fixtures provided by the repository and should not need network credentials by default.

## Repository layout

| Path | Responsibility |
|---|---|
| `src/docforge/agents/` | Narrow LLM agent roles. |
| `src/docforge/api/` | FastAPI application, dependency wiring, and route handlers. |
| `src/docforge/core/` | Configuration, authentication, errors, file checks, IDs, and logging. |
| `src/docforge/design/`, `layout/`, `template/` | Design tokens, geometry/text fitting, and template analysis. |
| `src/docforge/ingest/`, `research/`, `retrieval/`, `media/` | Uploaded source handling, research, retrieval, and image providers. |
| `src/docforge/llm/` | LLM gateway, provider adapters, embeddings, fakes, and cassette support. |
| `src/docforge/models/` | Shared Pydantic models and contracts. |
| `src/docforge/orchestrator/` | Generation/edit orchestration. |
| `src/docforge/render/`, `validate/` | Office-file renderers, previews, validation, and repair. |
| `src/docforge/storage/` | Database repositories and blob storage. |
| `src/docforge/web/static/` | Static frontend served by FastAPI. |
| `tests/unit/`, `tests/fixtures/` | Automated tests and shared fixtures. |
| `docs/` | Product, architecture, data-model, quality, test, and operational docs. |

## Run during development

```powershell
.\.venv\Scripts\python.exe -m docforge.cli serve --reload
```

The default host and port are `127.0.0.1:8000`. Use `--host` and `--port` to change them. The static UI is served by the same app; no frontend package install/build step is defined.

## Tests and lint

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
```

For a focused test, pass a test file, for example `tests/unit/test_api.py`. The default suite excludes tests marked `live` and `visual`. Details are in [docs/TESTING.md](docs/TESTING.md).

## Adding or changing behavior

1. Find the owning module and nearest test; keep route handlers thin and put behavior in the relevant service/component.
2. Keep contracts in `docforge.models` typed with Pydantic. Update [docs/DATA_MODELS.md](docs/DATA_MODELS.md) when a shared model or persisted contract changes.
3. Add or update unit tests using the existing fixtures and fake providers. Avoid network access in default tests.
4. Keep provider access behind existing project-owned interfaces. Do not call vendor SDKs directly from agents; the gateway and adapters own provider interaction.
5. For renderer/validator changes, use fixture artifacts and update [docs/QUALITY.md](docs/QUALITY.md) if checks or thresholds change.
6. Update architecture/decision docs for cross-component design changes and record verification evidence in [docs/STATUS.md](docs/STATUS.md), following [AGENTS.md](AGENTS.md).
7. Run pytest and Ruff for the changed slice before proposing the change.

## Configuration and data safety

Settings live in `src/docforge/core/config.py`; `.env.example` is the local template. Never commit `.env`, credentials, runtime `storage/`, generated artifacts, or cassettes containing private data. Avoid logging user file contents. Uploads and fetched webpages are untrusted inputs; preserve existing validation and isolation boundaries.

## Debugging

- Start with `docforge health` or `python -m docforge.cli health` to inspect effective provider choices and optional dependency discovery.
- Use `--reload` for local server iteration; the server logs startup errors in the terminal.
- API schemas and interactive requests are available from `/docs` while the app runs.
- Tests provide isolated settings through `tests/conftest.py`; use those rather than a developer `.env` for deterministic tests.
- For LLM-related failures, inspect configured provider/model and whether the call is live or replayed; do not expose tokens or API keys in logs or issue reports.

## Dependencies and style

Runtime and optional development dependencies are declared in `pyproject.toml`; add packages there rather than relying on a machine-global install. Project guidance in [AGENTS.md](AGENTS.md) specifies Ruff, type hints, Pydantic v2 at component boundaries, small focused modules, deterministic rendering, and fake/fixture twins for new external services.

No repository-specific branch naming, commit convention, or pull-request template was found. See [CONTRIBUTING.md](CONTRIBUTING.md) for explicitly recommended practices.