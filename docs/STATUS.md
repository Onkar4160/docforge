# DocForge — Implementation Status

Recorded implementation snapshot: 2026-10-17

The stage verification evidence below is the historical snapshot recorded on that date; it was not rerun as part of the documentation update on 2026-10-22. The current API code exposes in-process background message jobs with polling; job progress is not durable across process restarts. See [DEPLOYMENT](DEPLOYMENT.md) and [ARCHITECTURE](architecture/ARCHITECTURE.md).

Implementation update (2026-10-22): added cached PPTX design analysis, stable-ID slide insertion/reordering, scoped PPTX style plans with confirmation for warnings, and pinned template references across artifact versions. The current test/lint verification results are recorded in the change handoff; the historical stage table below has not been re-baselined.

Verification for this update: `pytest` 217 passed; `ruff check src tests` passed; Python compilation passed. Tests use fakes/fixtures; no live provider calls or LibreOffice visual rendering were run.

## Stage summary

| Stage | Status | Evidence |
|---|---|---|
| 1 Requirements | verified | [PRD](PRD.md): 11 scenarios, 75 FRs, 12 NFRs, AC-1…AC-10, question register Q1–Q11 |
| 2 Architecture | verified | [ARCHITECTURE](architecture/ARCHITECTURE.md), [DECISIONS](architecture/DECISIONS.md) ADR-001…018, [DATA_MODELS](DATA_MODELS.md), [QUALITY](QUALITY.md), [TESTING](TESTING.md) |
| 3 Foundation | verified | see below |
| 4 Conversation | partial | InterpreterAgent + context builder (M1); target resolution and labelled eval set pending |
| 5 Research | done (offline-verified) | research planner, web + scholarly search (OpenAlex/Semantic Scholar/arXiv live-checked), ranking/dedupe, page fetch, user-file ingestion + retrieval, evidence extraction, claims, coverage/gaps/conflicts, dossier persistence, citations in decks and documents |
| 6 Templates | done (offline-verified) | PPTX analyzer (theme colours/fonts, layouts + archetypes, placeholders with inherited geometry, sample-slide inventory with branding/decorative/sample roles), theme-derived design tokens, manifest cache by SHA-256, `pptx-masters` guide attached to the manifest and planner; DOCX templates reused as-is; XLSX template analysis pending |
| 7 Planning | partial | deck planner + document outliner and parallel section writers, evidence-linked claims, uncited-figure checks; XLSX planner pending |
| 8 PPTX | done (offline-verified) | generated designs and template mode: sample slides removed, layout per archetype, headlines in the layout's title placeholder at inherited sizes, branding re-applied, frame-relative geometry for any slide size; fidelity checks (fonts, sample residue, branding) |
| 9 DOCX | partial | renderer (title page, TOC, exec summary, headings, lists, tables, matplotlib figures, KPI/callout boxes, images, numeric/APA/Harvard citations + references, header/footer page numbers), DOCX template reuse, checks; repair loop and page-flow checks pending |
| 10 XLSX | done (offline-verified) | dataset ingestion with type inference/profiles, workbook planner, openpyxl renderer (README, assumptions with named ranges, formula tables, Excel tables, number formats, charts, Sources), independent recalculation with `formulas`, one corrective planner round on formula errors |
| 11 Orchestration & editing | done (offline-verified) | targeted editing via TargetResolver, block-scoped DOCX edits, slide/section/sheet EditorAgents, Scope Guard, deterministic restyle, V2 persistence preserving untouched units, enhanced Excel recalculation feedback loop with rich formula diagnostics; 232 tests passed |
| 12 QA & evaluation | planned | — |
| 13 App delivery | planned | — |

Milestone **M1 vertical slice** (prompt → DeckPlan → PPTX without template → validated): **done, verified offline**; awaiting a first live run with a real `GEMINI_API_KEY`. Next: Stage 4 completion (target resolution, labelled set), Stage 5 research wired into planning, Stage 6 template analysis.

## Stage 3 — what exists

