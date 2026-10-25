from __future__ import annotations

from fastapi import APIRouter, Depends

from docforge import __version__
from docforge.api.deps import get_container
from docforge.container import Container

router = APIRouter(tags=["ops"])


@router.get("/health")
def health(c: Container = Depends(get_container)) -> dict:
    s = c.settings
    libreoffice = s.find_libreoffice()
    db_ok = c.db_ok()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": __version__,
        "database": db_ok,
        "llm": {
            "provider": s.llm_provider,
            "primary_model": s.llm_primary_model,
            "fallback_model": s.fallback_models,
            "configured": bool(s.gemini_api_key) or s.llm_provider != "gemini",
            "cassette_mode": s.llm_cassette_mode,
        },
        "web_search": {"provider": c.search.name, "authenticated": c.search.authenticated},
        "academic_sources": [p.name for p in c.academic],
        "vector_store": c.vectors.name,
        "embeddings": c.embedder.name,
        "default_templates": {fmt: bool(s.default_template(fmt)) for fmt in ("pptx", "docx", "xlsx")},
        "pptx_masters_enabled": s.pptx_masters_enabled,
        "libreoffice": str(libreoffice) if libreoffice else None,
        "auth_enabled": s.auth_enabled,
    }
