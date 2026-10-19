"""DeckPlannerAgent: objective + spec (+ evidence later) → DeckPlan (Stage 7, FR-PLAN-1/2/5/7)."""

from __future__ import annotations

from dataclasses import dataclass, field

from docforge.agents.base import UNTRUSTED_NOTE, Agent
from docforge.design.system import palette_names
from docforge.llm.base import ChatMessage
from docforge.models.intent import LengthUnit, OutputSpec
from docforge.models.ir import DeckPlan

SYSTEM = f"""You are a senior presentation strategist. You plan complete, presentation-ready slide decks as \
structured data that a renderer turns into PowerPoint.

Storyline:
- Lead with the answer. A typical arc: title -> agenda or executive summary -> sections that each prove one \
point -> summary of key takeaways -> closing with the decision or next steps. Short decks (<= 6 slides) skip \
agenda and section dividers.
- One message per slide. headline is a complete assertion of that message (max ~12 words, sentence case, no \
final period), e.g. "Fast charging pays back two years sooner" rather than "Fast charging".
- key_message is one short supporting line (or empty). purpose says why the slide exists.
- No two slides may make the same point.

Composition (archetype must match the content):
- title, section, closing: structural slides; closing carries next steps as bullets.
- agenda / summary: a bullets block of 3-6 short items.
- bullets: 3-6 bullets of <= 15 words; put the key takeaway in key_message.
- comparison: a comparison block with 2-3 columns of 2-4 points each.
- timeline: a timeline block of 3-6 dated events. process: a process block of 3-5 steps.
- chart: a chart block; categories and every series must have equal length; numbers only.
- table: a table block, <= 6 columns and <= 8 rows, all rows the same width.
- kpi: a kpi block of 2-4 metrics (value is short, e.g. "38%", "EUR 9.4bn").
- quote: a quote block with attribution.
- image_text: an image block (description = a concrete, photographable subject in 3-8 words, e.g. "fast \
charging station on a highway at dusk"; alt_text describes the photo) plus 2-4 bullets or a key_message. \
Use it for 1-3 slides where a real photo strengthens the message. The title slide may also carry one image \
block as a cover photo. Images are real stock or openly licensed photos found by search, so never ask for \
charts, text, logos or specific people in images.
Vary archetypes: never more than two consecutive bullets slides; prefer visual structures (comparison, \
process, timeline, kpi, chart) where the content allows.

Evidence and honesty:
- Use only facts, numbers and quotes that appear in the user's request or in the provided <evidence>. \
If no evidence is provided, do not invent statistics, dates, quotes or sources: build the argument with \
qualitative points, frameworks, processes and comparisons. Never fabricate a quote.
- When evidence is provided, build the storyline on it: every statement that uses a fact or number cites the \
supporting claim ids (e.g. "c4") in claim_ids of that bullet, metric, chart or table; charts and KPIs use \
the exact evidence figures and units. Prefer high-authority and recent evidence; where evidence conflicts, say \
so. Never cite ids that are not in the evidence, and never fill evidence gaps with invented facts.
- notes: 2-4 sentences the presenter can say, adding context that does not fit on the slide.

Output:
- every block object includes its "type" field (bullets, paragraph, chart, table, timeline, process, \
comparison, kpi, quote, image, callout).
- slides use ids s01, s02, ... in order. design_hint is one of: {", ".join(palette_names())} \
(pick the one that fits the topic and audience). audience restates who the deck is for.
{UNTRUSTED_NOTE}"""


@dataclass
class PlannerInput:
    objective: str
    spec: OutputSpec
    evidence_digest: str | None = None
    template_summary: str | None = None
    feedback: list[str] = field(default_factory=list)


def length_instruction(spec: OutputSpec) -> str:
    length = spec.length
    if length.unit == LengthUnit.slides and length.explicit and length.target:
        return f"The deck must have exactly {length.target} slides, including title and closing slides."
    if length.unit == LengthUnit.slides and (length.min or length.max):
        return f"Use between {length.min or 3} and {length.max or 20} slides."
    detail = {"brief": "6-8", "standard": "9-12", "detailed": "13-18"}[spec.detail_level.value]
    return (
        f"Choose the number of slides the content needs; typically {detail} slides at this level of detail."
    )


def render_input(inp: PlannerInput) -> str:
    spec = inp.spec
    parts = [
        f"<objective>\n{inp.objective}\n</objective>",
        "<requirements>\n"
        f"Purpose: {spec.purpose or 'as stated in the objective'}\n"
        f"Audience: {spec.audience}\nTone: {spec.tone}\nLanguage: {spec.language}\n"
        f"Detail level: {spec.detail_level.value}\n{length_instruction(spec)}\n"
        + (f"Style notes: {'; '.join(spec.style_notes)}\n" if spec.style_notes else "")
        + "</requirements>",
    ]
    if inp.evidence_digest:
        parts.append(f"<evidence>\n{inp.evidence_digest}\n</evidence>")
    else:
        parts.append("<evidence>\nNo researched evidence is available for this deck.\n</evidence>")
    if inp.template_summary:
        parts.append(f"<template>\n{inp.template_summary}\n</template>")
    return "\n\n".join(parts)


def normalise(deck: DeckPlan) -> DeckPlan:
    """Code owns unit IDs: renumber slides s01..sNN so IDs are stable and unique (ADR-003)."""
    slides = [
        s.model_copy(update={"id": f"s{i:02d}", "headline": s.headline.strip().rstrip(".")})
        for i, s in enumerate(deck.slides, start=1)
    ]
    hint = deck.design_hint if deck.design_hint in palette_names() else None
    return deck.model_copy(update={"slides": slides, "design_hint": hint})


class DeckPlannerAgent(Agent[DeckPlan]):
    name = "deck_planner"
    output_type = DeckPlan
    system_prompt = SYSTEM

    async def run(self, inp: PlannerInput) -> DeckPlan:
        result = await self.ask(render_input(inp))
        assert result.parsed is not None
        return normalise(result.parsed)

    async def revise(self, inp: PlannerInput, previous: DeckPlan, problems: list[str]) -> DeckPlan:
        """One corrective round with concrete problems from plan validation."""
        history = [
            ChatMessage("user", render_input(inp)),
            ChatMessage("assistant", previous.model_dump_json()),
        ]
        feedback = "Revise the deck plan to fix these problems, keeping everything else:\n- " + "\n- ".join(
            problems
        )
        result = await self.ask(feedback, history=history)
        assert result.parsed is not None
        return normalise(result.parsed)