| Area | Module | Notes |
|---|---|---|
| Config | `core/config.py` | project `.env` names (no prefix), placeholder keys treated as unset, `provider:model` specs, default templates, LibreOffice detection |
| Auth | `core/auth.py`, `api/routes/auth.py` | JWT login (PyJWT), bearer dependency, owner-scoped sessions, prod refuses placeholder secret |
| Logging / errors / IDs | `core/*` | structured logs with job context; error taxonomy incl. transient/rate-limit/schema-rejected/blocked |
| Upload safety | `core/files.py` | magic-byte + OOXML part checks, zip-bomb limits, macro rejection |
| Contracts | `models/*` | all DATA_MODELS schemas with invariants |
| Storage | `storage/*` | `records` table, typed repositories, immutable artifact versions, content-addressed blobs |
| LLM gateway | `llm/*` | vendor-neutral: Gemini + OpenAI-compatible REST adapters, schema-in-prompt structured output with validation + repair, retries with backoff, fallback model, optional native schema with auto-disable, cassettes |
| Embeddings | `llm/providers/*` | Gemini batch embeddings, OpenAI-compatible embeddings, offline hashing embeddings |
| Web search | `research/search.py`, `research/fetch.py` | Tavily (default), DuckDuckGo HTML dev fallback, unavailable-provider reporting, fixtures; safe page-to-text fetch |
| Retrieval | `retrieval/*` | chunking, `KnowledgeIndex`, Pinecone REST store, local SQLite store |
| Template hook | `template/external.py` | optional `pptx-masters` run with configurable command/args, output capture, failure reporting |
| API / UI / CLI | `api/*`, `web/static`, `cli.py` | health (component status), auth, sessions, uploads, downloads, messages; login-aware UI; `docforge health/serve` |

## M1 vertical slice — what exists

| Area | Module | Notes |
|---|---|---|
| Agents | `agents/interpreter.py`, `agents/deck_planner.py` | typed outputs via the gateway; planner forbids invented statistics/quotes without evidence; code renumbers unit IDs |
| Orchestrator | `orchestrator/context.py`, `orchestrator/generate.py` | interpret → clarify / honest "not yet" replies → plan → validate plan (one revision) → design → render/validate/repair → persist version + report → reply |
| Design | `design/system.py` | 9 content-informed palettes, Cambria/Calibri, contrast helpers |
| Layout | `layout/fonts.py`, `layout/text.py` | font resolution (system → metric-compatible substitutes → heuristic), wrapping, proportional fit with floors |
| PPTX renderer | `render/pptx/*` | 13.33×7.5 in, 16 archetypes, real bullets, native charts/tables with alt text, speaker notes, content-sized cards, source footers when evidence exists |
| Validation | `validate/*` | plan checks + 13 file checks (QUALITY §2.1–2.2), tier-4/5 reported as skipped, split-slide repair loop, corrected-vs-unresolved accounting |
| Previews | `render/pptx/preview.py` | PNG previews without LibreOffice (layout QA, thumbnail fallback) |
| API / UI / CLI | `api/routes/sessions.py`, `web/static`, `cli.py` | `POST /messages` generates; download + report endpoints (session-scoped); UI download button; `docforge generate "…" -o deck.pptx` |

Sample outputs: `eval/out/template_demo/` (deck on a corporate template), `eval/out/workbook_demo/workbook.xlsx`, `eval/out/sample_deck.pptx` and `eval/out/sample_deck_preview.png` (13 slides from the fixture plan, zero unresolved findings).

## Verification evidence (Stage 3)

- `pytest`: **186 passed** (offline, no keys). Live (real Gemini 3.8 Flash + Tavily + scholarly search): 8-slide deck on the Green Cream template, 195 s, 14 sources (11 scholarly), verdict pass_with_warnings — `eval/out/live/`. Live checks (no LLM): OpenAlex and arXiv return papers with abstracts; Semantic Scholar keyless hits its rate limit and is reported as a caveat; Openverse photos download, crop and render (`eval/out/images_demo/`). Covers models, config (exact `.env` names), auth, file sniffing, storage, gateway behaviour (repair, retries, fallback, native-schema rejection, truncation), Gemini/OpenAI-compatible/Tavily/Pinecone request shapes and error mapping via `httpx.MockTransport`, DuckDuckGo parsing, retrieval round-trip, `pptx-masters` hook, API flows.
- `ruff check` / `ruff format --check`: clean.
- No vendor SDK in dependencies; repository scan for the previous vendor's identifiers in code and docs: none (except this note).

