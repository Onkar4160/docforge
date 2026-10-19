# DocForge — Quality Model

Defines what "good" means for each deliverable, how it is checked, the thresholds that gate delivery, and how results are reported.

## 1. Quality dimensions

| Dimension | Question it answers | Primary checker |
|---|---|---|
| Content | Is it accurate, relevant, deep enough, non-repetitive, on-tone? | Plan validation, ReviewerAgent, human rubric |
| Evidence | Are factual claims traceable and honestly labelled? | Evidence checks |
| Structure | Is the narrative/hierarchy/workbook model coherent and complete? | Plan validation, structural checks |
| Layout | Do elements fit, align, avoid overlap and stay in bounds? | Geometric checks, visual checks |
| Typography | Are fonts, sizes, hierarchy consistent and readable? | Style checks |
| Data | Are numbers, formulas, ranges and types correct? | Formula engine, workbook checks |
| Template fidelity | Is the template's identity preserved and sample residue removed? | Template checks |
| Accessibility | Headings, alt text, contrast. | Accessibility checks |
| Validity | Does the file open and convert cleanly? | Re-open + LibreOffice conversion |

## 2. Check catalogue

Tier: 1 structural · 2 geometric/text-metric · 3 computation · 4 visual (LibreOffice) · 5 LLM review. Severity is the default for a failure.

### 2.1 Common

| Check ID | Tier | Rule | Sev |
|---|---|---|---|
| `common.reopen` | 1 | File re-opens with its library. | critical |
| `common.convert` | 4 | LibreOffice converts to PDF without error. | critical |
| `common.length` | 1 | Explicit length honoured (slides/sheets exact; pages/words ±15 %). | major |
| `evidence.citations_resolve` | 1 | Every cited claim/source ID exists. | critical |
| `evidence.coverage` | 1 | ≥ 95 % factual claims have evidence or a non-fact status. | major |
| `evidence.unsupported_flagged` | 1 | Unsupported claims are not presented as fact (labelled or removed). | major |
| `content.duplicates` | 1 | No two units share near-identical headline/key message (normalised similarity ≥ 0.9). | major |
| `content.empty_units` | 1 | No empty slide/section/sheet. | critical |
| `content.placeholder_text` | 1 | No "Lorem ipsum", "Click to add", "TBD", "[insert]". | critical |
| `content.review` | 5 | ReviewerAgent findings (shallow, repetitive, off-tone, unsupported). | minor–major |
| `a11y.alt_text` | 1 | Pictures/charts have alt text. | minor |
| `a11y.contrast` | 2 | Text/background contrast ≥ 4.5:1 (≥ 3:1 for ≥ 18 pt). | major |

### 2.2 PPTX

| Check ID | Tier | Rule | Sev |
|---|---|---|---|
| `pptx.text_overflow` | 2 | Measured text height ≤ box height (after autofit floor). | critical |
| `pptx.font_floor` | 2 | Body ≥ 12 pt, headline ≥ 20 pt, footnote ≥ 9 pt. | major |
| `pptx.out_of_bounds` | 2 | Every element inside the slide. | critical |
| `pptx.overlap` | 2 | No unintended overlap between content elements (intersection > 2 % of smaller area). | major |
| `pptx.empty_placeholder` | 1 | No empty placeholders left visible. | critical |
| `pptx.sample_residue` | 1 | No template sample text or sample-only images remain. | critical |
| `pptx.density` | 2 | ≤ 6 bullets per box, ≤ 80 words per slide body (configurable per archetype). | minor |
| `pptx.alignment` | 2 | Content left edges snap to layout grid (± 0.05 in). | minor |
| `pptx.template_fonts` | 1 | Only theme / template fonts used when template provided. | major |
| `pptx.template_palette` | 1 | Shape/text colours from theme palette or tints of it. | major |
| `pptx.branding_retained` | 1 | Branding elements identified in the manifest present on each applicable slide. | major |
| `pptx.chart_data` | 1 | Native chart series lengths equal category count; no NaN. | critical |
| `pptx.visual_clipping` | 4 | Rendered image shows no text beyond box bounds (pixel diff vs box mask). | major |

