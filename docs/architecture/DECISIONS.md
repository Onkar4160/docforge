# Architecture Decision Records

Format: context → decision → alternatives → consequences. Status: Proposed / Accepted / Superseded.

---

## ADR-001 — Python 3.12 + FastAPI monorepo

**Status:** Accepted (Stage 2)

**Context.** The three office formats have mature Python libraries (`python-pptx`, `python-docx`, `openpyxl`); every LLM, search and vector-store backend we target has a plain REST API reachable with `httpx`; evaluation tooling is Python-heavy.

**Decision.** Single Python 3.12 package `docforge` (src layout) with FastAPI for HTTP, a static web UI served by the same app, and an argparse CLI.

**Alternatives.** TypeScript (weaker OOXML libraries; PptxGenJS cannot edit existing templates); separate frontend framework (adds build tooling without v1 benefit).

**Consequences.** One runtime, one test runner. A richer frontend can replace the static UI later without changing the API.

---

## ADR-002 — Code-orchestrated workflow with specialised agents

**Status:** Accepted

**Context.** The spec demands reproducibility, testability, bounded edits and honest reporting. A single autonomous agent loop is hard to test, hard to bound and hard to resume.

**Decision.** A deterministic `TaskOrchestrator` runs a staged state machine. LLM "agents" are narrow roles (interpret, research-plan, extract, plan, write, edit, review) with typed inputs/outputs via structured outputs. Research is also code-driven: the orchestrator calls the search provider (ADR-005) and asks agents to plan queries and extract evidence, all under a budget.

**Alternatives.** Fully autonomous agent with file tools (flexible but non-deterministic, hard to evaluate); a vendor-hosted agent platform (adds platform coupling and remote file handling, conflicts with ADR-016).

**Consequences.** Each stage is unit-testable with fake LLM responses; checkpoints make jobs resumable; adding agent autonomy later is localised to a stage.

---

## ADR-003 — Intermediate representation as the source of truth; edits as IR patches

**Status:** Accepted

**Context.** Targeted edits must preserve unrelated content and formatting. Editing rendered OOXML directly via an LLM is brittle; regenerating everything violates minimal-change requirements.

**Decision.** Every artifact version stores a typed IR (`DeckPlan`, `DocumentPlan`, `WorkbookPlan`) with stable unit IDs, plus a `StyleSpec`. Renderers are deterministic functions of (IR, template package, design tokens, config). Edits are `IRPatch` objects (JSON-Pointer ops) confined to resolved unit IDs; a scope guard rejects out-of-scope ops; a regression diff verifies unchanged units.

**Alternatives.** Direct OOXML editing (kept only for externally created files without IR — FR-EDIT-5); full regeneration with "keep the rest" instructions (unreliable).

**Consequences.** Renderer determinism must be maintained (no random IDs, stable ordering). File-level manual edits made by users outside DocForge are not reflected in IR unless the file is re-imported.

---

## ADR-004 — Provider-neutral LLM gateway over REST adapters

**Status:** Accepted (supersedes the earlier single-vendor SDK decision, 2026-10-17)

**Context.** The platform must be independent: no dependency on one model vendor or its SDK, and switchable between hosted and self-hosted models by configuration.

**Decision.** Agents call only `LLMClient`. The default implementation, `LLMGateway`, sits over small **REST adapters** written with `httpx`:

- `gemini` — Google Gemini `generateContent` / `batchEmbedContents` (`x-goog-api-key` header).
- `openai_compat` — any OpenAI-compatible `/chat/completions` + `/embeddings` server (Ollama, vLLM, LM Studio, llama.cpp server, OpenRouter, OpenAI).
- `fake` — scripted, for tests.

Model specs are `model` (uses `LLM_PROVIDER`) or `provider:model` (e.g. `openai_compat:llama3.1`), so primary, fallback and per-agent models can live on different backends. Structured output is **provider-agnostic**: the JSON Schema of the target Pydantic model is put in the system prompt, JSON mode is requested, the reply is parsed tolerantly and validated with Pydantic; on failure one repair turn quotes the validation errors. A provider's native schema constraint (`LLM_NATIVE_SCHEMA=true`) is an optional extra; if the provider rejects it, the gateway disables it for the process and continues. Transient errors (429/5xx/timeouts) are retried with exponential backoff up to `LLM_MAX_RETRIES`; when the primary model still cannot produce valid output, the gateway retries once on `LLM_FALLBACK_MODEL`. Every call is hashed for **record/replay cassettes**.

**Alternatives.** Vendor SDKs (lock-in, different idioms per vendor); multi-provider frameworks such as LiteLLM/LangChain (large dependency surface, opaque retry and schema behaviour).

