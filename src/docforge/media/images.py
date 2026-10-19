"""Stock and openly licensed images for slides and documents.

Openverse (openly licensed, keyless) by default; Pexels when ``PEXELS_API_KEY`` is set. Every image
keeps its credit line, which renderers print next to it (CC BY attribution requirement).
"""

from __future__ import annotations

import io
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from PIL import Image

from docforge.core.config import Settings
from docforge.core.errors import ResearchError
from docforge.core.logging import get_logger
from docforge.models.ir import DeckPlan, DocumentPlan, ImageBlock, SlideArchetype
from docforge.storage import BlobStore

log = get_logger(__name__)

OPENVERSE_URL = "https://api.openverse.org/v1/images/"
PEXELS_URL = "https://api.pexels.com/v1/search"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIN_WIDTH = 800


# Wikimedia and others reject anonymous agents; a contact makes requests policy-compliant.
def user_agent(contact: str | None) -> dict[str, str]:
    return {"User-Agent": f"DocForge/0.1 (document generation; contact: {contact or 'admin@localhost'})"}


@dataclass
class ImageCandidate:
    url: str
    width: int
    height: int
    credit: str
    landing_url: str
    fallback_url: str | None = None  # e.g. Openverse's proxy when the origin host refuses
    title: str = ""


class ImageProvider(ABC):
    name: str

    @abstractmethod
    async def search(self, query: str, *, count: int = 5, wide: bool = True) -> list[ImageCandidate]: ...

    async def download(self, candidate: ImageCandidate) -> bytes:
        try:
            return await self._fetch(candidate.url)
        except ResearchError:
            if not candidate.fallback_url:
                raise
            return await self._fetch(candidate.fallback_url)

    async def _fetch(self, url: str) -> bytes:
        try:
            async with self.client.stream("GET", url, follow_redirects=True) as resp:
                if not resp.is_success:
                    raise ResearchError(f"image download failed ({resp.status_code})")
                data = bytearray()
                async for chunk in resp.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise ResearchError("image too large")
        except httpx.HTTPError as exc:
            raise ResearchError(f"image download failed: {exc.__class__.__name__}") from exc
        return bytes(data)

    async def aclose(self) -> None:
        await self.client.aclose()


class OpenverseProvider(ImageProvider):
    name = "openverse"

    def __init__(self, client: httpx.AsyncClient | None = None, contact: str | None = None) -> None:
        self.client = client or httpx.AsyncClient(timeout=30, headers=user_agent(contact))

    async def search(self, query: str, *, count: int = 5, wide: bool = True) -> list[ImageCandidate]:
        params = {
            "q": query,
            "page_size": str(count),
            "license_type": "commercial,modification",
            "mature": "false",
        }
        if wide:
            params["aspect_ratio"] = "wide"
        try:
            resp = await self.client.get(OPENVERSE_URL, params=params)
        except httpx.HTTPError as exc:
            raise ResearchError(f"openverse request failed: {exc.__class__.__name__}") from exc
        if not resp.is_success:
            raise ResearchError(f"openverse error {resp.status_code}")
        out = []
        for r in resp.json().get("results", []):
            if not r.get("url"):
                continue
            license_text = f"CC {r.get('license', '').upper()} {r.get('license_version') or ''}".strip()
            if r.get("license") in ("cc0", "pdm"):
                license_text = "public domain"
            credit = (
                f"Photo: {r.get('creator') or 'unknown'} ({r.get('provider') or 'Openverse'}), {license_text}"
            )
            out.append(
                ImageCandidate(
                    r["url"],
                    int(r.get("width") or 0),
                    int(r.get("height") or 0),
                    credit,
                    r.get("foreign_landing_url") or r["url"],
                    f"{r['thumbnail']}?full_size=true" if r.get("thumbnail") else None,
                    r.get("title") or "",
                )
            )
        return out


