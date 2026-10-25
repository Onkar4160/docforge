# Command-Line Interface

The console script is registered in `pyproject.toml` as `docforge = docforge.cli:main`. It is available after installing the package. From the repository root, the module form also works:

```powershell
python -m docforge.cli --help
```

The current CLI provides `health`, `serve`, and `generate`. Commands such as `edit`, `eval`, and `analyze-template` are not registered by the current parser.

## `health`

Prints JSON with the installed version, storage path, database URL, selected LLM provider/models, whether a key is configured, search provider state, vector store, available default templates, cassette mode, and LibreOffice discovery.

```powershell
docforge health
```

This is a configuration/status report, not a live test of API credentials.

## `serve`

Runs the FastAPI application through Uvicorn.

```powershell
docforge serve
docforge serve --host 127.0.0.1 --port 8001 --reload
```

Options:

| Option | Default | Purpose |
|---|---|---|
| `--host` | `127.0.0.1` | Bind address. |
| `--port` | `8000` | Listen port. |
| `--reload` | Off | Enable development reload. |

Open `/` for the web UI, `/docs` for OpenAPI docs, and `/health` for health information. Press `Ctrl+C` to stop the foreground server.

## `generate`

Generates a deliverable from a prompt through the configured LLM and writes the resulting file to the requested path. The default output name is `deliverable.pptx`.

```powershell
docforge generate "Create a short project overview" --output overview.pptx
```

Arguments:

| Argument | Required | Description |
|---|---|---|
| `prompt` | Yes | Natural-language generation request. |
| `-o`, `--output` | No | Destination file path; defaults to `deliverable.pptx`. |

Configure a functioning LLM provider before use. The CLI creates a local session with owner `cli`; it does not accept file uploads or expose edit options in its current parser. A provider/configuration failure may return a non-zero exit code.

## Windows launcher alternatives

`run.ps1` and `run.bat` start the server on `127.0.0.1:8000` in a separate console and open a browser. They do not install dependencies. See [INSTALLATION.md](../INSTALLATION.md) for setup.