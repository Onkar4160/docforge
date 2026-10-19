# DocForge — Product Requirements Document

| Field | Value |
|---|---|
| Status | Approved for implementation (Stage 1 complete) |
| Owner | Project team |
| Related | [ARCHITECTURE](architecture/ARCHITECTURE.md) · [PLAN](PLAN.md) · [QUALITY](QUALITY.md) · [DATA_MODELS](DATA_MODELS.md) |

## 1. Product summary

DocForge is a multi-agent AI platform that turns a natural-language request — plus optional templates and source files — into a finished, editable, evidence-backed **PowerPoint (PPTX)**, **Word (DOCX)** or **Excel (XLSX)** file. The user refines the result conversationally; follow-up requests change only what they target.

Success is judged by the delivered file and its evidence, not by the pipeline completing.

## 2. Goals and non-goals

### 2.1 Goals

- G1. Understand purpose, audience, tone, depth and format from natural language, including references to earlier turns and existing artifacts.
- G2. Research external information when the request needs it, and keep every material factual claim traceable to a source or marked as an assumption.
- G3. Plan the information architecture before rendering (storyline, section hierarchy, workbook model).
- G4. Read user templates structurally (masters, layouts, styles, placeholders, sheets, formulas) and preserve their visual identity in new compositions of any length.
- G5. Render professional, editable files and validate them; repair what can be repaired; report the rest honestly.
- G6. Apply targeted edits with minimal collateral change, backed by artifact versioning.
- G7. Be reproducible and testable: deterministic rendering from a stored intermediate representation, replayable LLM calls in tests.

### 2.2 Non-goals (v1)

- Real-time multi-user co-editing of the same artifact.
- Output formats beyond PPTX, DOCX, XLSX (PDF export is a convenience only, when LibreOffice is available).
- Generative image synthesis (v1 uses charts, diagrams, shapes, icons and user-supplied images; an image provider is an extension point).
- Macro-enabled files (`.pptm`, `.docm`, `.xlsm`) as outputs; VBA is never executed.
- Pixel-exact replication of arbitrary SmartArt or embedded OLE objects from templates (preserved when untouched, not re-authored).
- Access to paywalled or login-restricted sources.

## 3. Users and personas

| Persona | Typical need | Key quality bar |
|---|---|---|
| Consultant / analyst | Client-ready deck in corporate template, market research | Template fidelity, evidence, storyline |
| Student / researcher | Report or literature-style document with references | Structure, citations, depth |
| Operations / finance staff | Workbook with calculations, KPIs and charts | Formula correctness, clear structure |
| Manager | Quick briefing deck or memo, then iterative tweaks | Speed, concise messaging, safe edits |

## 4. User scenarios

- **S1 — Deck from prompt, no template.** "Create a 10-slide investor update on the European EV charging market for a non-technical board." → researched, designed deck with charts and sources.
- **S2 — Deck in corporate template, different length.** User uploads a 6-slide template and asks for 14 slides. Output reuses masters, theme, logos and layout vocabulary; sample content is removed.
- **S3 — Researched report.** "Write a 12-page report on microplastics in drinking water with an executive summary and APA references." → DOCX with headings, tables, references.
- **S4 — Report in DOCX template.** Styles, headers/footers, numbering and cover structure of the template are reused.
- **S5 — Analytical workbook.** "Build a 5-year SaaS revenue model with assumptions, monthly calculations and a dashboard." → XLSX with Assumptions, Calculations, Dashboard, Sources sheets and verified formulas.
- **S6 — Dataset analysis.** User uploads a CSV/XLSX and asks for a summary workbook and a 5-slide deck of findings.
- **S7 — Targeted style edit.** "Make the heading font size 20pt." → only heading styles change; content and structure stay identical.
- **S8 — Targeted content edit.** "Rewrite slide 4 to focus on costs and add a chart." → only slide 4 changes.
- **S9 — Ambiguous edit.** "Make it better." on a 20-slide deck → system asks what to improve (or proposes options) rather than regenerating everything.
- **S10 — Regeneration / scope change.** "Actually, make this a Word report instead." → new task inheriting the research and objective.
- **S11 — Unverifiable topic.** Evidence is thin or contradictory → artifact states limitations; quality report lists unsupported claims.

