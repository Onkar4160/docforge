# Testing

## Scope

The checked-in automated tests are in `tests/unit/`, with shared data and fixtures under `tests/fixtures/`. Tests exercise models, configuration, API behavior, storage, generation/rendering, research adapters, and other package components. The repository does not currently contain the separately described `tests/component/`, `tests/e2e/`, `tests/live/`, or `tests/visual/` directories, nor an `eval/` runner; do not treat those planned layers as available test commands.

The default pytest configuration in `pyproject.toml` uses `tests/`, excludes markers `live` and `visual`, and writes temporary files to `.pytest_tmp`. Tests use fake LLM/search dependencies where applicable; the default suite is intended to run without service credentials.

## Install test tools

Install the editable package and development extras from the repository root:

```powershell
python -m pip install -e ".[dev]"
```

On Windows, when using the project virtual environment, run `\.venv\Scripts\python.exe -m pip install -e ".[dev]"` instead. `.[dev]` adds pytest and Ruff; runtime dependencies are installed with the package.

## Run tests

```powershell
python -m pytest
```

Useful narrower checks:

```powershell
python -m pytest tests/unit/test_api.py
python -m pytest tests/unit/test_storage.py
```

From PowerShell, substitute `\.venv\Scripts\python.exe` for `python` if the environment is not activated. The test suite is configured by `[tool.pytest.ini_options]` in `pyproject.toml`.

## Lint

```powershell
python -m ruff check src tests
```

Ruff is the configured linter. The repository instructions also mention `ruff format`; there is no formatter check configured as a required test command in `pyproject.toml`.

## Optional marked tests

The pytest config declares `live`, `visual`, and `slow` markers and filters `live` and `visual` from the default run. The current test tree may not contain tests for every marker. If applicable to a test present in the checkout:

```powershell
python -m pytest -m live
python -m pytest -m visual
```

Live tests can call external providers and consume quota or require API credentials. Visual checks may require LibreOffice. Check the selected tests before running them against real services.

## Fixtures and test doubles

- `tests/conftest.py` supplies isolated settings, temporary storage, a FastAPI `TestClient`, `FakeLLMClient`, hashing embeddings, and fixture search.
- `tests/fixtures/` contains reusable deck, document, workbook, and template fixture helpers.
- Adapter tests use mocked HTTP transports; unit tests should not require network access.
- Presentation regressions cover backward-compatible manifests, cached/evidence-bounded template prompts, stable-ID insertion and moves, non-adjacent-anchor clarification, style-scope isolation, confirmation before risky styling, and rendered PPTX font/color/size values.

## Failures

- Confirm the command is run from the repository root, where `pyproject.toml` is located.
- Reinstall the editable package if imports fail: `python -m pip install -e ".[dev]"`.
- If a test fails while creating temporary files, check free disk space and write permissions. Pytest's configured temporary base is `.pytest_tmp` in the project directory.
- For a provider-related test, confirm whether it is marked `live` before adding credentials or enabling network access.

See [QUALITY.md](QUALITY.md) for artifact quality criteria and [STATUS.md](STATUS.md) for the project's recorded verification evidence. Historical test counts in STATUS describe the state at its `Last updated` date, not a current run.
