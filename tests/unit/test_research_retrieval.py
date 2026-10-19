from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

from docforge.core.errors import ResearchError, StorageError
from docforge.llm.providers import HashingEmbeddingProvider
from docforge.research.fetch import fetch_text, html_to_text
from docforge.research.search import (
    DuckDuckGoHtmlProvider,
    FixtureSearchProvider,
    SearchQuery,
    SearchResult,
    TavilySearchProvider,
    UnavailableSearchProvider,
    build_search_provider,
)
from docforge.retrieval.index import KnowledgeIndex, chunk_text
from docforge.retrieval.vectorstore import LocalVectorStore, PineconeVectorStore, VectorRecord
from docforge.storage import init_db, make_engine
from docforge.template.external import run_pptx_masters
from tests.conftest import make_settings

pytestmark = pytest.mark.anyio


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- search providers (FR-RES-3, ADR-005)


def test_provider_selection_rules(tmp_path: Path):
    assert isinstance(
        build_search_provider(make_settings(tmp_path, tavily_api_key="tvly-1")), TavilySearchProvider
    )
    strict = build_search_provider(make_settings(tmp_path, require_authenticated_web_search=True))
    assert isinstance(strict, UnavailableSearchProvider)
    dev = build_search_provider(make_settings(tmp_path, require_authenticated_web_search=False))
    assert isinstance(dev, DuckDuckGoHtmlProvider)


async def test_unavailable_provider_explains_itself():
    with pytest.raises(ResearchError, match="TAVILY_API_KEY"):
        await UnavailableSearchProvider("web research requires TAVILY_API_KEY").search(SearchQuery("x"))


async def test_tavily_request_and_mapping():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "IEA report",
                        "url": "https://iea.org/r",
                        "content": "snippet",
                        "score": 0.9,
                        "raw_content": "full text",
                        "published_date": "2026-03-01",
                    },
                    {"title": "no url"},
                ]
            },
        )

    provider = TavilySearchProvider("tvly-abc", client=_client(handler))
    results = await provider.search(
        SearchQuery("ev charging", max_results=50, exclude_domains=["spam.com"], time_range="year")
    )
    assert results == [
        SearchResult("IEA report", "https://iea.org/r", "snippet", "full text", 0.9, "2026-03-01")
    ]
    body = json.loads(seen[0].content)
    assert seen[0].headers["authorization"] == "Bearer tvly-abc"
    assert body["max_results"] == 20 and body["exclude_domains"] == ["spam.com"]
    assert body["include_raw_content"] == "text" and body["time_range"] == "year"


async def test_tavily_errors():
    for status, match in [(401, "API key"), (429, "rate limit"), (500, "error 500")]:
        provider = TavilySearchProvider("k", client=_client(lambda r, s=status: httpx.Response(s, text="x")))
        with pytest.raises(ResearchError, match=match):
            await provider.search(SearchQuery("q"))


async def test_duckduckgo_parses_results_and_filters_domains():
    page = """<html><body>
      <div class="result results_links"><h2><a class="result__a"
        href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.who.int%2Fnews&amp;rut=x">WHO news</a></h2>
        <a class="result__snippet">Microplastics in water</a></div>
      <div class="result"><a class="result__a" href="https://blocked.example/a">Blocked</a></div>
    </body></html>"""
    provider = DuckDuckGoHtmlProvider(client=_client(lambda r: httpx.Response(200, text=page)))
    results = await provider.search(SearchQuery("microplastics", exclude_domains=["blocked.example"]))
    assert [(r.title, r.url, r.snippet) for r in results] == [
        ("WHO news", "https://www.who.int/news", "Microplastics in water")
    ]


async def test_fixture_provider_matches_substrings():
    p = FixtureSearchProvider(
        {"solar": [SearchResult("A", "https://a.org/x"), SearchResult("B", "https://b.com/y")]}
    )
    assert [r.title for r in await p.search(SearchQuery("solar costs", include_domains=["a.org"]))] == ["A"]
    assert await p.search(SearchQuery("wind")) == []


def test_html_to_text_strips_noise():
    title, text = html_to_text(
        "<html><head><title> T </title><script>evil()</script></head>"
        "<body><nav>menu</nav><h1>Head</h1><p>One <b>two</b></p><p>Three</p></body></html>"
    )
    assert title == "T"
    assert "evil" not in text and "menu" not in text
    assert text.splitlines()[0] == "Head" and "One two" in text and "Three" in text


async def test_fetch_text_rejects_non_http_and_binary():
    with pytest.raises(ResearchError, match="non-http"):
        await fetch_text("file:///etc/passwd")
    client = _client(
        lambda r: httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})
    )
    with pytest.raises(ResearchError, match="unsupported content type"):
        await fetch_text("https://x.org/a.pdf", client=client)
    client = _client(
        lambda r: httpx.Response(200, text="<p>hello</p>", headers={"content-type": "text/html"})
    )
    assert (await fetch_text("https://x.org", client=client))[1] == "hello"


# ---------------------------------------------------------------- retrieval (FR-RES-4, ADR-014)


def test_chunk_text_respects_limits_and_overlap():
    text = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
    chunks = chunk_text(text, max_chars=500, overlap=50)
    assert len(chunks) > 3 and all(len(c) <= 560 for c in chunks)
    assert chunk_text("x" * 1200, max_chars=500, overlap=100)[0] == "x" * 500
    assert chunk_text("   ") == []


@pytest.fixture
def local_store(tmp_path: Path) -> LocalVectorStore:
    engine = make_engine(f"sqlite:///{(tmp_path / 'v.db').as_posix()}")
    return LocalVectorStore(init_db(engine))