## 5. Functional requirements

Priority: **M** = must (v1), **S** = should (v1 if feasible), **C** = could (later).

### 5.1 Conversation and request understanding (FR-CONV)

| ID | Requirement | Pri |
|---|---|---|
| FR-CONV-1 | Accept a free-text request with optional attached files in a chat session. | M |
| FR-CONV-2 | Classify each message as: new task, continuation, artifact modification, regeneration, objective change, clarification answer, or question. | M |
| FR-CONV-3 | Extract an output specification: format, purpose, audience, tone, language, detail level, length (unit, target, explicit vs inferred), style notes. | M |
| FR-CONV-4 | Infer the output format when not stated (e.g. "deck" → PPTX, "model/calculator" → XLSX) and record the inference as an assumption. | M |
| FR-CONV-5 | Resolve references to prior turns, artifacts and elements ("slide 4", "the chart", "that table", "the second section"). | M |
| FR-CONV-6 | Represent each modification as a change request with scope (artifact / slide / section / sheet / element / style) and operation. | M |
| FR-CONV-7 | Ask for clarification when interpretation confidence is below threshold or the change would be materially destructive; never silently make a materially different change. | M |
| FR-CONV-8 | Persist sessions, messages, tasks, interpretations and artifact versions across restarts. | M |
| FR-CONV-9 | Answer questions about the current artifact or its sources without regenerating it. | S |

### 5.2 Research and evidence (FR-RES)

| ID | Requirement | Pri |
|---|---|---|
| FR-RES-1 | Decide whether research is needed and at what depth (none / light / standard / deep) from objective and deliverable. | M |
| FR-RES-2 | Produce a research plan: prioritised questions linked to the planned deliverable. | M |
| FR-RES-3 | Search and fetch web sources through a pluggable provider (default: Tavily; keyless fallback only in development when `REQUIRE_AUTHENTICATED_WEB_SEARCH=false`). | M |
| FR-RES-4 | Ingest user-supplied sources (PDF, DOCX, PPTX, XLSX, CSV, TXT, MD) as first-class sources. | M |
| FR-RES-5 | Register each source with URL/locator, title, publisher, publication date, retrieval time, type and authority rating. | M |
| FR-RES-6 | Extract atomic evidence items (facts, figures with unit and as-of date, findings, quotes) with source locators. | M |
| FR-RES-7 | Detect conflicting evidence and evidence gaps; record them in the dossier. | M |
| FR-RES-8 | Every factual claim in the content plan carries evidence IDs or an explicit status (assumption, interpretation, estimate, unsupported). | M |
| FR-RES-9 | Compute research coverage (answered / partial / unanswered questions) and expose it in the result. | M |
| FR-RES-10 | Reuse the dossier for follow-ups and format changes within the task. | S |
| FR-RES-11 | Domain allow/deny lists and per-task search budgets are configurable. | S |
| FR-RES-13 | Search scholarly literature (OpenAlex, Semantic Scholar, arXiv) alongside the web; rank peer-reviewed work above preprints and general web pages; cite papers with authors, venue, year and DOI. | M |
| FR-RES-12 | Index user sources for retrieval (chunk + embed + vector store: Pinecone or local) and cite retrieved passages with locators. | M |

### 5.3 Template understanding (FR-TPL)

| ID | Requirement | Pri |
|---|---|---|
| FR-TPL-1 | Accept PPTX/POTX, DOCX/DOTX and XLSX/XLTX templates. | M |
| FR-TPL-2 | PPTX: extract slide size, theme colours and fonts, masters, layouts, placeholders (type, index, geometry, text styles), backgrounds and every shape on sample slides (kind, geometry, z-order, grouping, fill, line, text style, image). | M |
| FR-TPL-3 | Classify elements as structural, branding, decorative, placeholder or sample content. | M |
| FR-TPL-4 | Classify layouts into archetypes (title, section, bullets, two-column, comparison, image+text, chart, table, blank, closing…). | M |
| FR-TPL-5 | DOCX: extract page setup, margins, styles (paragraph, character, table, numbering), headers/footers, section breaks, cover elements, tables. | M |
| FR-TPL-6 | XLSX: extract sheets, used ranges, tables, defined names, formulas and their dependencies, number formats, conditional formats, validations, charts and their ranges. | M |
| FR-TPL-7 | Produce a stored, versioned **Template Manifest** and derived **Design Tokens**. | M |
| FR-TPL-8 | Cache manifests by file hash. | S |
| FR-TPL-9 | Render template thumbnails for UI and visual comparison when a renderer is available. | C |

