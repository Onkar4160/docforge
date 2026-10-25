# Troubleshooting

Run commands from the repository root unless a step says otherwise. Items labeled **Potential** describe common environment issues; they are not asserted to have occurred in every installation.

## `py` or Python 3.12 is not found (Potential)

**Symptom:** `py -3.12` fails, or `pip install` reports an unsupported Python version.

**Likely cause:** Python 3.12+ is not installed or the wrong interpreter is active. `pyproject.toml` requires Python `>=3.12`.

**Diagnose:**

```powershell
py --list
python --version
```

**Fix:** Install Python 3.12 or newer, then recreate `.venv` with the intended interpreter. Do not delete an environment until confirming it contains no needed local changes.

**Verify:** `\.venv\Scripts\python.exe --version` reports 3.12 or later.

## Virtual environment activation is blocked (Potential)

**Symptom:** PowerShell refuses to run `Activate.ps1` due to execution policy.

**Likely cause:** The active PowerShell policy blocks scripts.

**Diagnose:** `Get-ExecutionPolicy -List`.

**Fix:** Activation is optional. Use `\.venv\Scripts\python.exe -m pip ...` and `\.venv\Scripts\python.exe -m docforge.cli ...` directly. Avoid changing machine-wide policy solely for this project.

**Verify:** Run `\.venv\Scripts\python.exe -m docforge.cli --help`.

## `docforge` is not recognized (Potential)

**Symptom:** PowerShell cannot find the `docforge` command.

**Likely cause:** The package is not installed in the active environment or its Scripts directory is not on PATH.

**Diagnose:** `\.venv\Scripts\python.exe -m pip show docforge`.

**Fix:** From the repository root, run `\.venv\Scripts\python.exe -m pip install -e ".[dev]"`, then either activate `.venv` or keep using `python -m docforge.cli` with that interpreter.

**Verify:** `\.venv\Scripts\python.exe -m docforge.cli --help` lists `health`, `generate`, and `serve`.

## `run.ps1` cannot find the project or dependencies (Potential)

**Symptom:** The launcher starts but Uvicorn or imports fail.

**Likely cause:** The launcher does not create the virtual environment or install dependencies. It uses `.venv` if present and otherwise falls back to system Python.

**Diagnose:** Check `Test-Path .\.venv\Scripts\python.exe` and run the direct CLI help command.

**Fix:** Follow [INSTALLATION.md](INSTALLATION.md) before running the launcher, or start directly with `.\.venv\Scripts\python.exe -m docforge.cli serve`.

**Verify:** The server prints a Uvicorn startup message and `/health` responds.

## Wrong working directory or `.env` is ignored (Potential)

**Symptom:** Settings or relative paths do not match expectations.

**Likely cause:** `.env` is loaded from the process working directory, and relative storage/template paths are also working-directory relative.

**Diagnose:** `Get-Location`; `Test-Path .env`; `Test-Path pyproject.toml`.

**Fix:** Change to the directory containing `pyproject.toml` before starting the app.

**Verify:** Run `docforge health` and confirm the reported storage path is the intended one.

## API reports 401 Unauthorized

**Symptom:** Calls under `/api` return 401.

**Likely cause:** A bearer token is missing, expired, or invalid. `POST /api/auth/login` is public; other `/api` routes require a bearer token when `AUTH_ENABLED=true`.

**Diagnose:** Log in with configured `DEMO_USERNAME` and `DEMO_PASSWORD`; inspect whether the response includes `access_token`.

**Fix:** Send `Authorization: Bearer <access_token>` and log in again if the token expired. Never paste real tokens into tickets.

**Verify:** `GET /api/auth/me` returns the configured username.

## Production startup rejects `JWT_SECRET`

**Symptom:** Startup raises `JWT_SECRET must be changed before running with APP_ENV=prod`.

**Likely cause:** Authentication is enabled and the default placeholder secret remains configured.

