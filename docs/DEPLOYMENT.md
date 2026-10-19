# DocForge — Deployment and Operations

## 1. Requirements

| Component | Version | Required |
|---|---|---|
| Python | 3.12+ | yes |
| LLM backend | Gemini API key **or** any OpenAI-compatible server (Ollama, vLLM, LM Studio, OpenRouter, OpenAI) | for live generation (not for tests) |
| Tavily API key | — | for web research (a keyless development fallback exists) |
| Pinecone index | dimension = `EMBEDDING_DIMENSIONS` | optional; local vector store otherwise |
| LibreOffice | 7.6+ (`soffice` on PATH or `LIBREOFFICE_PATH`) | optional: PDF export, visual checks, recalculation |
| Disk | ~1 GB + artifacts | yes |

No vendor SDK is installed; all services are called over HTTP by project adapters (ADR-016). Local libraries: python-pptx, python-docx, openpyxl, matplotlib (document charts), formulas (workbook recalculation), pypdf (PDF sources), Pillow, lxml.

## 2. Local setup

```bash
cd docforge
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # fill in GEMINI_API_KEY, TAVILY_API_KEY, optionally PINECONE_API_KEY
pytest                       # offline test suite, needs no keys
docforge serve               # http://127.0.0.1:8000, sign in with DEMO_USERNAME / DEMO_PASSWORD
```

Fully local LLM (no cloud keys), e.g. with Ollama:

```env
LLM_PROVIDER=openai_compat
OPENAI_COMPAT_BASE_URL=http://localhost:11434/v1
LLM_PRIMARY_MODEL=qwen2.5:14b
LLM_FALLBACK_MODEL=llama3.1:8b
EMBEDDING_PROVIDER=openai_compat
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_DIMENSIONS=768
VECTOR_STORE=local
```

Mixing backends is allowed: `LLM_FALLBACK_MODEL=openai_compat:llama3.1` keeps Gemini as primary and a local model as fallback.

CLI:

```bash
docforge health          # configuration, keys detected, optional dependencies
docforge serve --port 8000
```

## 3. Configuration

Variables are read from the environment or `.env` with **exactly these names** (no prefix). Placeholder values starting with `your-` are treated as unset. Defaults live in `src/docforge/core/config.py`.

### Keys and services

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | — | Gemini chat and embeddings |
| `PINECONE_API_KEY` | — | Enables Pinecone when `VECTOR_STORE=auto` |
| `PINECONE_INDEX` | `doc-chatbot` | Existing index name |
| `PINECONE_CLOUD` / `PINECONE_REGION` | `aws` / `us-east-1` | Recorded for index provisioning |
| `PINECONE_API_VERSION` | `2026-07` | `X-Pinecone-Api-Version` header |
| `TAVILY_API_KEY` | — | Web search |
| `REQUIRE_AUTHENTICATED_WEB_SEARCH` | `true` | `false` allows the keyless DuckDuckGo fallback (development only) |

### Auth

| Variable | Default | Meaning |
|---|---|---|
| `JWT_SECRET` | placeholder | **Change it.** `APP_ENV=prod` refuses to start with the placeholder |
| `JWT_ALGORITHM` | `HS256` | |
| `JWT_EXPIRE_MINUTES` | `480` | Token lifetime |
| `DEMO_USERNAME` / `DEMO_PASSWORD` | `demo` / `demo123` | The v1 login (ADR-015) |
| `AUTH_ENABLED` | `true` | `false` only for local scripting |

### Storage and limits

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./storage/app.db` | SQLAlchemy URL (Postgres supported) |
| `STORAGE_DIR` | `./storage` | Blobs, cassettes |
| `UPLOAD_MAX_MB` | `25` | Per-file upload limit |

### LLM

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | Default backend for bare model names: `gemini` / `openai_compat` / `fake` |
| `LLM_PRIMARY_MODEL` | `gemini-3.8-flash` | `model` or `provider:model` |
| `LLM_FALLBACK_MODEL` | `gemini-3.7-flash,gemini-3.5-flash,gemini-3.1-flash-lite` | Comma-separated chain, tried in order when a model fails, is retired (404) or out of quota (429); empty disables |
| `LLM_MAX_RETRIES` | `3` | Retries on 429/5xx/timeouts (exponential backoff) |
| `LLM_TEMPERATURE` | `0.3` | |
| `LLM_MAX_OUTPUT_TOKENS` | `8192` | |
| `LLM_TIMEOUT_S` | `180` | Per request |
| `LLM_NATIVE_SCHEMA` | `false` | Also send the provider's native JSON-schema constraint |
| `LLM_REPAIR_ATTEMPTS` | `1` | Re-asks after invalid structured output |
| `OPENAI_COMPAT_BASE_URL` | `http://localhost:11434/v1` | Any OpenAI-compatible server |
| `OPENAI_COMPAT_API_KEY` | — | Bearer key if the server needs one |
| `LLM_CASSETTE_MODE` | `off` | `off` / `record` / `replay` |

### Embeddings and retrieval

| Variable | Default | Meaning |
|---|---|---|
| `EMBEDDING_PROVIDER` | `gemini` | `gemini` / `openai_compat` / `hash` (offline); falls back to `hash` when Gemini has no key |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | |
| `EMBEDDING_DIMENSIONS` | `768` | Must equal the Pinecone index dimension |
| `VECTOR_STORE` | `auto` | `auto` (Pinecone if key set) / `pinecone` / `local` |