**Consequences.** Adding a backend = one adapter implementing `ChatProvider.generate` (and optionally `EmbeddingProvider.embed`). Prompt-level schema enforcement works with weaker local models but costs some tokens; validation + repair keeps outputs typed regardless of backend.

---

## ADR-005 — Research through a `SearchProvider`; Tavily by default

**Status:** Accepted (supersedes the earlier vendor-tool research decision, 2026-10-17)

**Context.** Research must not depend on the LLM vendor. Search, page retrieval and evidence extraction need to be separately testable and budgeted.

**Decision.** `SearchProvider` interface with:

- `TavilySearchProvider` (default; `TAVILY_API_KEY`, bearer auth, `search_depth=advanced`, raw page text requested so most sources need no separate fetch).
- `DuckDuckGoHtmlProvider` — keyless **development-only** fallback, used only when `REQUIRE_AUTHENTICATED_WEB_SEARCH=false` and no Tavily key exists.
- `UnavailableSearchProvider` — selected when authenticated search is required but not configured; research then fails with a clear reason and the artifact reports the limitation.
- `FixtureSearchProvider` — offline tests.

Pages not returned with content are fetched by `research.fetch` (http/https only, size-capped, HTML reduced to text). Evidence extraction is a separate structured LLM call per source so evidence stays atomic and traceable.

**Consequences.** Search cost is Tavily credits, budgeted per task (`RESEARCH_MAX_SEARCHES`). Other providers (Brave, SerpAPI, SearXNG) can be added as adapters.

---

## ADR-006 — Evidence model: Source → EvidenceItem → Claim

**Status:** Accepted

**Context.** Traceability from statements in the artifact back to sources, and honest labelling of assumptions.

**Decision.** Three levels: `Source` (provenance, authority, dates), `EvidenceItem` (atomic fact/figure/quote with locator), `Claim` (statement used in the IR, with `evidence_ids` and `status` ∈ supported / partially_supported / unsupported / assumption / interpretation / estimate). IR blocks reference claim IDs; renderers produce citations from them.

**Consequences.** Citation coverage and unsupported-claim checks become simple queries. Writers must emit claim references; plan validation enforces it.

---

## ADR-007 — Template handling: analyse into manifest, render on top of the template package

**Status:** Accepted

**Context.** Templates carry masters, layouts, themes, styles and branding that text extraction loses. Output length differs from template length.

**Decision.** `TemplateAnalyzer` produces a `TemplateManifest` (geometry, styles, element inventory with role classification, layout archetypes) and `DesignTokens`. PPTX output starts from the template package, deletes sample slides, and composes new slides on template layouts; branding elements are re-applied. DOCX output starts from the template with body cleared. XLSX templates are mapped to sheet roles.

**Alternatives.** Clone-and-edit sample slides (simple but forces sample compositions and leaves residue); re-creating designs from scratch using extracted tokens (loses masters and fidelity).

**Consequences.** Layout scoring and element role classification quality drive fidelity; covered by template fixtures. Unsupported exotic elements (SmartArt, OLE) are preserved on layouts but not re-authored.

---

## ADR-008 — Persistence: SQLAlchemy 2 + SQLite default, filesystem blob store

**Status:** Accepted

**Decision.** SQLAlchemy 2 with a single document-style `records` table: primary key `(kind, id)`, indexed `parent_id`, and a JSON `data` column holding the validated Pydantic document. Typed `Repository[Model]` classes provide CRUD per kind. SQLite file DB by default, Postgres via URL. Content-addressed filesystem blob store with an interface compatible with S3.

**Alternatives.** One ORM table per entity (more migrations as contracts evolve during Stages 4–11, little query benefit at v1 scale).

**Consequences.** Zero-setup local runs; additive model changes need no DB migration; cross-entity queries go through repositories rather than SQL joins. If query needs grow (e.g. analytics over evidence), dedicated tables can be added beside `records`. Alembic is introduced at Stage 13 before first deployment.

---

## ADR-009 — Validation: always-on structural/geometric checks; optional visual rendering

**Status:** Accepted

**Context.** LibreOffice gives the best rendering check but is not always installed (it is not on the current dev machine).

**Decision.** Checks are tiered: (1) structural re-open and schema checks; (2) geometric/text-metric checks from IR + measured text; (3) formula recomputation; (4) visual rendering via LibreOffice when available; (5) LLM content review. Every check returns `skipped` with a reason when its dependency is missing; the quality report shows it.

**Consequences.** Quality reports are honest across environments; the Docker image includes LibreOffice so CI can run tier 4.

---

## ADR-010 — Text measurement with font metrics

