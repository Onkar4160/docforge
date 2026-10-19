"""Fetch a web page and reduce it to readable text. Output is untrusted data, never instructions."""

from __future__ import annotations

import re

import httpx
from lxml import html as lxml_html

from docforge.core.errors import ResearchError

MAX_BYTES = 3 * 1024 * 1024
_DROP = ("script", "style", "noscript", "nav", "footer", "header", "form", "svg", "iframe")
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANKS = re.compile(r"\n{3,}")


def html_to_text(markup: str) -> tuple[str, str]:
    """Return (title, text) from HTML."""
    doc = lxml_html.fromstring(markup)
    for tag in _DROP:
        for node in list(doc.iter(tag)):
            node.drop_tree()
    title_nodes = doc.xpath("//title")
    title = title_nodes[0].text_content().strip() if title_nodes else ""
    bodies = doc.xpath("//body")
    if bodies:
        doc = bodies[0]
    for br in doc.iter("br"):
        br.tail = "\n" + (br.tail or "")
    for block in doc.iter("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"):
        block.tail = "\n" + (block.tail or "")
    text = _WS.sub(" ", doc.text_content())
    text = "\n".join(line.strip() for line in text.splitlines())
    return title, _BLANKS.sub("\n\n", text).strip()


async def fetch_text(
    url: str, *, client: httpx.AsyncClient | None = None, timeout: float = 30.0
) -> tuple[str, str]:
    if not url.startswith(("http://", "https://")):
        raise ResearchError(f"refusing to fetch non-http URL: {url}")
    own = client is None
    client = client or httpx.AsyncClient(
        timeout=timeout, follow_redirects=True, headers={"User-Agent": "DocForge research bot"}
    )
    try:
        async with client.stream("GET", url) as resp:
            if not resp.is_success:
                raise ResearchError(f"fetch {url} failed with {resp.status_code}")
            ctype = resp.headers.get("content-type", "")
            if "html" not in ctype and "text" not in ctype:
                raise ResearchError(f"unsupported content type {ctype or 'unknown'} at {url}")
            chunks: list[bytes] = []
            size = 0
            async for chunk in resp.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    break
                chunks.append(chunk)
            body = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        raise ResearchError(f"fetch {url} failed: {exc.__class__.__name__}") from exc
    finally:
        if own:
            await client.aclose()
    if "html" in ctype:
        return html_to_text(body)
    return "", body.strip()