### 5.4 Content planning (FR-PLAN)

| ID | Requirement | Pri |
|---|---|---|
| FR-PLAN-1 | Generate a format-specific plan (Deck / Document / Workbook) before rendering. | M |
| FR-PLAN-2 | Deck plan: narrative arc; per slide purpose, headline (assertion-style), key message, content blocks, visual archetype, citations, speaker notes. | M |
| FR-PLAN-3 | Document plan: section hierarchy with purpose, argument, evidence and block types per section; front/back matter. | M |
| FR-PLAN-4 | Workbook plan: sheet roles (readme, assumptions, data, calculations, report, sources), table schemas with types/units/formats, formulas, named ranges, charts, expected-value checks. | M |
| FR-PLAN-5 | Length follows explicit user requirements; otherwise is derived from content need, not from template length. | M |
| FR-PLAN-6 | Plan validation: no duplicate messages, no empty units, citation coverage, length compliance, archetype–content fit. | M |
| FR-PLAN-7 | Content blocks are typed (bullets, table, chart, timeline, process, comparison, KPI, quote, image, paragraph). | M |

### 5.5 PPTX generation (FR-PPTX)

| ID | Requirement | Pri |
|---|---|---|
| FR-PPTX-1 | Render editable slides: real text boxes/placeholders, native charts, native tables, shapes — no rasterised text. | M |
| FR-PPTX-2 | With template: build on the template package (masters, layouts, theme retained), remove sample slides, compose new slides on best-matching layouts, reuse branding elements. | M |
| FR-PPTX-3 | Without template: generate a design system (palette, fonts, spacing grid) appropriate to audience and tone. | M |
| FR-PPTX-4 | Layout engine supports archetypes: title, agenda, section, bullets, two-column, comparison, timeline, process, chart, table, KPI, quote, image+text, closing/summary, references. | M |
| FR-PPTX-5 | Text fitting: estimate rendered text size; adjust font within bounds, condense, or split the slide. | M |
| FR-PPTX-6 | Speaker notes and per-slide source footers; references slide when sources exist. | M |
| FR-PPTX-7 | Any slide count, independent of template slide count. | M |
| FR-PPTX-8 | Real photographs where they strengthen the message (cover and image+text slides), from openly licensed or stock sources, cropped to fit and credited on the slide. | S |

### 5.6 DOCX generation (FR-DOCX)

| ID | Requirement | Pri |
|---|---|---|
| FR-DOCX-1 | Title page, optional executive summary/abstract, table of contents field, headings H1–H3, body, lists, tables, figures (charts as images), captions. | M |
| FR-DOCX-2 | Citations in a selectable style (numeric, APA, Harvard) with a references section. | M |
| FR-DOCX-3 | Headers, footers, page numbers, margins, consistent styles. | M |
| FR-DOCX-4 | With template: reuse its styles, numbering, headers/footers, section setup; remove sample body content. | M |
| FR-DOCX-5 | Style overrides (e.g. heading size) applied to styles, not as direct formatting. | M |

### 5.7 XLSX generation (FR-XLSX)

| ID | Requirement | Pri |
|---|---|---|
| FR-XLSX-1 | Named sheets with defined roles; raw data, calculations and reports separated. | M |
| FR-XLSX-2 | Excel tables, typed columns, number formats, units in headers, freeze panes, filters. | M |
| FR-XLSX-3 | Real formulas (not pasted values) for calculated fields; named ranges for assumptions. | M |
| FR-XLSX-4 | Native charts with correct ranges; KPI dashboard sheet where relevant. | M |
| FR-XLSX-5 | Conditional formatting and data validation where meaningful. | S |
| FR-XLSX-6 | Formula verification: compute the workbook independently and compare to expected values; zero `#REF!`, `#NAME?`, `#DIV/0!` (unless intended), circular references flagged. | M |
| FR-XLSX-7 | Sources and assumptions sheet linking figures to sources. | M |
| FR-XLSX-8 | Ingest CSV/XLSX datasets with type inference and cleaning report. | M |

