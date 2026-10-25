# Getting Started

DocForge accepts a natural-language request and can create editable office deliverables through its web interface or CLI. The app also provides a REST API and persists sessions locally.

## Fastest setup on Windows

Run these commands from the folder containing `pyproject.toml`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env` to set your chosen model provider credentials before asking DocForge to generate files. With the default `LLM_PROVIDER=gemini`, live generation needs `GEMINI_API_KEY`. Without a working provider, the web app can still start and the offline test suite can still run, but live generation will not complete.

Start the app:

```powershell
.\.venv\Scripts\python.exe -m docforge.cli serve --host 127.0.0.1 --port 8000 --reload
```

When startup succeeds, Uvicorn prints a line similar to:

```text
Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Open <http://127.0.0.1:8000/>. The local demo login defaults to `demo` / `demo123`; change both values in `.env` before allowing another person to access the app. API docs are available at <http://127.0.0.1:8000/docs>.

## Smoke test

In a second PowerShell window, check the public health endpoint:

```powershell
$health = Invoke-RestMethod http://127.0.0.1:8000/health
$health.status
```

The expected healthy database status is `ok`. This endpoint reports settings and database reachability, but does not validate external credentials by making provider calls.

Test login and create a session:

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/auth/login `
  -ContentType 'application/json' `
  -Body (@{ username = 'demo'; password = 'demo123' } | ConvertTo-Json)

$headers = @{ Authorization = "Bearer $($login.access_token)" }
$session = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/sessions `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body (@{ title = 'Smoke test' } | ConvertTo-Json)
$session.id
```

For a generation smoke test, use the UI with a simple request after configuring a valid provider. Generation calls may incur provider costs. The CLI alternative is:

```powershell
.\.venv\Scripts\docforge.exe generate "Create a short project overview" --output overview.pptx
```

## Stop the server

Press `Ctrl+C` in the PowerShell window running Uvicorn. When launched with `run.ps1` or `run.bat`, close the separate server console or stop its foreground process with `Ctrl+C`.

For more detail, see [INSTALLATION.md](INSTALLATION.md), [CONFIGURATION.md](CONFIGURATION.md), and [docs/API.md](docs/API.md).