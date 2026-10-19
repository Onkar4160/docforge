# DocForge — Testing Strategy

## 1. Goals

- Every component verified against its requirements (PRD IDs referenced in test docstrings or markers).
- Default test run is **offline, deterministic and free**: no network, no API key.
- Live tests against the real model are opt-in and budgeted.

## 2. Test layers

| Layer | Location | Scope | Runs |
|---|---|---|---|
| Unit | `tests/unit/` | Pure functions, models, analyzers, layout, renderers, checks | Always |
| Component | `tests/component/` | One stage with fake LLM / fixture provider (e.g. research pipeline with fixture search) | Always |
| End-to-end (replay) | `tests/e2e/` | Full orchestrator flows with replayed LLM cassettes | Always |
| Live | `tests/live/` | Real external services (Gemini, Tavily, Pinecone), small requests | `pytest -m live` with the matching keys |
| Visual | `tests/visual/` | LibreOffice rendering + image comparison | `pytest -m visual` when LibreOffice found |
| Evaluation | `eval/` | Scenario suite S1–S11, quality metrics, human-rating sheets | `docforge eval` |

Markers (`pyproject.toml`): `live`, `visual`, `slow`. Default `addopts` deselects `live` and `visual`.

## 3. LLM test doubles

- `FakeLLMClient`: returns scripted Pydantic objects per agent name, records requests. Used in unit/component tests.
- `FakeChatProvider`: scripted provider replies/exceptions for exercising the gateway's retry, repair and fallback logic.
- REST adapters (Gemini, OpenAI-compatible, Tavily, Pinecone) are tested against `httpx.MockTransport`, asserting request shape and error mapping without network.
- `ReplayLLMClient`: reads cassettes (`tests/cassettes/<suite>/<request_hash>.json`) produced by `LLM_CASSETTE_MODE=record`. Missing cassette → test fails with the hash and agent name, never silently calls the network.
- Request hash = SHA-256 of canonical JSON of (`provider:model`, system, messages, output JSON schema, temperature). Volatile values (timestamps, IDs) are excluded from prompts by design so hashes are stable.

## 4. Fixtures

| Fixture | Purpose |
|---|---|
| `tests/fixtures/templates/pptx/` | Generated-in-test templates (corporate-like: logo on layout, custom theme, branding shape on sample slides) and any licensed real templates |
| `tests/fixtures/templates/docx/` | Styled template with header/footer, custom heading styles, cover page |
| `tests/fixtures/templates/xlsx/` | Template with assumptions sheet, table, formulas, chart |
| `tests/fixtures/sources/` | Small PDFs/DOCX/CSV used as user sources |
| `tests/fixtures/search/` | Fixture search results + page texts for the offline search provider |
| `tests/fixtures/documents.py` | Document outline + written sections covering every block type |
| `tests/fixtures/decks.py` | Hand-written DeckPlan covering all archetypes (renderer, validator, pipeline tests) |
| `tests/fixtures/ir/` | Further DocumentPlan / WorkbookPlan samples (Stages 9–10) |

Template fixtures are built programmatically by `tests/fixtures/build_fixtures.py` so they are reproducible and licence-clean.

## 5. Quality metrics tracked

| Metric | Definition | Target |
|---|---|---|
| Reopen rate | files reopened without error / files generated | 100 % |
| Critical findings | unresolved critical findings per artifact | 0 |
| Citation resolution | resolved cited IDs / cited IDs | 100 % |
| Evidence coverage | factual claims with evidence or explicit status / factual claims | ≥ 95 % |
| Formula pass rate | expected-value checks passed / checks | 100 % |
| Length compliance | artifacts meeting explicit length | 100 % slides/sheets; pages ±15 % |
| Edit precision | out-of-scope units unchanged / out-of-scope units | 100 % |
| Clarification recall | ambiguous cases that asked / ambiguous cases | ≥ 90 % |
| Template fidelity | fidelity checks passed / applicable | 100 % |
| Human rubric | mean of QUALITY §4 | ≥ 4.0 |

## 6. Verification procedure per stage

A stage is **verified** (STATUS) only when:
1. Its unit/component tests pass in CI (`pytest`).
2. Requirements it implements have at least one test referencing the requirement ID.
3. For generators: sample outputs from fixtures are produced under `eval/out/` and inspected (automatically, plus a manual spot check recorded in STATUS).
4. Documentation (DATA_MODELS, ARCHITECTURE, STATUS) updated.

## 7. Commands

```bash
pytest                       # offline suite
pytest -m live               # requires GEMINI_API_KEY / TAVILY_API_KEY / PINECONE_API_KEY; uses quota
pytest -m visual             # requires LibreOffice
ruff check src tests         # lint
python -m docforge.cli eval --suite smoke
```

## 8. Test environments

| Env | Python | LibreOffice | Network | Purpose |
|---|---|---|---|---|
| Dev (Windows/macOS/Linux) | 3.12 | optional | optional | daily work |
| CI | 3.12 | yes (Docker image) | no | offline + visual |
| Nightly | 3.12 | yes | yes | live + evaluation |
