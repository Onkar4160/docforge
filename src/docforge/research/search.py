"""Web search providers behind one interface (ADR-005).

Default is Tavily (authenticated). When ``REQUIRE_AUTHENTICATED_WEB_SEARCH=false`` and no Tavily key
is configured, a keyless DuckDuckGo HTML provider is used for development only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from lxml import html as lxml_html

from docforge.core.config import Settings
from docforge.core.errors import ResearchError
from docforge.core.logging import get_logger

log = get_logger(__name__)

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
DDG_HTML_URL = "https://html.duckduckgo.com/html/"


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    content: str | None = None  # full page text when the provider returns it
    score: float | None = None
    published_date: str | None = None
    # Scholarly metadata (filled by academic providers)
    authors: list[str] = field(default_factory=list)
    venue: str | None = None
    doi: str | None = None
    citations: int | None = None
    kind: str = "web"  # web | paper | preprint
    provider: str = ""


@dataclass
class SearchQuery:
    query: str
    max_results: int = 6
    include_domains: list[str] = field(default_factory=list)
    exclude_domains: list[str] = field(default_factory=list)
    topic: str = "general"  # general | news | finance
    time_range: str | None = None  # day | week | month | year
    include_content: bool = True


class SearchProvider(ABC):
    name: str
    authenticated: bool = False

    @abstractmethod
    async def search(self, q: SearchQuery) -> list[SearchResult]: ...

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        pass


def _domain_allowed(url: str, include: list[str], exclude: list[str]) -> bool:
    host = (urlparse(url).hostname or "").lower()

    def matches(domain: str) -> bool:
        domain = domain.lower().lstrip(".")
        return host == domain or host.endswith(f".{domain}")

    if include and not any(matches(d) for d in include):
        return False
    return not any(matches(d) for d in exclude)


class TavilySearchProvider(SearchProvider):
    name = "tavily"
    authenticated = True

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
        depth: str = "advanced",
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._depth = depth

    async def search(self, q: SearchQuery) -> list[SearchResult]:
        body: dict = {
            "query": q.query,
            "search_depth": self._depth,
            "max_results": max(1, min(q.max_results, 20)),
            "topic": q.topic,
            "include_raw_content": "text" if q.include_content else False,
            "include_answer": False,
            "include_domains": q.include_domains,
            "exclude_domains": q.exclude_domains,
            "include_published_date": True,
        }
        if q.time_range:
            body["time_range"] = q.time_range
        try:
            resp = await self._client.post(TAVILY_SEARCH_URL, json=body, headers=self._headers)
        except httpx.HTTPError as exc:
            raise ResearchError(f"tavily request failed: {exc.__class__.__name__}") from exc
        if resp.status_code in (401, 403):
            raise ResearchError("tavily rejected the API key (TAVILY_API_KEY)")
        if resp.status_code == 429:
            raise ResearchError("tavily rate limit or credit limit reached")
        if not resp.is_success:
            raise ResearchError(f"tavily error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        return [
            SearchResult(
                title=r.get("title") or r.get("url", ""),
                url=r["url"],
                snippet=r.get("content") or "",
                content=r.get("raw_content") or None,
                score=r.get("score"),
                published_date=r.get("published_date"),
            )
            for r in data.get("results", [])
            if r.get("url")
        ]

    async def aclose(self) -> None:
        await self._client.aclose()


class DuckDuckGoHtmlProvider(SearchProvider):
    """Keyless development fallback. Scrapes the HTML endpoint; best-effort, no page content."""

    name = "duckduckgo_html"

    def __init__(self, *, timeout: float = 30.0, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (DocForge research; development mode)"}
        )

    @staticmethod
    def _real_url(href: str) -> str:
        if href.startswith("//"):
            href = f"https:{href}"
        parsed = urlparse(href)
        if parsed.hostname and parsed.hostname.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            return unquote(target)
        return href

    async def search(self, q: SearchQuery) -> list[SearchResult]:
        try:
            resp = await self._client.post(DDG_HTML_URL, data={"q": q.query})
        except httpx.HTTPError as exc:
            raise ResearchError(f"duckduckgo request failed: {exc.__class__.__name__}") from exc
        if not resp.is_success:
            raise ResearchError(f"duckduckgo error {resp.status_code}")
        doc = lxml_html.fromstring(resp.text)
        results: list[SearchResult] = []
        for node in doc.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " result ")]'):
            links = node.xpath('.//a[contains(@class, "result__a")]')
            if not links:
                continue
            url = self._real_url(links[0].get("href", ""))
            if not url.startswith("http") or not _domain_allowed(url, q.include_domains, q.exclude_domains):
                continue
            snippet_nodes = node.xpath('.//*[contains(@class, "result__snippet")]')
            results.append(
                SearchResult(
                    title=links[0].text_content().strip(),
                    url=url,
                    snippet=snippet_nodes[0].text_content().strip() if snippet_nodes else "",
                )
            )
            if len(results) >= q.max_results:
                break
        return results

    async def aclose(self) -> None:
        await self._client.aclose()


class UnavailableSearchProvider(SearchProvider):
    """Configured when authenticated search is required but no key exists; fails with a clear reason."""

    name = "unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    async def search(self, q: SearchQuery) -> list[SearchResult]:
        raise ResearchError(self.reason)


class FixtureSearchProvider(SearchProvider):
    """Offline provider for tests: maps query substrings to canned results."""

    name = "fixture"

    def __init__(self, results: dict[str, list[SearchResult]]) -> None:
        self.results = results
        self.queries: list[SearchQuery] = []

    async def search(self, q: SearchQuery) -> list[SearchResult]:
        self.queries.append(q)
        hits: list[SearchResult] = []
        for key, items in self.results.items():
            if key.lower() in q.query.lower():
                hits.extend(i for i in items if _domain_allowed(i.url, q.include_domains, q.exclude_domains))
        return hits[: q.max_results]


def build_search_provider(settings: Settings) -> SearchProvider:
    if settings.tavily_api_key:
        return TavilySearchProvider(settings.tavily_api_key)
    if settings.require_authenticated_web_search:
        return UnavailableSearchProvider(
            "web research requires TAVILY_API_KEY (REQUIRE_AUTHENTICATED_WEB_SEARCH=true)"
        )
    log.warning("TAVILY_API_KEY not set; using keyless DuckDuckGo fallback (development only)")
    return DuckDuckGoHtmlProvider()
