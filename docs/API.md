# API Reference

The API is implemented by FastAPI routers under `src/docforge/api/routes/`. While the server is running, interactive OpenAPI documentation is available at `/docs`. The application does not define an `/api` root endpoint.

Base URL for local development: `http://127.0.0.1:8000`.

## Authentication

`GET /health` and `POST /api/auth/login` are public. Other `/api/*` routes require `Authorization: Bearer <token>` when `AUTH_ENABLED=true`. Login uses the configured `DEMO_USERNAME` and `DEMO_PASSWORD` and returns an expiring JWT. See [CONFIGURATION.md](../CONFIGURATION.md).

PowerShell login example:

```powershell
$login = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/auth/login `
  -ContentType 'application/json' `
  -Body (@{ username = 'demo'; password = 'demo123' } | ConvertTo-Json)
$headers = @{ Authorization = "Bearer $($login.access_token)" }
```

Replace the development credentials with configured values when changed. Do not save or share the access token.

## Endpoints

| Method | Path | Auth | Success | Purpose and response |
|---|---|---|---:|---|
| `GET` | `/health` | No | 200 | Component status JSON including database, provider selections, templates, LibreOffice, and auth state. |
| `POST` | `/api/auth/login` | No | 200 | JSON body `{ "username": "...", "password": "..." }`; returns `access_token`, `token_type`, `expires_in`. Invalid credentials return 401. |
| `GET` | `/api/auth/me` | Yes | 200 | Returns `{ "username": "..." }`. |
| `POST` | `/api/sessions` | Yes | 201 | Optional JSON `{ "title": "..." }`; creates a session. Default title is `Untitled session`. |
| `GET` | `/api/sessions` | Yes | 200 | Lists the current user's sessions with title, IDs, timestamps, and message counts. |
| `GET` | `/api/sessions/{session_id}` | Yes | 200 | Returns the session with its messages, files, and tasks. |
| `PATCH` | `/api/sessions/{session_id}` | Yes | 200 | JSON `{ "title": "..." }`; renames session (title length 1–120). |
| `DELETE` | `/api/sessions/{session_id}` | Yes | 204 | Deletes a session; no response body. |
| `POST` | `/api/sessions/{session_id}/files` | Yes | 201 | Multipart `file` and optional `role` (`template`, `source`, `dataset`, `unknown`); returns uploaded-file metadata. |
| `GET` | `/api/sessions/{session_id}/files/{file_id}` | Yes | 200 | Downloads an uploaded file. |
| `POST` | `/api/sessions/{session_id}/messages` | Yes | 200 | Synchronous message processing; JSON `{ "content": "...", "file_ids": [] }`; returns message/reply/task/artifact/report view. |
| `POST` | `/api/sessions/{session_id}/jobs` | Yes | 202 | Starts message processing in-process; same message body; returns `job_id` and the stored message. |
| `GET` | `/api/sessions/{session_id}/jobs/{job_id}` | Yes | 200 | Polls job status, progress steps, and result/error. |
| `GET` | `/api/sessions/{session_id}/artifacts/{artifact_id}/versions/{version}/download` | Yes | 200 | Downloads a versioned artifact. |
| `GET` | `/api/sessions/{session_id}/artifacts/{artifact_id}/versions/{version}/report` | Yes | 200 | Returns the version's quality report. |
| `GET` | `/api/sessions/{session_id}/artifacts/{artifact_id}/versions/{version}/preview/{index}` | Yes | 200 | Downloads a PNG preview when that preview index exists. |

`POST /api/sessions/{session_id}/messages` and `/jobs` require a non-empty `content` of at most 20,000 characters. `file_ids` defaults to an empty list. The upload limit is controlled by `UPLOAD_MAX_MB` (default 25 MiB); a file submitted as a template must be a supported office template type.

For authenticated requests, send `Authorization: Bearer <access_token>`. JSON endpoints use `Content-Type: application/json`; file uploads use `multipart/form-data` with a `file` part and optional `role` form field. Path parameters are the IDs returned by the corresponding create/list responses; `version` and `index` are integers.

## Example: create and list a session

```powershell
$session = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/sessions `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body (@{ title = 'Research notes' } | ConvertTo-Json)

Invoke-RestMethod -Uri http://127.0.0.1:8000/api/sessions `
  -Headers $headers
```

## Example: upload a file

```powershell
curl.exe -X POST "http://127.0.0.1:8000/api/sessions/$($session.id)/files" `
  -H "Authorization: Bearer $($login.access_token)" `
  -F "file=@source.pdf" `
  -F "role=source"
```

## Example: submit a message and poll a job

```powershell
$job = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/sessions/$($session.id)/jobs" `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body (@{ content = 'Create a short project overview'; file_ids = @() } | ConvertTo-Json)

Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/sessions/$($session.id)/jobs/$($job.job_id)" `
  -Headers $headers
```

Job state is stored in process memory; progress may not survive a server restart. The persisted message/result behavior is separate. For a simple request, the synchronous `/messages` route avoids polling.

## Errors and status codes

- `400`: invalid input, unsupported file, invalid file role/type, or unknown file ID.
- `401`: invalid/missing/expired bearer token or invalid login. Protected responses include `WWW-Authenticate: Bearer` for auth failures.
- `404`: missing resource or session/artifact not owned by the authenticated user.
- `413`: uploaded file exceeds `UPLOAD_MAX_MB`.
- `422`: FastAPI/Pydantic request validation failure.
- `502`/`503`: some LLM provider failures, as mapped by the application error types.
- `500`: unexpected internal errors.

Application errors use the JSON shape `{ "error": { "code": "...", "message": "...", "details": {} } }`. Exact codes depend on the error class; for example, invalid auth uses `unauthorized`, missing resources `not_found`, and oversized files `file_too_large`.

## Static routes

The web UI is served at `/`; static assets are mounted under `/static`. These are not API JSON routes.