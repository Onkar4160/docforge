"""Research pipeline (Stage 5): plan → multi-source search → rank → read → extract → dossier.

Sources come from three places, all optional and all degrading gracefully:
web search (Tavily / dev fallback), scholarly indexes (OpenAlex, Semantic Scholar, arXiv), and the
user's own files (retrieved through the knowledge index). Every failure is recorded in ``dossier.notes``.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from docforge.agents.research import EvidenceExtractorAgent, ResearchPlannerAgent, SourceText
from docforge.core.config import Settings
from docforge.core.errors import DocForgeError
from docforge.core.ids import new_id
from docforge.core.logging import get_logger
from docforge.llm.base import LLMClient
from docforge.models.evidence import (
    Authority,
    Claim,
    ClaimStatus,
    Conflict,
    Coverage,
    EvidenceItem,
    Gap,
    ResearchDossier,
    ResearchPlan,
    ResearchQuestion,
    Source,
    SourceKind,
)
from docforge.models.intent import ResearchDepth
from docforge.research.fetch import fetch_text
from docforge.research.search import SearchProvider, SearchQuery, SearchResult
from docforge.retrieval.index import KnowledgeIndex

log = get_logger(__name__)


@dataclass(frozen=True)
class Budget:
    questions: int
    queries_per_question: int
    results_per_query: int
    sources: int
    fetches: int


BUDGETS = {
    ResearchDepth.light: Budget(3, 1, 4, 6, 2),
    ResearchDepth.standard: Budget(6, 2, 5, 12, 4),
    ResearchDepth.deep: Budget(10, 3, 6, 20, 8),
}
_HIGH_DOMAINS = (
    ".gov",
    ".gov.uk",
    ".edu",
    ".ac.uk",
    ".int",
    "europa.eu",
    "un.org",
    "who.int",
    "oecd.org",
    "worldbank.org",
    "imf.org",
    "iea.org",
    "nature.com",
    "science.org",
    "thelancet.com",
    "nejm.org",
    "nih.gov",
    "ieee.org",
    "acm.org",
    "springer.com",
    "wiley.com",
    "sciencedirect.com",
    "bmj.com",
    "cell.com",
    "pnas.org",
    "statista.com",
    "eurostat",
    "ons.gov.uk",
    "bls.gov",
    "census.gov",
)
_LOW_HINTS = ("blog", "medium.com", "substack", "reddit.com", "quora.com", "pinterest", "facebook.com")
_TEXT_LIMIT = 6000


def _norm_url(url: str) -> str:
    p = urlparse(url.lower())
    return f"{p.netloc.removeprefix('www.')}{p.path.rstrip('/')}"


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def authority_of(r: SearchResult) -> tuple[Authority, str]:
    host = (urlparse(r.url).hostname or "").lower()
    if r.kind == "paper":
        return Authority.high, f"peer-reviewed literature{f' ({r.venue})' if r.venue else ''}"
    if r.kind == "preprint":
        return Authority.medium, "preprint (not peer reviewed)"
    if any(host.endswith(d) or d in host for d in _HIGH_DOMAINS):
        return Authority.high, "official, academic or major research publisher domain"
    if any(h in host for h in _LOW_HINTS):
        return Authority.low, "user-generated or blog content"
    return Authority.medium, "general web source"


def _recency_bonus(date: str | None) -> float:
    match = re.match(r"(\d{4})", date or "")
    if not match:
        return 0.0
    age = datetime.now(UTC).year - int(match.group(1))
    return max(0.0, 0.15 - 0.03 * max(age, 0))


def rank_score(r: SearchResult, position: int) -> float:
    authority, _ = authority_of(r)
    base = r.score if r.score is not None else max(0.2, 1.0 - 0.1 * position)
    bonus = {Authority.high: 0.3, Authority.medium: 0.1, Authority.low: -0.2}[authority]
    citations = math.log10(1 + (r.citations or 0)) * 0.08
    has_text = 0.1 if (r.content or r.snippet) else -0.3
    return base + bonus + citations + _recency_bonus(r.published_date) + has_text


@dataclass
class UserSource:
    file_id: str
    filename: str
    text: str


class ResearchService:
    def __init__(
        self,
        settings: Settings,
        llm: LLMClient,
        *,
        web: SearchProvider | None,
        academic: list[SearchProvider],
        knowledge: KnowledgeIndex | None = None,
        fetcher=fetch_text,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.web = web
        self.academic = academic
        self.knowledge = knowledge
        self.fetcher = fetcher
        self._sem = asyncio.Semaphore(4)

    async def run(
        self,
        task_id: str,
        objective: str,
        *,
        deliverable: str,
        depth: ResearchDepth,
        namespace: str,
        user_sources: list[UserSource] | None = None,
    ) -> ResearchDossier:
        dossier = ResearchDossier(id=new_id("dossier"), task_id=task_id)
        if depth == ResearchDepth.none and not user_sources:
            dossier.skipped_reason = "research not needed for this request"
            return dossier
        budget = BUDGETS.get(depth, BUDGETS[ResearchDepth.light])
        plan = await ResearchPlannerAgent(self.llm).run(objective, deliverable, depth.value, budget.questions)
        dossier.plan = plan

        candidates = await self._search(plan, budget, dossier.notes)
        chosen = self._select(candidates, budget.sources)
        texts, sources = await self._read(chosen, budget, dossier.notes)
        user_texts, user_records = await self._user_sources(
            plan, namespace, user_sources or [], dossier.notes
        )
        texts += user_texts
        sources += user_records

        if not texts:
            dossier.notes.append("no usable sources were found")
            dossier.gaps = [
                Gap(question_id=q.id, description=f"No evidence found: {q.question}") for q in plan.questions
            ]
            dossier.coverage = Coverage(unanswered=len(plan.questions))
            dossier.performed = True
            return dossier

        evidence, conflicts = await self._extract(plan.questions, texts, dossier.notes)
        return self._assemble(dossier, plan, sources, evidence, conflicts)

    # ---------------------------------------------------------------- search

    def _providers_for(self, q: ResearchQuestion) -> list[tuple[SearchProvider, str]]:
        out: list[tuple[SearchProvider, str]] = []
        channels = set(q.channels or ["web"])
        if self.web is not None and channels & {"web", "news"}:
            out.append((self.web, "news" if "news" in channels and "web" not in channels else "general"))
        if "academic" in channels:
            out += [(p, "general") for p in self.academic]
        if not out and self.web is not None:
            out.append((self.web, "general"))
        if not out:
            out += [(p, "general") for p in self.academic]
        return out

    async def _search(
        self, plan: ResearchPlan, budget: Budget, notes: list[str]
    ) -> list[tuple[SearchResult, int]]:
        async def one(provider: SearchProvider, query: SearchQuery) -> list[tuple[SearchResult, int]]:
            async with self._sem:
                try:
                    results = await provider.search(query)
                except DocForgeError as exc:
                    msg = f"{provider.name}: {exc.message}"
                    if msg not in notes:
                        notes.append(msg)
                    return []
            for r in results:
                r.provider = r.provider or provider.name
            return [(r, i) for i, r in enumerate(results)]

        jobs = []
        for q in sorted(plan.questions, key=lambda q: q.priority):
            queries = (q.query_hints or [q.question])[: budget.queries_per_question]
            for text in queries:
                for provider, topic in self._providers_for(q):
                    jobs.append(
                        one(
                            provider,
                            SearchQuery(
                                query=text,
                                max_results=budget.results_per_query,
                                topic=topic,
                                include_domains=self.settings.research_allowed_domains,
                                exclude_domains=self.settings.research_blocked_domains,
                            ),
                        )
                    )
        batches = await asyncio.gather(*jobs)
        return [item for batch in batches for item in batch]

    @staticmethod
    def _select(candidates: list[tuple[SearchResult, int]], limit: int) -> list[SearchResult]:
        best: dict[str, tuple[float, SearchResult]] = {}
        title_keys: dict[str, str] = {}
        for r, position in candidates:
            key = (r.doi or "").lower() or _norm_url(r.url)
            tkey = _norm_title(r.title)
            if tkey and tkey in title_keys:  # same paper from two indexes
                key = title_keys[tkey]
            title_keys.setdefault(tkey, key)
            score = rank_score(r, position)
            if key not in best or score > best[key][0]:
                # keep the richer record when duplicates differ
                if key in best and not r.content and best[key][1].content:
                    continue
                best[key] = (score, r)
        ranked = sorted(best.values(), key=lambda pair: pair[0], reverse=True)
        # Keep diversity: at most 3 sources per domain.
        per_domain: dict[str, int] = {}
        chosen = []
        for _, r in ranked:
            host = urlparse(r.url).hostname or ""
            if per_domain.get(host, 0) >= 3 and r.kind == "web":
                continue
            per_domain[host] = per_domain.get(host, 0) + 1
            chosen.append(r)
            if len(chosen) >= limit:
                break
        return chosen

    # ---------------------------------------------------------------- reading

    async def _read(
        self, chosen: list[SearchResult], budget: Budget, notes: list[str]
    ) -> tuple[list[SourceText], list[Source]]:
        fetch_slots = budget.fetches

        async def content_for(r: SearchResult) -> str:
            nonlocal fetch_slots
            if r.content:
                return r.content
            if r.kind == "web" and fetch_slots > 0:
                fetch_slots -= 1
                try:
                    _, text = await self.fetcher(r.url)
                    return text
                except DocForgeError as exc:
                    notes.append(f"fetch failed: {exc.message}")
            return r.snippet

        bodies = await asyncio.gather(*(content_for(r) for r in chosen))
        texts, sources = [], []
        for i, (r, body) in enumerate(zip(chosen, bodies, strict=True), start=1):
            body = (body or "").strip()
            if len(body) < 80:
                continue
            sid = f"S{i}"
            authority, why = authority_of(r)
            origin = r.venue or (urlparse(r.url).hostname or "").removeprefix("www.")
            kind = SourceKind.web
            sources.append(
                Source(
                    id=sid,
                    kind=kind,
                    url=r.url,
                    title=r.title[:300],
                    publisher=origin,
                    author=", ".join(r.authors[:3]) + (" et al." if len(r.authors) > 3 else "") or None,
                    published_at=r.published_date,
                    authority=authority,
                    authority_rationale=why,
                    relevance=min(1.0, max(0.0, r.score if r.score is not None else 0.6)),
                    content_sha256=hashlib.sha256(body.encode()).hexdigest(),
                    excerpt=body[:400],
                    doi=r.doi,
                    venue=r.venue,
                    citations=r.citations,
                )
            )
            texts.append(
                SourceText(
                    sid,
                    r.title,
                    origin,
                    r.published_date,
                    body[:_TEXT_LIMIT],
                    r.kind if r.kind in ("paper", "preprint") else "web",
                )
            )
        return texts, sources

    async def _user_sources(
        self, plan: ResearchPlan, namespace: str, files: list[UserSource], notes: list[str]
    ) -> tuple[list[SourceText], list[Source]]:
        if not files:
            return [], []
        texts, sources = [], []
        for n, f in enumerate(files, start=1):
            sid = f"U{n}"
            body = f.text
            if self.knowledge is not None and len(body) > _TEXT_LIMIT:
                try:
                    await self.knowledge.index_document(namespace, sid, body, title=f.filename)
                    chunks = []
                    for q in plan.questions:
                        chunks += await self.knowledge.search(
                            namespace, q.question, top_k=2, source_ids=[sid]
                        )
                    seen = dict.fromkeys(c.text for c in sorted(chunks, key=lambda c: -c.score))
                    body = "\n\n".join(seen)[:_TEXT_LIMIT]
                except DocForgeError as exc:
                    notes.append(f"retrieval over {f.filename} failed: {exc.message}")
                    body = body[:_TEXT_LIMIT]
            sources.append(
                Source(
                    id=sid,
                    kind=SourceKind.user_file,
                    file_id=f.file_id,
                    title=f.filename,
                    publisher="user-provided file",
                    authority=Authority.high,
                    authority_rationale="supplied by the user",
                    relevance=1.0,
                    excerpt=body[:400],
                )
            )
            texts.append(
                SourceText(sid, f.filename, "user-provided file", None, body[:_TEXT_LIMIT], "user_file")
            )
        return texts, sources

    # ---------------------------------------------------------------- extraction + assembly

    async def _extract(self, questions, texts: list[SourceText], notes: list[str]):
        agent = EvidenceExtractorAgent(self.llm)
        batches = [texts[i : i + 4] for i in range(0, len(texts), 4)]
        sem = asyncio.Semaphore(3)

        async def one(batch):
            async with sem:
                try:
                    return await agent.run(questions, batch)
                except DocForgeError as exc:
                    notes.append(
                        f"evidence extraction failed for {', '.join(s.source_id for s in batch)}: "
                        f"{exc.message}"
                    )
                    return None

        results = [r for r in await asyncio.gather(*(one(b) for b in batches)) if r is not None]
        items = [i for r in results for i in r.items]
        conflicts = [c for r in results for c in r.conflicts]
        return items, conflicts

    @staticmethod
    def _assemble(dossier, plan, sources, items, conflicts) -> ResearchDossier:
        used = {i.source_id for i in items}
        sources = [s for s in sources if s.id in used]
        valid_q = {q.id for q in plan.questions}
        evidence, claims = [], []
        by_source: dict[str, list[str]] = {}
        for n, item in enumerate(items, start=1):
            eid, cid = f"e{n}", f"c{n}"
            evidence.append(
                EvidenceItem(
                    id=eid,
                    source_id=item.source_id,
                    kind=item.kind,
                    statement=item.statement,
                    value=item.value,
                    unit=item.unit,
                    as_of=item.as_of,
                    locator=item.locator,
                    question_ids=[q for q in item.question_ids if q in valid_q],
                    confidence=item.confidence,
                )
            )
            status = ClaimStatus.supported if item.kind != "opinion" else ClaimStatus.interpretation
            claims.append(Claim(id=cid, text=item.statement, evidence_ids=[eid], status=status))
            by_source.setdefault(item.source_id, []).append(eid)

        dossier.sources = sources
        dossier.evidence = evidence
        dossier.claims = claims
        dossier.conflicts = [
            Conflict(
                topic=c.topic,
                evidence_ids=[e for s in c.source_ids for e in by_source.get(s, [])][:6],
                description=c.description,
            )
            for c in conflicts
            if any(s in by_source for s in c.source_ids)
        ]
        coverage = Coverage()
        gaps = []
        for q in plan.questions:
            hits = [e for e in evidence if q.id in e.question_ids]
            strong = [e for e in hits if e.confidence >= 0.6]
            if len(strong) >= 2 or (strong and len({e.source_id for e in strong}) >= 1 and len(hits) >= 2):
                coverage.answered += 1
            elif hits:
                coverage.partial += 1
                gaps.append(Gap(question_id=q.id, description=f"Thin evidence: {q.question}"))
            else:
                coverage.unanswered += 1
                gaps.append(Gap(question_id=q.id, description=f"No evidence found: {q.question}"))
        dossier.coverage = coverage
        dossier.gaps = gaps
        dossier.performed = True
        return ResearchDossier.model_validate(dossier.model_dump())


def evidence_digest(dossier: ResearchDossier, *, max_claims: int = 70) -> str | None:
    """Compact, citable view of the dossier for planners: claims grouped by question."""
    if not dossier.performed or not dossier.claims:
        return None
    sources = {s.id: s for s in dossier.sources}
    evidence = {e.id: e for e in dossier.evidence}
    lines = []
    questions = dossier.plan.questions if dossier.plan else []
    emitted: set[str] = set()

    def claim_line(c: Claim) -> str:
        e = evidence[c.evidence_ids[0]]
        s = sources.get(e.source_id)
        figure = (
            f" [{e.value:g} {e.unit or ''}{', ' + e.as_of if e.as_of else ''}]".rstrip()
            if e.value is not None
            else ""
        )
        origin = f"{s.title[:90]} — {s.publisher or ''} {s.published_at or ''}".strip() if s else ""
        authority = s.authority.value if s else "?"
        return f"- [{c.id}] {c.text}{figure} (source {e.source_id}: {origin}; authority {authority})"

    for q in questions:
        group = [c for c in dossier.claims if q.id in evidence[c.evidence_ids[0]].question_ids][:12]
        if group:
            lines.append(f"Question {q.id}: {q.question}")
            for c in group:
                if c.id not in emitted and len(emitted) < max_claims:
                    lines.append(claim_line(c))
                    emitted.add(c.id)
    rest = [c for c in dossier.claims if c.id not in emitted][: max(0, max_claims - len(emitted))]
    if rest:
        lines.append("Other evidence:")
        lines += [claim_line(c) for c in rest]
    if dossier.conflicts:
        lines.append("Conflicting evidence (present both sides or the more authoritative one):")
        lines += [f"- {c.topic}: {c.description} ({', '.join(c.evidence_ids)})" for c in dossier.conflicts]
    if dossier.gaps:
        lines.append("Gaps (do not fill with invented facts; state the limitation if relevant):")
        lines += [f"- {g.description}" for g in dossier.gaps]
    return "\n".join(lines)