**Decision.** `TextMeasurer` uses Pillow `ImageFont.truetype` with a font resolver (template-embedded fonts → system fonts → bundled metric-compatible fallbacks such as Liberation/Carlito) to wrap and measure text in EMU; falls back to an average-advance heuristic with a safety margin when no font file is found.

**Consequences.** Overflow detection works without a renderer; accuracy is reported as "estimated" when the heuristic path is used.

---

## ADR-011 — Formula verification with an independent evaluator

**Decision.** Workbooks are verified by (a) static checks (references resolve, no error literals, no unintended circularity) and (b) computing the workbook with the `formulas` library (or LibreOffice headless recalculation when present) and comparing selected cells to plan-declared expected values computed in Python.

**Consequences.** Formulas must be within the supported function set; the planner is constrained to a documented function whitelist.

---

## ADR-012 — Background execution: in-process async job runner with persistent job records

**Decision.** Jobs run in an asyncio task pool inside the API process; state, checkpoints and progress events are persisted; SSE streams events. Interface allows swapping to a queue (Arq/Celery) later.

**Consequences.** Single-node deployment in v1; restart resumes jobs from checkpoints.

---

## ADR-013 — Clarification thresholds

**Decision.** Ask when interpretation confidence < 0.6, target resolution is ambiguous, scope blast radius > 50 % for a narrow request, or required inputs are missing (ARCHITECTURE §5.3). Thresholds are configurable and covered by evaluation cases (AC-9).

---

## ADR-014 — Retrieval over user sources: embeddings + pluggable vector store

**Status:** Accepted (2026-10-17)

**Context.** Uploaded sources (reports, datasets, previous decks) can be far larger than a prompt. Agents need the relevant passages, with locators for citation.

**Decision.** `KnowledgeIndex` chunks text (paragraph-aware, ~1500 chars, 200 overlap), embeds chunks with an `EmbeddingProvider` (Gemini `gemini-embedding-001` by default, OpenAI-compatible, or offline feature-hashing) and stores them in a `VectorStore`: **Pinecone** over REST (index host discovered via the control plane; `PINECONE_INDEX`) or a **local** store kept in the app database with exact cosine search. `VECTOR_STORE=auto` picks Pinecone when `PINECONE_API_KEY` is set. Each chat session is a namespace; filters support `$eq`/`$in` on both backends. Embeddings are L2-normalised so truncated dimensions behave with cosine and dot product.

**Consequences.** `EMBEDDING_DIMENSIONS` must equal the Pinecone index dimension. Without any keys, retrieval still works (lower quality hashing embeddings + local store), keeping tests and offline use functional.

---

## ADR-015 — JWT authentication, single configured user in v1

**Status:** Accepted (2026-10-17); resolves PRD Q3 for v1

**Decision.** `POST /api/auth/login` checks `DEMO_USERNAME`/`DEMO_PASSWORD` (constant-time compare) and issues an HS256 JWT (`JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRE_MINUTES`) via PyJWT. All `/api/*` routes except login require `Authorization: Bearer`. Sessions record their `owner`; another user's session is reported as not found. With `APP_ENV=prod` the app refuses to start while `JWT_SECRET` is the placeholder. `AUTH_ENABLED=false` exists for local scripting.

**Consequences.** Multi-user accounts need a user store and password hashing later; the token/ownership model already supports it.

---

## ADR-016 — Vendor neutrality and configuration contract

**Status:** Accepted (2026-10-17)

**Decision.** No component may import a vendor SDK for LLM, search or vector storage; all external services are reached through project-owned adapters over HTTP and selected by configuration. Environment variable names follow the project `.env` exactly (no prefix): `GEMINI_API_KEY`, `PINECONE_*`, `TAVILY_API_KEY`, `REQUIRE_AUTHENTICATED_WEB_SEARCH`, `JWT_*`, `DEMO_*`, `DATABASE_URL`, `UPLOAD_MAX_MB`, `LLM_PRIMARY_MODEL`, `LLM_FALLBACK_MODEL`, `LLM_MAX_RETRIES`, `DEFAULT_*_TEMPLATE_PATH`, `PPTX_MASTERS_ENABLED`. Placeholder values (`your-…`) count as unset. Missing keys degrade features with explicit reporting instead of failing startup.

**Consequences.** Every external integration has a fake/fixture twin for offline tests. The optional `pptx-masters` design-guide extractor is treated the same way: command and arguments are configurable (`PPTX_MASTERS_COMMAND`, `PPTX_MASTERS_ARGS`) because no fixed CLI contract is assumed, and the built-in analyzer never depends on it.

---

## ADR-017 — Scholarly sources next to web search

