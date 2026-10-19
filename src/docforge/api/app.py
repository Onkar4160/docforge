"""FastAPI application factory. Routes stay thin; behaviour lives in the core packages."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from docforge import __version__
from docforge.api.routes import auth, health, sessions
from docforge.container import Container
from docforge.core.config import Settings, get_settings
from docforge.core.errors import DocForgeError
from docforge.core.logging import configure_logging, get_logger

STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
log = get_logger(__name__)


def create_app(
    settings: Settings | None = None, container_factory: Callable[[Settings], Container] | None = None
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)
    if settings.auth_enabled and settings.jwt_secret_is_default:
        if settings.app_env == "prod":
            raise RuntimeError("JWT_SECRET must be changed before running with APP_ENV=prod")
        log.warning("JWT_SECRET is the placeholder value; change it before any shared deployment")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = (container_factory or Container.build)(settings)
        try:
            yield
        finally:
            await app.state.container.aclose()

    app = FastAPI(title="DocForge", version=__version__, lifespan=lifespan)

    @app.exception_handler(DocForgeError)
    async def _docforge_error(_: Request, exc: DocForgeError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.http_status == 401 else None
        return JSONResponse(status_code=exc.http_status, content={"error": exc.to_dict()}, headers=headers)

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> FileResponse:
            return FileResponse(STATIC_DIR / "index.html")

    return app


def __getattr__(name: str):  # lazily build ``app`` so importing this module has no side effects
    if name == "app":
        return create_app()
    raise AttributeError(name)