async def test_local_store_query_filter_delete(local_store: LocalVectorStore):
    await local_store.upsert(
        "ns",
        [
            VectorRecord("a", [1.0, 0.0], {"source_id": "s1"}),
            VectorRecord("b", [0.0, 1.0], {"source_id": "s2"}),
            VectorRecord("c", [0.7, 0.7], {"source_id": "s1"}),
        ],
    )
    await local_store.upsert("other", [VectorRecord("z", [1.0, 0.0])])
    hits = await local_store.query("ns", [1.0, 0.1], top_k=2)
    assert [h.id for h in hits] == ["a", "c"]
    only_s2 = await local_store.query("ns", [1.0, 0.0], filter={"source_id": {"$in": ["s2"]}})
    assert [h.id for h in only_s2] == ["b"]
    await local_store.delete("ns", ["a"])
    assert {h.id for h in await local_store.query("ns", [1.0, 0.0])} == {"b", "c"}
    await local_store.delete("ns")
    assert await local_store.query("ns", [1.0, 0.0]) == []
    assert len(await local_store.query("other", [1.0, 0.0])) == 1


async def test_pinecone_rest_calls():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "api.pinecone.io":
            return httpx.Response(200, json={"host": "idx-abc.svc.pinecone.io", "status": {"ready": True}})
        if request.url.path == "/vectors/upsert":
            return httpx.Response(200, json={"upsertedCount": len(json.loads(request.content)["vectors"])})
        if request.url.path == "/query":
            return httpx.Response(
                200, json={"matches": [{"id": "a", "score": 0.9, "metadata": {"text": "t"}}]}
            )
        return httpx.Response(200, json={})

    store = PineconeVectorStore("pc-key", "doc-chatbot", api_version="2026-07", client=_client(handler))
    assert await store.upsert("ns", [VectorRecord(str(i), [0.1, 0.2]) for i in range(150)]) == 150
    hits = await store.query("ns", [0.1, 0.2], top_k=3, filter={"source_id": {"$in": ["s1"]}})
    assert hits[0].id == "a" and hits[0].metadata == {"text": "t"}
    await store.delete("ns")

    assert seen[0].url.path == "/indexes/doc-chatbot"
    assert all(
        r.headers["api-key"] == "pc-key" and r.headers["x-pinecone-api-version"] == "2026-07" for r in seen
    )
    assert [r.url.path for r in seen[1:]] == [
        "/vectors/upsert",
        "/vectors/upsert",
        "/query",
        "/vectors/delete",
    ]
    assert seen[1].url.host == "idx-abc.svc.pinecone.io"
    query_body = json.loads(seen[3].content)
    assert query_body["topK"] == 3 and query_body["includeMetadata"] is True and "filter" in query_body
    assert json.loads(seen[4].content) == {"namespace": "ns", "deleteAll": True}


async def test_pinecone_missing_index_is_clear():
    store = PineconeVectorStore(
        "k", "nope", api_version="2026-07", client=_client(lambda r: httpx.Response(404))
    )
    with pytest.raises(StorageError, match="PINECONE_INDEX"):
        await store.query("ns", [0.1])


async def test_knowledge_index_roundtrip(local_store: LocalVectorStore):
    index = KnowledgeIndex(HashingEmbeddingProvider(256), local_store)
    n = await index.index_document(
        "ses_1", "src_a", "Solar module prices fell sharply in 2025.\n\nWind is steady."
    )
    await index.index_document("ses_1", "src_b", "Medieval poetry uses alliteration and kennings.")
    assert n == 1
    hits = await index.search("ses_1", "solar module prices", top_k=1)
    assert hits[0].source_id == "src_a" and "Solar" in hits[0].text
    scoped = await index.search("ses_1", "solar module prices", source_ids=["src_b"])
    assert {h.source_id for h in scoped} == {"src_b"}


# ---------------------------------------------------------------- optional pptx-masters hook


def test_pptx_masters_disabled_and_missing(tmp_path: Path):
    assert run_pptx_masters(make_settings(tmp_path), tmp_path / "t.pptx", tmp_path / "o").status == "disabled"
    s = make_settings(
        tmp_path, pptx_masters_enabled=True, pptx_masters_command="definitely-not-installed-xyz"
    )
    assert run_pptx_masters(s, tmp_path / "t.pptx", tmp_path / "o").status == "not_installed"


def test_pptx_masters_collects_output_files(tmp_path: Path):
    script = tmp_path / "fake_masters.py"
    script.write_text(
        "import sys, pathlib\n"
        "out = pathlib.Path(sys.argv[3]); out.mkdir(parents=True, exist_ok=True)\n"
        "(out / 'guide.md').write_text('# Guide for ' + pathlib.Path(sys.argv[1]).name)\n"
    )
    s = make_settings(
        tmp_path,
        pptx_masters_enabled=True,
        pptx_masters_command=sys.executable,
        pptx_masters_args=f'"{script.as_posix()}" "{{input}}" --output "{{output_dir}}"',
    )
    guide = run_pptx_masters(s, tmp_path / "My Template.pptx", tmp_path / "out dir")
    assert guide.status == "ok", guide.detail
    assert guide.files == {"guide.md": "# Guide for My Template.pptx"}


def test_pptx_masters_failure_reported(tmp_path: Path):
    s = make_settings(
        tmp_path,
        pptx_masters_enabled=True,
        pptx_masters_command=sys.executable,
        pptx_masters_args='-c "import sys; sys.exit(3)"',
    )
    assert run_pptx_masters(s, tmp_path / "t.pptx", tmp_path / "o").status == "failed"
