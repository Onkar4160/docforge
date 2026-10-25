"""Research agents: plan the questions, then extract atomic evidence from sources (Stage 5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from docforge.agents.base import UNTRUSTED_NOTE, Agent, tagged
from docforge.models.base import DFModel
from docforge.models.evidence import EvidenceKind, ResearchPlan, ResearchQuestion

PLANNER_SYSTEM = f"""You plan research for a professional deliverable (presentation, report or workbook).
Break the objective into the specific questions the deliverable must answer with evidence: market size and \
growth, causes, comparisons, risks, recent developments, definitions, figures that charts will need.

For each question:
- id: q1, q2, ... ; priority 1 = essential, 2 = important, 3 = nice to have.
- query_hints: 1-3 concise search-engine queries (keywords, not sentences; add a year for \
time-sensitive facts).
- channels: "academic" for scientific, medical, technical or empirical questions answered by papers; "news" \
for recent events; "web" for official statistics, industry and government sources. Several are allowed.
Ask for what the deliverable needs, no more. {UNTRUSTED_NOTE}"""

EXTRACTOR_SYSTEM = f"""You extract evidence from sources for a research dossier.
For each source, record atomic, verifiable items that help answer the research questions:
- statement: one self-contained sentence in your own words, faithful to the source; keep figures exact.
- kind: fact, figure (a number), finding (a study result), quote (verbatim, short), definition, opinion.
- value/unit/as_of for figures (e.g. 9.4, "EUR bn", "2025").
- locator: where in the source (page, section, "abstract").
- question_ids: which questions it helps answer. confidence: how directly the source supports the statement.
Rules: only use what the source text says; never add outside knowledge; skip marketing fluff; prefer recent \
and specific data; at most 6 items per source. Report conflicts between sources in this batch.
{UNTRUSTED_NOTE}"""


class PlannedResearch(DFModel):
    questions: list[ResearchQuestion] = Field(min_length=1, max_length=12)


class ExtractedItem(DFModel):
    source_id: str
    kind: EvidenceKind
    statement: str
    value: float | None = None
    unit: str | None = None
    as_of: str | None = None
    locator: str = ""
    question_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(0.7, ge=0, le=1)


class ExtractedConflict(DFModel):
    topic: str
    source_ids: list[str]
    description: str


class Extraction(DFModel):
    items: list[ExtractedItem] = Field(default_factory=list)
    conflicts: list[ExtractedConflict] = Field(default_factory=list)


@dataclass
class SourceText:
    source_id: str
    title: str
    origin: str  # publisher / venue / domain
    date: str | None
    text: str
    kind: Literal["web", "paper", "preprint", "user_file"]


class ResearchPlannerAgent(Agent[PlannedResearch]):
    name = "research_planner"
    output_type = PlannedResearch
    system_prompt = PLANNER_SYSTEM

    async def run(self, objective: str, deliverable: str, depth: str, max_questions: int) -> ResearchPlan:
        prompt = (
            f"<objective>\n{objective}\n</objective>\nDeliverable: {deliverable}\nResearch depth: {depth}\n"
            f"Plan at most {max_questions} questions."
        )
        result = await self.ask(prompt, temperature=0.2)
        questions = result.parsed.questions[:max_questions]
        for i, q in enumerate(questions, start=1):
            q.id = f"q{i}"
        return ResearchPlan(depth=depth, questions=questions)


class EvidenceExtractorAgent(Agent[Extraction]):
    name = "evidence_extractor"
    output_type = Extraction
    system_prompt = EXTRACTOR_SYSTEM

    async def run(self, questions: list[ResearchQuestion], sources: list[SourceText]) -> Extraction:
        qs = "\n".join(f"{q.id}: {q.question}" for q in questions)
        tag = {"user_file": "user_file", "web": "web"}
        body = "\n\n".join(
            tagged(
                tag.get(s.kind, "source"),
                s.text,
                id=s.source_id,
                title=s.title.replace('"', "'"),
                origin=(s.origin or "").replace('"', "'"),
                date=s.date or "unknown",
                type=s.kind,
            )
            for s in sources
        )
        result = await self.ask(f"<questions>\n{qs}\n</questions>\n\n{body}", temperature=0.1)
        extraction = result.parsed
        known = {s.source_id for s in sources}
        extraction.items = [i for i in extraction.items if i.source_id in known and i.statement.strip()]
        return extraction