**Status:** Accepted (2026-10-17)

**Context.** The user asked for research that finds research papers and research work, not only web pages.

**Decision.** Three scholarly `SearchProvider`s run alongside web search: **OpenAlex** (broad index of journals and repositories; API key optional — the free keyless allowance is small), **Semantic Scholar** (abstracts and TLDRs; key optional, keyless use is rate-limited), **arXiv** (preprints; keyless). The research planner tags each question with channels (`web`, `academic`, `news`); academic questions query the scholarly providers. Results are deduplicated by DOI/URL/title across indexes, ranked by provider relevance + authority (peer-reviewed > official/academic domains > general web > blogs) + citation count + recency, with at most 3 web sources per domain. Abstracts are the evidence text for papers. Provider failures are recorded in `dossier.notes` and surfaced in the reply; research continues with the remaining providers.

**Consequences.** Papers are cited with authors, venue, year and DOI. Full-text reading of open-access PDFs is a later extension (`ingest.readers` already extracts PDF text).

---

## ADR-018 — Photographs from openly licensed and stock sources

**Status:** Accepted (2026-10-17)

**Context.** Modern AI deck tools use imagery heavily; text-only decks look dated.

**Decision.** Planners may request `image` blocks with a concrete, photographable description. An `ImageProvider` resolves them: **Openverse** (openly licensed images, keyless) by default, **Pexels** when `PEXELS_API_KEY` is set. Candidates are ranked by title relevance and size, downloaded with a contact-bearing User-Agent (Wikimedia policy), normalised with Pillow (metadata stripped, max 2400 px) and stored in the blob store. Renderers crop to fill without distortion and always print the credit line (CC BY attribution). Images never contain generated text, charts or identifiable people requests. Missing images degrade to text layouts.

**Consequences.** Image use is capped per deliverable (`MAX_IMAGES_PER_DECK`). Generative image models can be added as another `ImageProvider`.

---

## ADR-019 — Clone mode for templates whose design lives on the sample slides

**Status:** Accepted (2026-10-17)

**Context.** Canva exports and marketplace templates (e.g. the user's "Green Cream Simple Aesthetic Watercolor" and "Company_Template") keep backgrounds, artwork, panels and photo frames on the sample slides; their layouts are blank and their themes are Office defaults. Layout-based rendering (ADR-007) discarded the design.

**Decision.** The analyzer turns every usable sample slide into a *base* (title box, optional subtitle box, sample text and in-area structure to remove, photo placeholders and light photo frames, content region extended to the space the design leaves, colour behind the region from fills and image pixels). Templates are in `slides` mode when the sample slides carry more artwork than their layouts. Rendering clones a base per slide (shapes deep-copied with relationships re-linked, sample slides removed at the end); headlines go into the template's title box keeping its font/colour/alignment and grow instead of overflowing; content is laid out inside the region; bases rotate for variety, wide archetypes (charts, tables, timelines, KPIs) get wide regions, dark regions are avoided for dark text. Tokens come from the slides (fonts of title/body text, accents from fills and artwork, darkened to ≥3.2:1 against every light panel). Promotional and image-only sample slides are never bases. The contrast check now sees colours behind text (pictures, groups, inherited backgrounds).

**Consequences.** Output keeps the template's look (verified on three real templates: Green Cream, Company_Template, presentation_Template). Accent lines on *layouts* can still cross long titles. Manifest cache is versioned so older analyses are recomputed.

---

## ADR-020 — Quota-aware model chain and replies for every message

**Status:** Accepted (2026-10-17)

**Context.** Live use showed: `gemini-2.0-flash` retired (404), `gemini-2.5-flash` free tier exhausted (20 requests/day/model), and an exception outside the guarded path left messages without any reply.

**Decision.** `LLM_FALLBACK_MODEL` is a comma-separated chain. 404 marks a model unavailable for 24 h; a daily or long 429 (parsed from `QuotaFailure`/`RetryInfo`) marks it unavailable until its retry time; short 429s wait the advised delay. When the whole chain is exhausted one clear error is raised. The orchestrator wraps interpretation and generation: every message stores an assistant reply; failures are described in plain language with next steps (`friendly_error`). Questions are answered (AnswerAgent); change requests regenerate with the change; a fixed-length deck whose text does not fit gets one planner "shorten" round. Messages run as background jobs (`POST /api/sessions/{id}/jobs`, `GET …/jobs/{job}`) with progress steps; rendering runs in a worker thread so polling stays responsive.

**Consequences.** Free-tier keys still limit daily volume, but users always get a reply that says why. Jobs are in-process (lost on restart; the persisted reply is unaffected).