### 5.8 Validation and repair (FR-VAL)

| ID | Requirement | Pri |
|---|---|---|
| FR-VAL-1 | Run format-specific checks after every render (see [QUALITY](QUALITY.md)). | M |
| FR-VAL-2 | Apply automatic repairs (deterministic first, LLM-assisted second) and re-validate up to a configured iteration limit. | M |
| FR-VAL-3 | Quality report distinguishes detected, corrected, unresolved findings and skipped checks (with reason). | M |
| FR-VAL-4 | Files must open in Microsoft Office and LibreOffice (structural validity checked by re-opening with the parsing libraries and, when available, LibreOffice conversion). | M |
| FR-VAL-5 | Visual rendering checks (LibreOffice → PNG) when available; otherwise geometric checks only, reported as such. | S |
| FR-VAL-6 | LLM content review against the plan and evidence (repetition, shallowness, unsupported claims, tone). | S |

### 5.9 Editing and versioning (FR-EDIT)

| ID | Requirement | Pri |
|---|---|---|
| FR-EDIT-1 | Every generation or edit creates a new immutable artifact version with parent link and change summary. | M |
| FR-EDIT-2 | Edits are applied as patches to the intermediate representation; only affected units are re-planned/re-written. | M |
| FR-EDIT-3 | Regression guard: units outside the change scope must be byte/structure-identical in the IR and equivalent in the rendered file. | M |
| FR-EDIT-4 | User can download any version and revert to a previous version. | M |
| FR-EDIT-5 | Edits to externally created files (no IR): import to IR where supported, otherwise apply direct, minimal file-level edits. | S |

### 5.10 Application and UX (FR-UX)

| ID | Requirement | Pri |
|---|---|---|
| FR-UX-1 | Web UI: chat, file upload (template / source / dataset role), output preferences, progress status, downloads, sources, quality report. | M |
| FR-UX-2 | REST API covering the same capabilities; job status via polling and server-sent events. | M |
| FR-UX-3 | CLI for local/batch use and evaluation runs. | M |
| FR-UX-4 | Slide/page thumbnails preview when a renderer is available. | C |
| FR-UX-5 | Authenticated access: login issues a JWT; sessions, files and artifacts are scoped to their owner. | M |

## 6. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 Reproducibility | Rendering is deterministic for a given IR + template + config. LLM calls are recorded and replayable in tests (cassettes). |
| NFR-2 Testability | Every stage has unit tests with fixtures; end-to-end tests run offline with replayed LLM responses. |
| NFR-3 Performance | Typical 10-slide researched deck ≤ 6 min; targeted edit ≤ 60 s (excluding provider latency spikes). Progress reported per stage. |
| NFR-4 Cost control | Per-task token and search budgets; usage logged per LLM call. |
| NFR-5 Reliability | Provider errors retried with backoff; a failed stage leaves the task resumable; partial results never presented as complete. |
| NFR-6 Security | Uploads size-limited and type-checked by content; zip-bomb and XXE protections; macros never executed; API keys only from environment/secret store; no user content in logs at INFO level. |
| NFR-7 Privacy | User files and artifacts stored per session; deletion endpoint removes files, versions and evidence. |
| NFR-8 Portability | Runs on Windows, macOS, Linux with Python 3.12; LibreOffice optional. |
| NFR-9 Modularity | Agents, providers, renderers and validators behind interfaces; new format or provider without changing the orchestrator core. |
| NFR-12 Vendor neutrality | No vendor SDK dependency for LLM, search or vector storage; backends selected by configuration; the system runs fully offline (fakes, hashing embeddings, local vectors) for tests. |
| NFR-10 Observability | Structured logs with task/job IDs; per-stage timings; quality and usage metrics. |
| NFR-11 Accessibility | Generated decks/documents: real heading structure, alt text for charts/images, sufficient colour contrast (WCAG AA for text). |

## 7. Constraints and assumptions

