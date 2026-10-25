# Deployment and Operations

## Current support

The repository provides local process startup through the `docforge serve` CLI, Uvicorn, and Windows launchers. It does not include a Dockerfile, Compose definition, deployment manifests, database migration system, or a production deployment recipe. Treat hosted/container deployment as an operator-owned approach that requires additional review and testing, not as a supported one-click deployment.

## Local operation

Install Python 3.12+ and the project with its development extras as described in [INSTALLATION.md](../INSTALLATION.md). Start from the repository root so `.env` and relative storage paths resolve predictably:

```powershell
docforge health
docforge serve --host 127.0.0.1 --port 8000
```

The default database is SQLite at `./storage/app.db`; uploaded files, generated blobs, and recorded cassettes are stored under `STORAGE_DIR` (default `./storage`). Back up the database and storage directory together. SQLite/PostgreSQL URLs are passed through SQLAlchemy via `DATABASE_URL`; no migration command is currently provided.

## Production considerations (operator-managed, not repository-verified)

Before exposing the service to a network:

- Use a supported, currently patched Python runtime and install only pinned/reviewed dependencies in a controlled build.
- Set `APP_ENV=prod`, a randomly generated `JWT_SECRET`, non-default `DEMO_USERNAME` and `DEMO_PASSWORD`, and required provider credentials through a secret manager. The app refuses to start in production with the default JWT secret when authentication is enabled.
- Terminate TLS at a trusted reverse proxy; do not expose the development server directly to the public internet.
- Keep `STORAGE_DIR` persistent and access-controlled. Protect database and artifact backups as user data.
- Review upload limits, authentication, logging, retention, rate limiting, and operational monitoring for your deployment. The app has one configured login, not a user-management system.
- Keep a single application worker unless job ownership/state is moved to a shared queue/store: message jobs are held in process memory and may be lost on restart. Multi-worker behavior has not been verified.
- Configure a durable database and verify PostgreSQL behavior for the intended deployment; SQLite is the checked-in default.
- Install LibreOffice only if conversion/visual checks are needed, and configure `LIBREOFFICE_PATH` when it is not discoverable.

Example command for an operator-managed single process (not a packaged or tested deployment profile):

```powershell
python -m uvicorn docforge.api.app:app --host 127.0.0.1 --port 8000
```

Do not use `--reload` in production. Bind to a private interface behind TLS termination. The repository does not currently define health-check orchestration beyond the public `GET /health` application route.

## Health and diagnostics

`GET /health` reports database status, configured provider names, vector/embedding backends, default template availability, LibreOffice discovery, and whether authentication is enabled. It does not validate that every external credential can make a successful live request. `docforge health` prints a related local configuration summary.

See [CONFIGURATION.md](../CONFIGURATION.md), [SECURITY.md](../SECURITY.md), and [TROUBLESHOOTING.md](../TROUBLESHOOTING.md) before operating a shared instance.
