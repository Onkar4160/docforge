"""Document agents (Stage 7/9): an outliner plans the argument, section writers draft in parallel.

Splitting outline and writing keeps long reports deep and coherent without hitting output limits,
and lets one section be rewritten later without touching the rest (ADR-003).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from docforge.agents.base import UNTRUSTED_NOTE, Agent
from docforge.models.base import DFModel
from docforge.models.intent import LengthUnit, OutputSpec
from docforge.models.ir import Block, DocumentPlan, FrontMatter, ParagraphBlock, SectionPlan

WORDS_PER_PAGE = 450

OUTLINER_SYSTEM = f"""You are a senior analyst and editor. You design the structure of professional documents \
(reports, proposals, memos, papers, briefs, manuals) before they are written.

Produce an outline whose sections form one coherent argument:
- Typical report: introduction/context -> analysis sections (each answering one question) -> implications or \
recommendations -> conclusion. Papers: introduction, background/literature, method or approach, findings, \
discussion, conclusion. Memos and briefs are short and lead with the recommendation.
- Each section: a specific heading (not generic like "Analysis"), its purpose, 3-6 key points it must make, \
target_words, and subsections only where a section exceeds ~700 words.
- executive_summary: 4-6 sentences stating the main findings and recommendation (omit for memos < 2 pages).
- Distribute target_words so the total matches the requested length. Do not pad.
- Ground key points in the provided evidence (mention claim ids like c4 next to points that use them). Do not \
invent statistics; if evidence is missing, plan qualitative reasoning or state the limitation.
When template guidance is supplied, keep the outline compatible with its observed heading hierarchy and page
structure. Do not invent style IDs or copy sample document content.
{UNTRUSTED_NOTE}"""

WRITER_SYSTEM = f"""You write one section of a professional document, as structured content blocks.
Write substantive, specific prose: paragraphs of 80-180 words that explain, compare and conclude, not lists of \
fragments. Use a bullets block only for genuinely list-like content, a table block for structured comparisons \
or figures, a chart block only for numeric evidence (equal-length categories and values), a quote block only \
for a verbatim quote from evidence, a callout block for one key takeaway, and at most one image block per \
section when a real photograph helps (description = concrete photographable subject; alt_text describes it).
Every block object includes its "type" field.
Evidence rules: every sentence that uses a fact or figure must be backed by claim ids from the evidence, placed \
in claim_ids of that paragraph, bullet item, table or chart. Use the exact figures and units. Never cite ids \
that are not in the evidence; never invent statistics, studies or quotes. Where evidence is thin, say so plainly.
Stay within the section's purpose; do not repeat what other sections cover; do not write the heading itself.
Match the requested tone and audience. Aim for the target word count (+-15%).
When template guidance is supplied, preserve its named heading/body styles and page structure; do not invent style IDs or overwrite headers, footers, or page setup. The renderer applies those styles.
{UNTRUSTED_NOTE}"""


class OutlineSubsection(DFModel):
    heading: str
    purpose: str = ""
    key_points: list[str] = Field(default_factory=list)
    target_words: int = Field(300, ge=60, le=3000)


class OutlineSection(DFModel):
    heading: str
    purpose: str = ""
    key_points: list[str] = Field(default_factory=list)
    target_words: int = Field(500, ge=80, le=6000)
    subsections: list[OutlineSubsection] = Field(default_factory=list)


class DocumentOutline(DFModel):
    title: str
    subtitle: str | None = None
    doc_type: Literal["report", "memo", "proposal", "paper", "brief", "manual"] = "report"
    audience: str = ""
    executive_summary: list[str] = Field(default_factory=list)
    include_toc: bool = True
    sections: list[OutlineSection] = Field(min_length=1)


class WrittenSubsection(DFModel):
    heading: str
    blocks: list[Block] = Field(default_factory=list)


class WrittenSection(DFModel):
    blocks: list[Block] = Field(default_factory=list, description="Content before the first subsection")
    subsections: list[WrittenSubsection] = Field(default_factory=list)


@dataclass
class DocumentInput:
    objective: str
    spec: OutputSpec
    evidence_digest: str | None = None
    template_summary: str | None = None


def target_words(spec: OutputSpec) -> int:
    length = spec.length
    if length.explicit and length.target:
        if length.unit == LengthUnit.pages:
            return length.target * WORDS_PER_PAGE
        if length.unit == LengthUnit.words:
            return length.target
    return {"brief": 1200, "standard": 2800, "detailed": 5000}[spec.detail_level.value]


def _requirements(inp: DocumentInput) -> str:
    spec = inp.spec
    evidence = inp.evidence_digest or "No researched evidence is available."
    prompt = (
        f"<objective>\n{inp.objective}\n</objective>\n\n<requirements>\nPurpose: {spec.purpose or 'see objective'}\n"
        f"Audience: {spec.audience}\nTone: {spec.tone}\nLanguage: {spec.language}\n"
        f"Total length: about {target_words(spec)} words\nCitation style: {spec.citation_style.value}\n"
        + (f"Style notes: {'; '.join(spec.style_notes)}\n" if spec.style_notes else "")
        + f"</requirements>\n\n<evidence>\n{evidence}\n</evidence>"
    )
    if inp.template_summary:
        prompt += f"\n\n<template_guidance>\n{inp.template_summary}\n</template_guidance>"
    return prompt


def _outline_text(outline: DocumentOutline) -> str:
    lines = [f"Title: {outline.title}"]
    for i, s in enumerate(outline.sections, 1):
        lines.append(f"{i}. {s.heading} — {s.purpose}")
        lines += [f"   {i}.{j}. {sub.heading}" for j, sub in enumerate(s.subsections, 1)]
    return "\n".join(lines)


class DocumentOutlinerAgent(Agent[DocumentOutline]):
    name = "doc_outliner"
    output_type = DocumentOutline
    system_prompt = OUTLINER_SYSTEM

    async def run(self, inp: DocumentInput) -> DocumentOutline:
        result = await self.ask(_requirements(inp), temperature=0.3)
        return result.parsed


class SectionWriterAgent(Agent[WrittenSection]):
    name = "section_writer"
    output_type = WrittenSection
    system_prompt = WRITER_SYSTEM

    async def run(self, inp: DocumentInput, outline: DocumentOutline, index: int) -> WrittenSection:
        section = outline.sections[index]
        subs = "\n".join(
            f"- {s.heading}: {s.purpose} | points: {'; '.join(s.key_points)} | ~{s.target_words} words"
            for s in section.subsections
        )
        prompt = (
            f"{_requirements(inp)}\n\n<document_outline>\n{_outline_text(outline)}\n</document_outline>\n\n"
            f"<section_to_write>\nHeading: {section.heading}\nPurpose: {section.purpose}\n"
            f"Key points: {'; '.join(section.key_points)}\nTarget words: {section.target_words}\n"
            + (
                f"Write exactly these subsections, in order, with these headings:\n{subs}\n"
                if subs
                else "Write it without subsections.\n"
            )
            + "</section_to_write>"
        )
        return (await self.ask(prompt, temperature=0.4)).parsed


def assemble(outline: DocumentOutline, written: list[WrittenSection]) -> DocumentPlan:
    """Outline + drafted sections -> DocumentPlan with code-owned unit IDs."""
    sections = []
    for i, (o, w) in enumerate(zip(outline.sections, written, strict=True), start=1):
        planned = o.subsections
        subs = [
            SectionPlan(
                id=f"sec-{i}-{j}",
                heading=ws.heading.strip() or (planned[j - 1].heading if j <= len(planned) else f"Part {j}"),
                level=2,
                purpose=planned[j - 1].purpose if j <= len(planned) else "",
                blocks=ws.blocks,
            )
            for j, ws in enumerate(w.subsections, start=1)
        ]
        sections.append(
            SectionPlan(
                id=f"sec-{i}",
                heading=o.heading.strip(),
                level=1,
                purpose=o.purpose,
                blocks=w.blocks,
                subsections=subs,
            )
        )
    summary = [ParagraphBlock(text=" ".join(outline.executive_summary))] if outline.executive_summary else []
    return DocumentPlan(
        title=outline.title,
        subtitle=outline.subtitle,
        doc_type=outline.doc_type,
        front_matter=FrontMatter(executive_summary=summary, include_toc=outline.include_toc),
        sections=sections,
    )


async def write_document(llm, inp: DocumentInput, *, concurrency: int = 4) -> DocumentPlan:
    outline = await DocumentOutlinerAgent(llm).run(inp)
    writer = SectionWriterAgent(llm)
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int) -> WrittenSection:
        async with sem:
            return await writer.run(inp, outline, i)

    written = await asyncio.gather(*(one(i) for i in range(len(outline.sections))))
    return assemble(outline, list(written))
