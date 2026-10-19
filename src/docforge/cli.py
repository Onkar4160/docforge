"""Command-line interface (FR-UX-3). Subcommands grow with each stage."""

from __future__ import annotations

import argparse
import json
import sys

from docforge import __version__
from docforge.core.config import get_settings


def _health(_: argparse.Namespace) -> int:
    settings = get_settings()
    lo = settings.find_libreoffice()
    print(
        json.dumps(
            {
                "version": __version__,
                "storage_dir": str(settings.storage_dir.resolve()),
                "database_url": settings.database_url,
                "llm_provider": settings.llm_provider,
                "llm_primary_model": settings.llm_primary_model,
                "llm_fallback_model": settings.fallback_models,
                "llm_key_configured": bool(settings.gemini_api_key) or settings.llm_provider != "gemini",
                "web_search": "tavily"
                if settings.tavily_api_key
                else (
                    "unavailable (TAVILY_API_KEY required)"
                    if settings.require_authenticated_web_search
                    else "duckduckgo_html (development fallback)"
                ),
                "vector_store": settings.resolved_vector_store,
                "default_templates": {
                    f: str(settings.default_template(f) or "missing") for f in ("pptx", "docx")
                },
                "cassette_mode": settings.llm_cassette_mode,
                "libreoffice": str(lo) if lo else None,
            },
            indent=2,
        )
    )
    return 0


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("docforge.api.app:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def _generate(args: argparse.Namespace) -> int:
    import asyncio
    import shutil
    from pathlib import Path

    from docforge.container import Container
    from docforge.core.ids import new_id
    from docforge.core.logging import configure_logging
    from docforge.models.conversation import Message, Role, Session
    from docforge.orchestrator.generate import GenerationService

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    async def run() -> int:
        c = Container.build(settings)
        try:
            session = c.repos.sessions.put(Session(id=new_id("session"), owner="cli", title=args.prompt[:60]))
            message = c.repos.messages.put(
                Message(id=new_id("message"), session_id=session.id, role=Role.user, content=args.prompt)
            )
            reply = await GenerationService(c).handle_message(session, message)
            print(reply.message.content)
            if reply.version is None:
                return 2
            out = Path(args.output)
            shutil.copyfile(c.blobs.resolve(reply.version.blob_path), out)
            print(f"Saved {out.resolve()}")
            return 0
        finally:
            await c.aclose()

    return asyncio.run(run())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="docforge", description="DocForge command-line interface")
    parser.add_argument("--version", action="version", version=f"docforge {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="show configuration and optional dependency status").set_defaults(
        func=_health
    )

    gen = sub.add_parser("generate", help="generate a deliverable from a prompt (uses the configured LLM)")
    gen.add_argument("prompt")
    gen.add_argument("-o", "--output", default="deliverable.pptx")
    gen.set_defaults(func=_generate)

    serve = sub.add_parser("serve", help="run the web application")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    serve.set_defaults(func=_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
