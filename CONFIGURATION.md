# Configuration

Settings are defined by `src/docforge/core/config.py`. Values are loaded from process environment variables or `.env` in the current working directory. Names are case-insensitive, use no project prefix, and unknown keys are ignored. Blank values and placeholder API keys beginning with `your-` are treated as unset. Relative paths are resolved relative to the process working directory.

No environment variable is required merely to install or start the local app. Provider credentials are required only for the corresponding live feature. Defaults below come from the `Settings` class; optional key/path values are unset unless noted.

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_ENV` | No | `dev` | Runtime mode: `dev`, `test`, or `prod`. |
| `STORAGE_DIR` | No | `./storage` | Root for blobs and default cassette storage. |
| `DATABASE_URL` | No | `sqlite:///./storage/app.db` | SQLAlchemy database URL. SQLite is the local default; PostgreSQL support is described in the architecture docs. |
| `UPLOAD_MAX_MB` | No | `25` | Maximum uploaded file size in MiB. |
| `AUTH_ENABLED` | No | `true` | Enables bearer authentication. Disabling it removes the API auth requirement; use only for isolated local work. |
| `JWT_SECRET` | Required for secure/shared or production use | `change-me-to-a-random-secret` | Signing key for JWTs. With auth enabled and `APP_ENV=prod`, startup rejects the default placeholder. |
| `JWT_ALGORITHM` | No | `HS256` | JWT signing algorithm. |
| `JWT_EXPIRE_MINUTES` | No | `480` | Token lifetime. |
| `DEMO_USERNAME` | No | `demo` | The single configured login username. |
| `DEMO_PASSWORD` | No | `demo123` | The single configured login password. Replace the development default before sharing the service. |
| `GEMINI_API_KEY` | For Gemini live calls | Unset | Credential used by the Gemini adapter. |
| `LLM_PROVIDER` | No | `gemini` | Default provider for unqualified model names: `gemini`, `openai_compat`, or `fake`. |
| `LLM_PRIMARY_MODEL` | No | `gemini-3.8-flash` | Primary model name or `provider:model` spec. Provider model availability can change. |
| `LLM_FALLBACK_MODEL` | No | `gemini-3.7-flash,gemini-3.5-flash,gemini-3.1-flash-lite` | Comma-separated fallback model chain; blank disables fallback. |
| `LLM_AGENT_MODEL` | No | Empty mapping | Per-agent model mapping supported by settings; configure as a mapping in the format accepted by Pydantic settings. |
| `LLM_MAX_RETRIES` | No | `3` | Retry count for transient LLM failures. |
| `LLM_TEMPERATURE` | No | `0.3` | LLM sampling temperature. |
| `LLM_MAX_OUTPUT_TOKENS` | No | `8192` | Maximum output token setting passed to the provider. |
| `LLM_TIMEOUT_S` | No | `180` | LLM request timeout in seconds. |
| `LLM_NATIVE_SCHEMA` | No | `false` | Enables the provider's native JSON-schema constraint where implemented; prompt/schema validation remains in place. |
| `LLM_REPAIR_ATTEMPTS` | No | `1` | Structured-output repair attempts. |
| `LLM_CASSETTE_MODE` | No | `off` | LLM cassette mode: `off`, `record`, or `replay`. Recording can persist request/response content. |
| `LLM_CASSETTE_DIR` | No | Unset | Overrides the cassette directory; otherwise under `STORAGE_DIR`. |
| `OPENAI_COMPAT_BASE_URL` | For OpenAI-compatible provider | `http://localhost:11434/v1` | Base URL for an OpenAI-compatible API server. |
| `OPENAI_COMPAT_API_KEY` | Only if server requires it | Unset | Bearer credential for that server. |
| `TAVILY_API_KEY` | For authenticated web search | Unset | Tavily search credential. |
| `REQUIRE_AUTHENTICATED_WEB_SEARCH` | No | `true` | When false, allows the keyless development search fallback if Tavily is unset. |
| `OPENALEX_API_KEY` | No | Unset | Optional OpenAlex credential. |
| `SEMANTIC_SCHOLAR_API_KEY` | No | Unset | Optional Semantic Scholar credential; keyless use may be rate-limited. |
| `RESEARCH_CONTACT_EMAIL` | No | Unset | Contact address used by supported research/image provider requests. |
| `ACADEMIC_SOURCES` | No | `openalex,semantic_scholar,arxiv` | Comma-separated academic source names. |
| `RESEARCH_ENABLED` | No | `true` | Enables research pipeline behavior. |
| `RESEARCH_MAX_SEARCHES` | No | `8` | Search budget per task. |
| `RESEARCH_MAX_RESULTS` | No | `6` | Maximum results per query. |
| `RESEARCH_ALLOWED_DOMAINS` | No | Empty list | Optional comma-separated domain allowlist. |
| `RESEARCH_BLOCKED_DOMAINS` | No | Empty list | Optional comma-separated domain blocklist. |
| `PINECONE_API_KEY` | When explicitly selecting Pinecone | Unset | Pinecone credential. With `VECTOR_STORE=auto`, its presence selects Pinecone. |
| `PINECONE_INDEX` | No | `doc-chatbot` | Pinecone index name. The index dimension must match `EMBEDDING_DIMENSIONS`. |
| `PINECONE_CLOUD` | No | `aws` | Cloud metadata used by Pinecone integration. |
| `PINECONE_REGION` | No | `us-east-1` | Region metadata used by Pinecone integration. |
| `PINECONE_API_VERSION` | No | `2026-07` | Pinecone API version header value. |
| `EMBEDDING_PROVIDER` | No | `gemini` | Embedding backend: `gemini`, `openai_compat`, or `hash`. |
| `EMBEDDING_MODEL` | No | `gemini-embedding-001` | Embedding model name. |
| `EMBEDDING_DIMENSIONS` | No | `768` | Embedding vector size; must match the configured Pinecone index if used. |
| `VECTOR_STORE` | No | `auto` | `auto`, `pinecone`, or `local`. `auto` selects Pinecone when its key is set, otherwise local. |
| `IMAGES_ENABLED` | No | `true` | Enables image retrieval features. |
| `IMAGE_PROVIDER` | No | `auto` | `auto`, `openverse`, `pexels`, or `none`. |
| `PEXELS_API_KEY` | For Pexels | Unset | Pexels image provider credential. |
| `MAX_IMAGES_PER_DECK` | No | `6` | Image limit per deck. |
| `DEFAULT_DOCX_TEMPLATE_PATH` | No | `data/sample_templates/Company_Proposal.docx` | Default DOCX template path; ignored if unset or missing. |
| `DEFAULT_PPTX_TEMPLATE_PATH` | No | `data/sample_templates/Green Cream Simple Aesthetic Watercolor Presentation.pptx` | Default PPTX template path; ignored if unset or missing. |
| `DEFAULT_XLSX_TEMPLATE_PATH` | No | Unset | Default XLSX template path. |
| `PPTX_MASTERS_ENABLED` | No | `false` | Enables the optional external `pptx-masters` analysis hook. |
| `PPTX_MASTERS_COMMAND` | No | `pptx-masters` | Executable name/path for the optional hook. |
| `PPTX_MASTERS_ARGS` | No | `{input} --output {output_dir}` | Argument template; placeholders are substituted by the hook. |
| `PPTX_MASTERS_TIMEOUT_S` | No | `120` | Timeout for the optional hook. |
| `CLARIFY_THRESHOLD` | No | `0.6` | Interpretation confidence threshold for clarification behavior. |
| `MAX_REPAIR_ITERATIONS` | No | `3` | Maximum render/validation repair iterations. |
| `LIBREOFFICE_PATH` | No | Auto-detected | Explicit path to LibreOffice `soffice`; if unset, the app searches PATH and known platform locations. |
| `LOG_LEVEL` | No | `INFO` | Logging level. |
| `LOG_JSON` | No | `false` | Enables JSON-formatted logs. |

## Minimal local setup

The `.env.example` file contains a sample. Copy it only when `.env` does not already exist, then edit the needed values:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

To use Gemini, set `GEMINI_API_KEY`. To use an OpenAI-compatible service, set `LLM_PROVIDER=openai_compat`, `OPENAI_COMPAT_BASE_URL`, and an appropriate `LLM_PRIMARY_MODEL`; set `OPENAI_COMPAT_API_KEY` only if that server requires it. `docforge health` reports configured provider choices but does not make a credential-validation request.

## Production security settings

When `APP_ENV=prod` and authentication is enabled, `JWT_SECRET` cannot remain the built-in placeholder. Generate a secret locally, for example:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Store it and all provider keys in a secret manager or protected environment, change the demo credentials, and do not commit `.env`. See [SECURITY.md](SECURITY.md) and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).