### 2.3 DOCX

| Check ID | Tier | Rule | Sev |
|---|---|---|---|
| `docx.heading_hierarchy` | 1 | No skipped heading levels; one Title. | major |
| `docx.styles_used` | 1 | Body/heading text uses named styles, not direct formatting overrides. | minor |
| `docx.toc_present` | 1 | TOC field present when requested. | minor |
| `docx.references` | 1 | References section lists every cited source exactly once, in citation-style order. | major |
| `docx.tables` | 1 | Tables have header row, consistent column count. | major |
| `docx.page_numbers` | 1 | Footer page number field present. | minor |
| `docx.template_styles` | 1 | Template style names used for mapped roles. | major |
| `docx.page_flow` | 4 | No near-empty pages caused by breaks; no orphaned headings at page bottom. | minor |

### 2.4 XLSX

| Check ID | Tier | Rule | Sev |
|---|---|---|---|
| `xlsx.formula_errors` | 3 | No computed `#REF!`, `#NAME?`, `#VALUE!`, `#DIV/0!`, `#N/A` (unless declared). | critical |
| `xlsx.expected_values` | 3 | All plan `checks` within tolerance. | critical |
| `xlsx.circular` | 3 | No circular references unless declared. | critical |
| `xlsx.refs_resolve` | 1 | All formula sheet/cell/name references exist. | critical |
| `xlsx.number_formats` | 1 | Typed columns carry formats (currency/percent/date). | minor |
| `xlsx.chart_ranges` | 1 | Chart ranges inside populated data. | major |
| `xlsx.hardcoded_calcs` | 1 | Columns declared as calculated contain formulas, not values. | major |
| `xlsx.sources_sheet` | 1 | Sources/assumptions sheet present when external figures used. | major |
| `xlsx.sheet_names` | 1 | ≤ 31 chars, unique, no invalid characters. | critical |

## 3. Gating thresholds

A version is **delivered** in all cases (users always get the best effort), with a verdict:

- `pass` — no unresolved findings ≥ minor except info; no skipped tier 1–3 checks.
- `pass_with_warnings` — unresolved minor/major findings, or tier 4/5 checks skipped.
- `fail` — any unresolved critical finding. The UI shows the failure prominently; the assistant message says what is wrong.

Repair loop limit: `MAX_REPAIR_ITERATIONS = 3` (configurable). LLM repairs per iteration capped by budget.

## 4. Human evaluation rubric (1–5)

| Criterion | 1 | 3 | 5 |
|---|---|---|---|
| Relevance | Misses the request | Mostly on target | Precisely fulfils purpose and audience |
| Accuracy & evidence | Errors/unsupported | Minor gaps | Accurate, sourced, limitations stated |
| Structure & storyline | Disorganised | Logical but flat | Compelling arc / clear hierarchy |
| Depth | Superficial | Adequate | Insightful, specific, quantified |
| Visual design | Broken/cluttered | Clean but generic | Polished, purposeful visuals |
| Template fidelity | Identity lost | Recognisable | Indistinguishable from in-house work |
| Edit precision | Collateral damage | Small side effects | Exactly the requested change |

Target: mean ≥ 4.0, no criterion mean < 3.5 on the evaluation set.

## 5. Reporting requirements

Each `QualityReport` (see DATA_MODELS §9) is stored with the version and shown in the UI/API:

1. Verdict and counts: detected / corrected / unresolved / skipped.
2. Unresolved findings with unit reference and plain-language message.
3. Corrected findings with the repair action taken.
4. Skipped checks with reason (e.g. "LibreOffice not installed — visual checks not performed").
5. Evidence summary: sources used, coverage, unsupported claims and gaps.

The assistant's delivery message summarises 1, 2 and 4 in one or two sentences.
