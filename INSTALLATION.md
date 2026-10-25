# Installation

This guide installs the checked-in Python application from a local project folder. Run commands from the repository root: the directory containing `pyproject.toml`, `.env.example`, and `src/`.

## Requirements

| Requirement | Required | Notes |
|---|---|---|
| Python 3.12+ | Yes | Declared in `pyproject.toml`; use a supported 64-bit installation where available. |
| pip | Yes | Included with normal Python installations; upgrade it in the virtual environment. |
| Git | No | Needed only if cloning/updating from GitHub rather than using the downloaded archive. |
| LLM credentials or compatible local server | For live generation | Not required for installation, app startup, or the default offline test suite. |
| Tavily API key | For authenticated web research | Or explicitly enable the documented development fallback. |
| LibreOffice | No | Optional conversion and visual checks. |
| Database server | No | SQLite is the default; PostgreSQL can be selected with `DATABASE_URL`. |

Windows PowerShell, macOS, and Linux are suitable development environments. The repository includes `run.ps1` and `run.bat` for Windows. No Docker or Node.js setup is provided.

## Windows PowerShell

Open PowerShell in the repository root. Verify the working directory and Python version:

```powershell
Get-Location
py -3.12 --version
```

Create a virtual environment and install the project plus developer tools:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Optionally activate the environment for shorter commands:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation because of the current execution policy, do not change the machine-wide policy just for this project. Use the virtual environment's Python executable directly as shown above, or consult [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

Create a local environment file without overwriting an existing one:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` with a suitable provider configuration. For live generation, the default `LLM_PROVIDER=gemini` needs `GEMINI_API_KEY`; alternatively configure an OpenAI-compatible server. Add `TAVILY_API_KEY` for authenticated web research. Credentials are not needed to run offline tests.

Verify installation:

```powershell
.\.venv\Scripts\python.exe -m docforge.cli --help
.\.venv\Scripts\python.exe -m docforge.cli health
.\.venv\Scripts\python.exe -m pytest
```

The health command reports configuration and optional dependency discovery; it does not make a live request to prove credentials are accepted.

## macOS and Linux

From the repository root:

```bash
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
if [ ! -f .env ]; then cp .env.example .env; fi
python -m docforge.cli --help
python -m docforge.cli health
python -m pytest
```

Set up `.env` as described in [CONFIGURATION.md](CONFIGURATION.md).

## External services

External services are optional for package installation and offline operation. Configure only the services the workflow needs:

- LLM: Gemini, or an OpenAI-compatible server such as a compatible local endpoint.
- Web search: Tavily when authenticated web search is required. `REQUIRE_AUTHENTICATED_WEB_SEARCH=false` enables the development-only keyless fallback implemented by the project.
- Vector search: local storage is available; Pinecone requires an API key and an existing index with matching embedding dimensions.
- Academic search and image providers have optional credentials; see [CONFIGURATION.md](CONFIGURATION.md).
- LibreOffice is optional and is detected separately for conversion/visual functionality.

## Windows launcher scripts

`run.ps1` and `run.bat` start Uvicorn on `127.0.0.1:8000` in a separate console and open the browser. They use `.venv` when it exists, otherwise fall back to system Python; they do not create an environment or install dependencies. Install the project first. The direct command in [GETTING_STARTED.md](GETTING_STARTED.md) is easier to diagnose and supports a custom port.

## Common installation issues

- **Python version rejected:** install Python 3.12 or newer and create the environment with that interpreter.
- **`pip install -e ".[dev]"` fails:** run it from the repository root and confirm `pyproject.toml` is present.
- **`docforge` not found:** activate `.venv` or invoke `.\.venv\Scripts\python.exe -m docforge.cli`.
- **A package build fails due to disk space or permissions:** check free space and ensure the project and temporary directories are writable. Do not remove existing runtime data as a first response.
- **PowerShell activation is blocked:** use the virtual-environment executable directly; activation is optional.

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for diagnostics. The project does not provide database migrations; SQLite initializes through application startup.