## Change log

| Date | Change |
|---|---|
| 2026-10-17 | Stages 1–3 completed: documentation set, foundation code. |
| 2026-10-17 | Live fixes: Gemini model chain with quota/retirement skipping (ADR-020), replies for every message, answers to questions, background jobs with progress, new chat UI (sessions sidebar, drag-and-drop files with roles, live progress, slide thumbnails, quality report), clone mode for designed templates (ADR-019) verified on the user's three PPTX templates and in a live Gemini run. |
| 2026-10-17 | Templates + Excel: PPTX template analysis and rendering (Stages 6/8), Excel workbooks with verified formulas (Stage 10), datasets, fidelity checks. |
| 2026-10-17 | Research + documents + imagery: scholarly sources (ADR-017), research pipeline wired into generation with citations and auto references slide, Word generation (outline + parallel section writers, DOCX renderer with templates), Openverse/Pexels photos with credits (ADR-018), preview renderer draws pictures. |
| 2026-10-17 | M1 vertical slice: interpreter + deck planner agents, generation service, design system, text fitting, PPTX renderer (16 archetypes), validator + repair loop, previews, generate/download/report API, CLI `generate`. |
| 2026-10-17 | Made the platform vendor-neutral at the user's request: removed the single-vendor LLM SDK and vendor-tool research; added REST adapters (Gemini, OpenAI-compatible), Tavily search, Pinecone/local retrieval, JWT auth, project `.env` naming. ADR-004/005 superseded; ADR-014/015/016 added. |

## Known limitations / open items

- No live call to Gemini, Tavily or Pinecone yet (no keys on the dev machine). Request shapes follow the providers' current public docs and are asserted in tests; first live checks planned with Stage 4 (`pytest -m live`).
- Gemini's native schema field (`responseJsonSchema`) could not be confirmed in the docs fetched; it is therefore opt-in (`LLM_NATIVE_SCHEMA`) and auto-disabled if rejected. The default prompt+validate path does not depend on it.
- The default fallback model `gemini-2.0-flash` comes from the project `.env`; Google may retire it (PRD Q10).
- No public `pptx-masters` tool was found; the hook's command/args are configurable (PRD Q9).
- Default template files under `data/sample_templates/` are not in the repository; they are used when present and ignored otherwise (`/health` shows availability).
- LibreOffice not installed on the dev machine; tier-4 visual checks will report `skipped` locally.
- The synchronous message endpoint runs generation inside the HTTP request. An alternate background-job endpoint exists; its status/progress is process-local, is polled over HTTP, and does not survive a process restart.
- M1 decks use a generated design only; uploaded/default templates are acknowledged in the reply but not applied until Stage 6/8.
- Research is not yet wired into generation; the planner is instructed not to invent figures, and the reply says research was not performed.
- Visual QA uses the built-in preview renderer (approximate); LibreOffice-based checks remain skipped on this machine.
- Drive C: on the dev machine is full (≈0 bytes free). Tests now use `--basetemp=.pytest_tmp` on the project drive; installs need `TMP`/`TEMP` on D:. The earlier one-off SQLite `OperationalError` was most likely caused by this.
- Semantic Scholar without a key is usually rate-limited; OpenAlex keyless allowance is small (free keys raise both).
- Conversational editing of existing artifacts (PPTX, DOCX, XLSX) is recorded as built and verified in the 2026-10-17 project snapshot; current automated verification was not rerun for this documentation update.
- PPTX template mode re-applies branding pictures; repeated branding *text* on sample slides (e.g. a company name box) is not yet re-applied.
- The preview renderer cannot resolve theme fonts for placeholder text, so template previews show a fallback font (the PPTX itself uses the theme font).
- `formulas` takes ~9 s to import on first workbook validation.