### Research, templates, pipeline

| Variable | Default | Meaning |
|---|---|---|
| `RESEARCH_ENABLED` | `true` | |
| `ACADEMIC_SOURCES` | `openalex,semantic_scholar,arxiv` | Scholarly indexes to query |
| `OPENALEX_API_KEY` | — | Optional free key (raises the small keyless allowance) |
| `SEMANTIC_SCHOLAR_API_KEY` | — | Optional free key (keyless use is often rate-limited) |
| `RESEARCH_CONTACT_EMAIL` | — | Sent as OpenAlex `mailto` and in the image downloader's User-Agent |
| `IMAGES_ENABLED` | `true` | Photos on cover and image+text slides |
| `IMAGE_PROVIDER` | `auto` | `auto` (Pexels if key, else Openverse) / `openverse` / `pexels` / `none` |
| `PEXELS_API_KEY` | — | Optional stock-photo provider |
| `MAX_IMAGES_PER_DECK` | `6` | Cap per deliverable |
| `RESEARCH_MAX_SEARCHES` | `8` | Per-task search budget |
| `RESEARCH_MAX_RESULTS` | `6` | Results per query |
| `RESEARCH_ALLOWED_DOMAINS` / `RESEARCH_BLOCKED_DOMAINS` | — | Comma lists |
| `DEFAULT_DOCX_TEMPLATE_PATH` | `data/sample_templates/Company_Proposal.docx` | Used when the user supplies no DOCX template; ignored if missing |
| `DEFAULT_PPTX_TEMPLATE_PATH` | `data/sample_templates/Green Cream Simple Aesthetic Watercolor Presentation.pptx` | Same for PPTX |
| `DEFAULT_XLSX_TEMPLATE_PATH` | — | Same for XLSX |
| `PPTX_MASTERS_ENABLED` | `0` | Run an installed `pptx-masters` CLI during template analysis |
| `PPTX_MASTERS_COMMAND` | `pptx-masters` | Executable |
| `PPTX_MASTERS_ARGS` | `{input} --output {output_dir}` | Argument template; adjust to the installed tool |
| `CLARIFY_THRESHOLD` | `0.6` | Interpretation confidence threshold |
| `MAX_REPAIR_ITERATIONS` | `3` | Validation/repair loop limit |
| `LIBREOFFICE_PATH` | auto-detect | Path to `soffice` |
| `APP_ENV` | `dev` | `dev` / `test` / `prod` |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / `false` | |

## 4. Production deployment (target for Stage 13)

- Container image: `python:3.12-slim` + LibreOffice + fonts (Liberation, Carlito, Caladea, DejaVu, Noto).
- Run: `uvicorn docforge.api.app:app --host 0.0.0.0 --port 8000 --workers 1` (single worker: in-process job runner, ADR-012).
- Put behind a reverse proxy providing TLS.
- Set `APP_ENV=prod` and a random `JWT_SECRET` (e.g. `python -c "import secrets; print(secrets.token_urlsafe(48))"`); change `DEMO_PASSWORD`.
- Volumes: `STORAGE_DIR` on persistent storage; Postgres via `DATABASE_URL` for multi-instance future.
- Secrets: inject API keys via a secret store; never bake into the image.

## 5. Operations

- **Health:** `GET /health` → database, LLM provider/models and whether a key is configured, web search provider (authenticated or not), vector store, embeddings backend, default template availability, LibreOffice.
- **Logs:** structured, include `job_id`, `task_id`, `stage`, timings; user content only at DEBUG.
- **Usage:** LLM call records hold tokens, attempts and fallback use per agent/job.
- **Backups:** DB + storage directory (+ Pinecone index if used).

## 6. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `GEMINI_API_KEY is not set` | Add the key, or switch `LLM_PROVIDER=openai_compat` with a local server. |
| `gemini: request failed (404)` | Model retired or not available to your key; the gateway skips it, but set `LLM_PRIMARY_MODEL` to a current model. List models: `GET https://generativelanguage.googleapis.com/v1beta/models?key=…`. |
| Reply says “usage limit is reached” | Gemini free tier allows ~20 requests per model per day; every model in the chain is used up. Wait for the reset or enable billing on the key. A deck uses ~6–8 requests. |
| A message got no reply (older versions) | Fixed: every message now gets a reply; unexpected errors are logged with a traceback and reported in plain language. |
| `web research requires TAVILY_API_KEY` | Add the key, or set `REQUIRE_AUTHENTICATED_WEB_SEARCH=false` for development. |
| `pinecone index '…' not found` | Create the index (dimension = `EMBEDDING_DIMENSIONS`) or fix `PINECONE_INDEX`. |
| Visual checks "skipped" in reports | LibreOffice not found; install or set `LIBREOFFICE_PATH`. |
| Replay test fails "missing cassette" | Prompt or schema changed; re-record with `LLM_CASSETTE_MODE=record` (uses quota). |
| 401 from every `/api` call | Log in via `/api/auth/login` and send `Authorization: Bearer <token>`. |
| `database is locked` (SQLite) | Concurrent writers; use a single worker or Postgres. |
| `No space left on device` / random `OSError` | The system drive is full; free space or point `TMP`/`TEMP` and `MPLCONFIGDIR` to another drive. |
| Reply mentions "rate limit" for semantic_scholar/openalex | Add `SEMANTIC_SCHOLAR_API_KEY` / `OPENALEX_API_KEY`. |
