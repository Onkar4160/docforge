# DocForge

DocForge is a Python application for creating editable PowerPoint (`.pptx`), Word (`.docx`), and Excel (`.xlsx`) deliverables from natural-language requests. It combines a web chat interface and CLI with a FastAPI backend, structured artifact models, renderers, validation, and configurable research/LLM providers.

The codebase is under active development. Capabilities and verification evidence change by stage; consult [docs/STATUS.md](docs/STATUS.md) and [docs/PLAN.md](docs/PLAN.md) for the recorded project status. This README describes the checked-in setup and current entry points, not a promise that every planned feature is complete.

## Features

- Serves a browser UI and REST API from one FastAPI process.
- Uses JWT login with one configured username/password in the current implementation.
- Stores sessions and records in SQLite by default, with a filesystem blob store; SQLAlchemy supports a configured PostgreSQL URL.
- Has generation and editing components for office formats; the CLI can generate an artifact using the configured LLM.
- Supports Gemini and OpenAI-compatible LLM providers, Tavily web search, academic search providers, optional Pinecone retrieval, and local retrieval.
- Accepts supported source/template uploads with size and file-type checks.
- Analyzes PPTX templates into deterministic manifests plus cached, evidence-bounded design guidance.
- Supports stable-ID slide insertion/reordering, scoped presentation styling, and confirmation before warned style changes.
- Runs offline tests using fakes and fixtures; external-service tests are opt-in where present.
- Uses LibreOffice only for optional conversion/visual checks; it is not required to start the app.

See [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) for component responsibilities and [docs/API.md](docs/API.md) for the implemented HTTP routes.

## Technology

- Python 3.12 or later; `src/`-layout package installed through `pyproject.toml`.
- FastAPI and Uvicorn; Pydantic v2 and pydantic-settings.
- SQLAlchemy, SQLite by default.
- `python-pptx`, `python-docx`, `openpyxl`, Pillow, matplotlib, `lxml`, `defusedxml`, `pypdf`, and `formulas` for office files, data, and validation.
- Pytest and Ruff for development.
- Static HTML/CSS/JavaScript frontend served by the Python app; there is no frontend build step documented by the repository.

## Prerequisites

- Python 3.12+ and `pip`.
- Windows PowerShell, macOS, and Linux are suitable for development. The repository includes PowerShell and batch launchers for Windows.
- An LLM provider credential/server is needed for live generation, not for installing the package, running the web app, or running the default offline tests.
- Tavily is needed for authenticated web search. Other integrations and LibreOffice are optional; see [CONFIGURATION.md](CONFIGURATION.md).

## Install and run

From PowerShell at the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` only for settings you need. For live generation configure a supported LLM provider and model; set `TAVILY_API_KEY` for authenticated web research. Do not commit `.env` or put credentials in source control.

Start the server from the same repository directory:

```powershell
.\.venv\Scripts\python.exe -m docforge.cli serve --reload
```

Open <http://127.0.0.1:8000/>. The checked-in defaults are `DEMO_USERNAME=demo` and `DEMO_PASSWORD=demo123`; change them before sharing access. API documentation is at <http://127.0.0.1:8000/docs>, and the unauthenticated health endpoint is <http://127.0.0.1:8000/health>.

On macOS/Linux, activate the environment with `source .venv/bin/activate`, install with `python -m pip install -e ".[dev]"`, then run `docforge serve --reload`.

For the detailed fresh-machine steps and Windows launcher behavior, see [INSTALLATION.md](INSTALLATION.md) and [GETTING_STARTED.md](GETTING_STARTED.md).

## CLI

The installed `docforge` command currently provides `health`, `serve`, and `generate`. For example:

```powershell
docforge health
docforge serve --host 127.0.0.1 --port 8000 --reload
docforge generate "Create a short project overview" --output overview.pptx
```

Generation requires a working LLM configuration. See [docs/CLI.md](docs/CLI.md); commands such as `eval`, `edit`, and `analyze-template` are not present in the current CLI parser.

## Tests and code quality

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check src tests
```

The default pytest configuration excludes tests marked `live` and `visual`. Live tests may consume external-service quota; visual checks require LibreOffice. See [docs/TESTING.md](docs/TESTING.md).

## Configuration and data

Settings are read from process environment variables and `.env` in the current working directory. SQLite defaults to `./storage/app.db`; uploaded/generated blobs are stored below `./storage`. The runtime data directory is ignored by Git. For all supported settings, defaults, and required credentials, see [CONFIGURATION.md](CONFIGURATION.md).

## Troubleshooting

- If PowerShell blocks `run.ps1`, use the direct Python command above or invoke the script for the current process with `PowerShell -ExecutionPolicy Bypass -File .\run.ps1`.
- If `docforge` is not recognized, install the project in the active environment with `python -m pip install -e ".[dev]"`, or use `python -m docforge.cli`.
- If the server cannot bind, choose another port with `docforge serve --port 8001`.
- If generation reports missing provider configuration, configure the selected LLM provider; starting the server alone does not prove LLM credentials work.

More symptom-specific diagnostics are in [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Security and license

The default demo credentials and placeholder JWT secret are for local development only. Set unique credentials and a high-entropy `JWT_SECRET` before exposing the service; use TLS and a secret manager in any deployment. See [SECURITY.md](SECURITY.md) for verified behavior and limitations.

No license file or license declaration was found in the repository when these docs were prepared. No licensing terms are implied; the repository owner must choose and add a license.

## Documentation index

| Guide | Contents |
|---|---|
| [INSTALLATION.md](INSTALLATION.md) | Full installation, Windows-first with macOS/Linux equivalents |
| [GETTING_STARTED.md](GETTING_STARTED.md) | Short path to launch and smoke-test the app |
| [CONFIGURATION.md](CONFIGURATION.md) | Environment variables and defaults from `core/config.py` |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Structure, workflow, debugging, and quality checks |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Repository policy and recommended contribution workflow |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Diagnostics and safe fixes |
| [SECURITY.md](SECURITY.md) | Secrets, authentication, uploads, and reporting guidance |
| [docs/API.md](docs/API.md) | Implemented API endpoints and request examples |
| [docs/CLI.md](docs/CLI.md) | Implemented command-line interface |
| [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) | Architecture and data flow |
| [docs/architecture/DECISIONS.md](docs/architecture/DECISIONS.md) | Architecture decisions |
| [docs/DATA_MODELS.md](docs/DATA_MODELS.md) | Shared models and contracts |
| [docs/TESTING.md](docs/TESTING.md) | Test layout and verified commands |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Local operation and deployment limitations |
| [docs/PRD.md](docs/PRD.md), [docs/PLAN.md](docs/PLAN.md), [docs/STATUS.md](docs/STATUS.md), [docs/QUALITY.md](docs/QUALITY.md) | Product, plans, recorded status, and quality criteria |
| [AGENTS.md](AGENTS.md) | Runtime-agent roles and repository conventions |
