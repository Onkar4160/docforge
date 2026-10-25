"""Scholarly search providers: OpenAlex, Semantic Scholar and arXiv (FR-RES-3, ADR-005).

All three return ``SearchResult`` with scholarly metadata so the pipeline can rank papers, preprints
and web pages together. Abstracts are the evidence text for papers.
"""

from __future__ import annotations

import re

import httpx
from defusedxml import ElementTree

from docforge.core.errors import ResearchError
from docforge.research.search import SearchProvider, SearchQuery, SearchResult

OPENALEX_URL = "https://api.openalex.org/works"
S2_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
ARXIV_URL = "https://export.arxiv.org/api/query"
_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"
_STOP = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "into",
    "what",
    "how",
    "why",
    "are",
    "does",
    "that",
    "this",
    "which",
}


async def _get(client: httpx.AsyncClient, provider: str, url: str, **kwargs) -> httpx.Response:
    try:
        resp = await client.get(url, **kwargs)
    except httpx.HTTPError as exc:
        raise ResearchError(f"{provider} request failed: {exc.__class__.__name__}") from exc
    if resp.status_code == 429:
        raise ResearchError(f"{provider} rate limit reached (add an API key to raise it)")
    if resp.status_code in (401, 403):
        raise ResearchError(f"{provider} rejected the request (check the API key)")
    if not resp.is_success:
        raise ResearchError(f"{provider} error {resp.status_code}")
    return resp


def _abstract_from_index(index: dict[str, list[int]] | None) -> str:
    """OpenAlex stores abstracts as an inverted index: word -> positions."""
    if not index:
        return ""
    positions = [(pos, word) for word, poss in index.items() for pos in poss]
    return " ".join(word for _, word in sorted(positions))


def _doi_url(doi: str | None) -> str | None:
    if not doi:
        return None
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    return f"https://doi.org/{doi}"


class OpenAlexProvider(SearchProvider):
    name = "openalex"
    authenticated = True

    def __init__(
        self,
        api_key: str | None = None,
        *,
        mailto: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._key = api_key
        self._mailto = mailto
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def search(self, q: SearchQuery) -> list[SearchResult]:
        params = {
            "search": q.query,
            "per_page": str(max(1, min(q.max_results, 25))),
            "filter": "has_abstract:true",
            "select": "id,doi,display_name,publication_year,publication_date,primary_location,authorships,"
            "cited_by_count,abstract_inverted_index,type",
        }
        if self._key:
            params["api_key"] = self._key
        if self._mailto:
            params["mailto"] = self._mailto
        data = (await _get(self._client, self.name, OPENALEX_URL, params=params)).json()
        out = []
        for w in data.get("results", []):
            loc = w.get("primary_location") or {}
            source = loc.get("source") or {}
            url = _doi_url(w.get("doi")) or loc.get("landing_page_url") or w.get("id")
            abstract = _abstract_from_index(w.get("abstract_inverted_index"))
            if not url or not w.get("display_name"):
                continue
            out.append(
                SearchResult(
                    title=w["display_name"],
                    url=url,
                    snippet=abstract[:400],
                    content=abstract or None,
                    published_date=w.get("publication_date")
                    or (str(w["publication_year"]) if w.get("publication_year") else None),
                    authors=[
                        a["author"]["display_name"]
                        for a in (w.get("authorships") or [])[:6]
                        if a.get("author", {}).get("display_name")
                    ],
                    venue=source.get("display_name"),
                    doi=w.get("doi"),
                    citations=w.get("cited_by_count"),
                    kind="preprint" if w.get("type") == "preprint" else "paper",
                    provider=self.name,
                )
            )
        return out

    async def aclose(self) -> None:
        await self._client.aclose()


class SemanticScholarProvider(SearchProvider):
    name = "semantic_scholar"
    authenticated = True

    FIELDS = "title,abstract,year,venue,authors,citationCount,url,externalIds,publicationDate,tldr"

    def __init__(
        self, api_key: str | None = None, *, client: httpx.AsyncClient | None = None, timeout: float = 30.0
    ) -> None:
        self._headers = {"x-api-key": api_key} if api_key else {}
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def search(self, q: SearchQuery) -> list[SearchResult]:
        params = {"query": q.query, "limit": str(max(1, min(q.max_results, 20))), "fields": self.FIELDS}
        data = (await _get(self._client, self.name, S2_URL, params=params, headers=self._headers)).json()
        out = []
        for p in data.get("data", []) or []:
            abstract = p.get("abstract") or ((p.get("tldr") or {}).get("text")) or ""
            doi = (p.get("externalIds") or {}).get("DOI")
            url = _doi_url(doi) or p.get("url")
            if not url or not p.get("title") or not abstract:
                continue
            out.append(
                SearchResult(
                    title=p["title"],
                    url=url,
                    snippet=abstract[:400],
                    content=abstract,
                    published_date=p.get("publicationDate") or (str(p["year"]) if p.get("year") else None),
                    authors=[a["name"] for a in (p.get("authors") or [])[:6] if a.get("name")],
                    venue=p.get("venue") or None,
                    doi=doi,
                    citations=p.get("citationCount"),
                    kind="paper",
                    provider=self.name,
                )
            )
        return out

    async def aclose(self) -> None:
        await self._client.aclose()


def arxiv_query(text: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z0-9\-]+", text.lower()) if len(w) > 3 and w not in _STOP]
    return " AND ".join(f"all:{w}" for w in words[:5]) or f"all:{text}"


class ArxivProvider(SearchProvider):
    name = "arxiv"
    authenticated = True  # public API, no key needed

    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float = 30.0) -> None:
        self._client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    async def search(self, q: SearchQuery) -> list[SearchResult]:
        params = {
            "search_query": arxiv_query(q.query),
            "start": "0",
            "max_results": str(max(1, min(q.max_results, 20))),
            "sortBy": "relevance",
        }
        resp = await _get(self._client, self.name, ARXIV_URL, params=params)
        try:
            root = ElementTree.fromstring(resp.content)
        except ElementTree.ParseError as exc:
            raise ResearchError("arxiv returned malformed XML") from exc
        out = []
        for entry in root.findall(f"{_ATOM}entry"):
            title = " ".join((entry.findtext(f"{_ATOM}title") or "").split())
            summary = " ".join((entry.findtext(f"{_ATOM}summary") or "").split())
            url = entry.findtext(f"{_ATOM}id") or ""
            if not title or not url:
                continue
            doi = entry.findtext(f"{_ARXIV_NS}doi")
            journal = entry.findtext(f"{_ARXIV_NS}journal_ref")
            out.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=summary[:400],
                    content=summary,
                    published_date=(entry.findtext(f"{_ATOM}published") or "")[:10] or None,
                    authors=[a.findtext(f"{_ATOM}name") or "" for a in entry.findall(f"{_ATOM}author")][:6],
                    venue=journal[:100] if journal else "arXiv",
                    doi=doi,
                    kind="paper" if journal else "preprint",
                    provider=self.name,
                )
            )
        return out

    async def aclose(self) -> None:
        await self._client.aclose()


def build_academic_providers(settings) -> list[SearchProvider]:
    """Configured scholarly indexes; each works without a key at a lower provider-imposed rate."""
    factories = {
        "openalex": lambda: OpenAlexProvider(
            settings.openalex_api_key, mailto=settings.research_contact_email
        ),
        "semantic_scholar": lambda: SemanticScholarProvider(settings.semantic_scholar_api_key),
        "arxiv": lambda: ArxivProvider(),
    }
    return [factories[name]() for name in settings.academic_sources if name in factories]