class PexelsProvider(ImageProvider):
    name = "pexels"

    def __init__(
        self, api_key: str, client: httpx.AsyncClient | None = None, contact: str | None = None
    ) -> None:
        headers = {**user_agent(contact), "Authorization": api_key}
        self.client = client or httpx.AsyncClient(timeout=30, headers=headers)

    async def search(self, query: str, *, count: int = 5, wide: bool = True) -> list[ImageCandidate]:
        params = {"query": query, "per_page": str(count)}
        if wide:
            params["orientation"] = "landscape"
        try:
            resp = await self.client.get(PEXELS_URL, params=params)
        except httpx.HTTPError as exc:
            raise ResearchError(f"pexels request failed: {exc.__class__.__name__}") from exc
        if not resp.is_success:
            raise ResearchError(f"pexels error {resp.status_code}")
        return [
            ImageCandidate(
                p["src"].get("large2x") or p["src"]["original"],
                int(p.get("width") or 0),
                int(p.get("height") or 0),
                f"Photo: {p.get('photographer', 'unknown')} (Pexels)",
                p.get("url", ""),
                title=p.get("alt") or "",
            )
            for p in resp.json().get("photos", [])
            if p.get("src")
        ]


def build_image_provider(settings: Settings) -> ImageProvider | None:
    if not settings.images_enabled or settings.image_provider == "none":
        return None
    if settings.image_provider in ("auto", "pexels") and settings.pexels_api_key:
        return PexelsProvider(settings.pexels_api_key, contact=settings.research_contact_email)
    if settings.image_provider == "pexels":
        log.warning("IMAGE_PROVIDER=pexels but PEXELS_API_KEY is not set; using Openverse")
    return OpenverseProvider(contact=settings.research_contact_email)


def relevance(query: str, title: str) -> int:
    words = {w for w in re.findall(r"[a-z]{3,}", query.lower())} - {"the", "and", "with", "for"}
    return sum(1 for w in words if w in title.lower())


def _normalise(data: bytes) -> tuple[bytes, str] | None:
    """Re-encode to JPEG/PNG, drop metadata, cap size at 2400 px; None if not a usable image."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None
    if img.width < MIN_WIDTH // 2:
        return None
    img.thumbnail((2400, 2400))
    out = io.BytesIO()
    if img.mode in ("RGBA", "LA", "P"):
        img.convert("RGBA").save(out, format="PNG", optimize=True)
        return out.getvalue(), ".png"
    img.convert("RGB").save(out, format="JPEG", quality=86, optimize=True)
    return out.getvalue(), ".jpg"


async def resolve_image(
    block: ImageBlock,
    provider: ImageProvider,
    blobs: BlobStore,
    notes: list[str],
    *,
    used: set[str] | None = None,
    cache: dict[str, list] | None = None,
) -> bool:
    used = used if used is not None else set()
    cache = cache if cache is not None else {}
    try:
        if block.description not in cache:
            cache[block.description] = await provider.search(block.description, count=8)
        candidates = cache[block.description]
    except ResearchError as exc:
        notes.append(exc.message)
        return False
    # Most relevant first (query words in the title), then ~1800 px: sharp without huge originals.
    for c in sorted(
        candidates, key=lambda c: (-relevance(block.description, c.title), abs((c.width or 1600) - 1800))
    ):
        if (c.width and c.width < MIN_WIDTH) or c.url in used:
            continue
        try:
            raw = await provider.download(c)
        except ResearchError as exc:
            notes.append(exc.message)
            continue
        normalised = _normalise(raw)
        if normalised is None:
            continue
        ref = blobs.put_bytes(*normalised)
        block.asset_path, block.credit, block.source_url = ref.path, c.credit, c.landing_url
        used.add(c.url)
        return True
    notes.append(f"no suitable image found for '{block.description[:50]}'")
    return False


async def resolve_deck_images(
    deck: DeckPlan, provider: ImageProvider | None, blobs: BlobStore, *, limit: int
) -> list[str]:
    """Fill image blocks (title slide first, then image_text slides) up to ``limit`` images."""
    notes: list[str] = []
    if provider is None:
        return notes
    order = sorted(deck.slides, key=lambda s: 0 if s.archetype == SlideArchetype.title else 1)
    used = 0
    seen: set[str] = set()
    cache: dict[str, list] = {}
    for slide in order:
        for block in slide.blocks:
            wanted = isinstance(block, ImageBlock) and not block.asset_path and used < limit
            if wanted and await resolve_image(block, provider, blobs, notes, used=seen, cache=cache):
                used += 1
    return notes


async def resolve_document_images(
    plan: DocumentPlan, provider: ImageProvider | None, blobs: BlobStore, *, limit: int
) -> list[str]:
    notes: list[str] = []
    if provider is None:
        return notes
    used = 0
    for section in plan.all_sections():
        for block in section.blocks:
            wanted = isinstance(block, ImageBlock) and not block.asset_path and used < limit
            if wanted and await resolve_image(block, provider, blobs, notes):
                used += 1
    return notes