- LLM access is vendor-neutral (ADR-004): default backend Google Gemini over REST (`LLM_PRIMARY_MODEL=gemini-2.5-flash`, `LLM_FALLBACK_MODEL=gemini-2.0-flash`); any OpenAI-compatible server (Ollama, vLLM, LM Studio, OpenRouter, OpenAI) can serve any role via `provider:model` specs.
- Web research uses Tavily (`TAVILY_API_KEY`); without it and with `REQUIRE_AUTHENTICATED_WEB_SEARCH=true`, research is reported as unavailable rather than silently degraded.
- Retrieval uses Pinecone (`PINECONE_*`) when configured, otherwise a local vector store.
- File libraries: `python-pptx`, `python-docx`, `openpyxl`; `lxml` for OOXML parts not covered by them.
- LibreOffice is optional; features depending on it are feature-detected and reported as skipped when absent.

## 8. Acceptance criteria

The product is accepted when all M-priority requirements are implemented and the following pass in the evaluation suite ([TESTING](TESTING.md)):

| ID | Criterion |
|---|---|
| AC-1 | For each scenario S1–S11 there is at least one automated end-to-end case that passes offline with replayed LLM responses. |
| AC-2 | 100 % of generated files re-open without error in python-pptx/python-docx/openpyxl; when LibreOffice is present, 100 % convert to PDF. |
| AC-3 | PPTX: zero unresolved *critical* findings (text overflow beyond box, off-slide elements, leftover template sample text, empty placeholders) across the evaluation set. |
| AC-4 | XLSX: zero formula errors; 100 % of declared expected-value checks pass within tolerance. |
| AC-5 | ≥ 95 % of factual claims in generated plans carry evidence IDs or an explicit non-fact status; 100 % of cited source IDs resolve to registered sources. |
| AC-6 | Targeted edits: in the edit regression set, 100 % of out-of-scope units are unchanged in IR, and the requested change is present. |
| AC-7 | Explicit length requests honoured exactly for slides/sheets and within ±15 % for pages/words. |
| AC-8 | Template fidelity: generated decks use only the template's masters/layouts/theme fonts/colours (no foreign fonts or palette) and retain designated branding elements. |
| AC-9 | Ambiguous-edit cases in the evaluation set produce a clarification request, not a regeneration. |
| AC-10 | Quality report present for every delivered version, with counts of detected/corrected/unresolved findings and skipped checks. |

Human-rated criteria (content quality, design quality, storyline) are scored with the rubric in [QUALITY](QUALITY.md) §4; target mean ≥ 4/5.

## 9. Scope boundaries summary

In: three formats, templates, web + file research, conversational editing, validation, versioning, web UI, API, CLI.
Out (v1): co-editing, image generation, macros, PDF-native output, paywalled sources, SmartArt authoring.

## 10. Unresolved-question register

| ID | Question | Default until resolved | Owner | Status |
|---|---|---|---|---|
| Q1 | Should an image-generation or stock-photo provider be integrated for decks? | No; use charts/shapes/user images. Extension point exists. | Product | Open |
| Q2 | Which citation styles are mandatory beyond numeric/APA/Harvard? | Those three. | Product | Open |
| Q3 | Multi-user accounts and authentication for hosted deployment? | v1: JWT login for one configured user, owner-scoped sessions (ADR-015). Multi-user store later. | Ops | Resolved for v1 |
| Q4 | Required support for right-to-left and CJK languages? | Unicode text supported; layout tuned for LTR Latin. | Product | Open |
| Q5 | Is LibreOffice guaranteed in production images? | Docker image includes it; local installs optional. | Ops | Proposed |
| Q6 | Maximum template and source file sizes? | `UPLOAD_MAX_MB` (default 25 MB) per file. | Ops | Resolved |
| Q7 | Retention period for artifacts and evidence? | Until user deletes session. | Product | Open |
| Q8 | Which web search provider? | Tavily default; DuckDuckGo HTML for development only; others via `SearchProvider` (ADR-005). | Eng | Resolved |
| Q9 | Which `pptx-masters` CLI and output format should the optional design-guide hook expect? | Command and args configurable; any text/JSON outputs attached as guidance. | Product | Open |
| Q11 | Semantic Scholar's keyless rate limit is often exhausted; obtain a free key for production? | Pipeline continues with other sources and reports the limit. | Ops | Open |
| Q10 | `gemini-2.0-flash` (fallback) may be retired by Google; which fallback model to standardise on? | Keep configurable; verify availability at deployment. | Ops | Open |