**Diagnose:** Check `APP_ENV`, `AUTH_ENABLED`, and the secret's presence without printing the secret value.

**Fix:** Set a strong random `JWT_SECRET` through a protected environment/secret manager and replace the demo credentials.

**Verify:** Start with `APP_ENV=prod` and auth enabled; confirm startup proceeds. Do not disable auth to bypass this check on a shared instance.

## LLM generation fails (Potential)

**Symptom:** App starts, but a generation request reports a missing key, unavailable model, quota, or provider connection error.

**Likely cause:** Startup does not validate external credentials. The configured provider, model, key, or local server may be unavailable.

**Diagnose:** Run `docforge health`; inspect `LLM_PROVIDER`, `LLM_PRIMARY_MODEL`, fallback configuration, and the relevant provider endpoint. Do not echo secrets.

**Fix:** Configure the key for the selected provider or point `OPENAI_COMPAT_BASE_URL` at a reachable compatible server. Select a model available to that provider. Provider usage may incur charges or quota limits.

**Verify:** Perform a small generation request and confirm an artifact is returned; the health endpoint alone is not sufficient verification.

## Web research reports unavailable (Potential)

**Symptom:** Research is unavailable or says `TAVILY_API_KEY` is required.

**Likely cause:** Authenticated web search is the default and no Tavily key is configured.

**Diagnose:** Check whether `TAVILY_API_KEY` is configured without printing it and inspect `REQUIRE_AUTHENTICATED_WEB_SEARCH`.

**Fix:** Add a valid Tavily key, or for local development only set `REQUIRE_AUTHENTICATED_WEB_SEARCH=false` to permit the keyless fallback.

**Verify:** Use a research request and inspect its reported sources/status. Do not treat provider selection as proof the search service is reachable.

## Port 8000 is already in use (Potential)

**Symptom:** Uvicorn cannot bind to the configured port.

**Likely cause:** Another process is listening on port 8000.

**Diagnose:** `Get-NetTCPConnection -LocalPort 8000 -State Listen`.

**Fix:** Select another port, for example `docforge serve --port 8001`. Do not terminate another process unless you have identified it and know it is safe to stop.

**Verify:** Open `http://127.0.0.1:8001/health`.

## Database or storage write error (Potential)

**Symptom:** Startup or requests fail with SQLite, permission, or disk-write errors.

**Likely cause:** The storage directory is not writable, disk space is exhausted, or the configured database path is invalid.

**Diagnose:** Check free disk space and `Test-Path .\storage`; inspect `DATABASE_URL` and `STORAGE_DIR` without deleting data.

**Fix:** Ensure the configured parent directory exists and is writable; point `STORAGE_DIR` or `DATABASE_URL` to an appropriate location. Back up existing files before any manual database operation.

**Verify:** Run `docforge health` and confirm its database field is `true`/status is healthy.

## LibreOffice checks are skipped (Potential)

**Symptom:** Conversion or visual checks report skipped.

**Likely cause:** LibreOffice is optional and not found.

**Diagnose:** Run `docforge health` and check its `libreoffice` value; check `Get-Command soffice`.

**Fix:** Install LibreOffice if the workflow needs it, or set `LIBREOFFICE_PATH` to the executable.

**Verify:** Restart the app and re-check health/report output.

## Upload rejected or too large (Potential)

**Symptom:** Upload returns a file validation error or HTTP 413.

**Likely cause:** Content does not match a supported file type, a template role was assigned to a non-template-capable file, or the upload exceeds `UPLOAD_MAX_MB` (default 25).

**Diagnose:** Check the actual file format and upload role; inspect the configured size limit.

**Fix:** Upload a valid file with the appropriate `template`, `source`, `dataset`, or `unknown` role, or intentionally adjust `UPLOAD_MAX_MB` for a trusted local environment.

**Verify:** Retry and confirm the API returns upload metadata; do not use extensions alone to disguise file contents.