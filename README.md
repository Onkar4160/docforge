# DocForge

Research-driven, template-aware generation of editable **PowerPoint**, **Word** and **Excel** deliverables, with conversational editing and validated output.

Vendor-neutral: LLMs via Gemini or any OpenAI-compatible server (Ollama, vLLM, LM Studio, OpenRouter...), web research via Tavily, retrieval via Pinecone or a local store, all chosen in `.env`.

> Status: foundation stage (Stages 1–3 of 13). See [docs/STATUS.md](docs/STATUS.md).

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env              # add GEMINI_API_KEY, TAVILY_API_KEY (optional: PINECONE_API_KEY)
pytest                            # offline test suite, no API key needed
docforge serve                    # http://127.0.0.1:8000  (sign in with DEMO_USERNAME / DEMO_PASSWORD)
```

## Documentation

| Document | Purpose |
|---|---|
| [AGENTS.md](AGENTS.md) | Agent roles, conventions, constraints |
| [docs/PRD.md](docs/PRD.md) | Requirements, scenarios, acceptance criteria |
| [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md) | Components, flows, security, lifecycle |
| [docs/architecture/DECISIONS.md](docs/architecture/DECISIONS.md) | Architecture decision records |
| [docs/DATA_MODELS.md](docs/DATA_MODELS.md) | Shared schemas and contracts |
| [docs/QUALITY.md](docs/QUALITY.md) | Quality checks, thresholds, reporting |
| [docs/TESTING.md](docs/TESTING.md) | Test strategy and verification procedure |
| [docs/PLAN.md](docs/PLAN.md) | Stages, dependencies, milestones |
| [docs/STATUS.md](docs/STATUS.md) | Current state and verification evidence |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Setup, configuration, operations |
