"""EditorAgent: edits targeted units in intermediate representations (Stage 11, FR-EDIT-1..4).

Takes the existing unit (slide, section, sheet) plus surrounding outline and user instruction,
and returns the updated unit. All other units in the deliverable remain 100% untouched.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from docforge.agents.base import UNTRUSTED_NOTE, Agent
from docforge.models.ir import (
    Block,
    DeckPlan,
    DocumentPlan,
    SectionInsertionPlan,
    SectionPlan,
    SheetPlan,
    SlideInsertionPlan,
    SlidePlan,
)

INSERT_SLIDE_SYSTEM = f"""You are a presentation editor responsible for drafting the requested slide or sequence of slides for an existing deck.

Use the user's requested purpose, the presentation outline, the adjacent slides, available evidence, and the
template guidance supplied in the input. Continue the narrative without duplicating neighboring slides.
Choose an appropriate existing slide archetype and follow the observed template constraints. Preserve source
meaning and cite only claim IDs present in the supplied evidence. Do not invent facts, IDs, layout IDs, or
template properties. Do not propose edits to existing slides. Return the requested count in narrative order,
up to the schema limit; the application assigns stable slide IDs and performs insertion, ordering, rendering,
and validation. Return only a SlideInsertionPlan matching the output schema.
{UNTRUSTED_NOTE}"""


@dataclass
class SlideInsertionInput:
    deck: DeckPlan
    instruction: str
    insertion_index: int
    template_guidance: str | None = None
    evidence_digest: str | None = None


def render_slide_insertion_input(inp: SlideInsertionInput) -> str:
    deck = inp.deck
    before = deck.slides[inp.insertion_index - 1] if inp.insertion_index > 0 else None
    after = deck.slides[inp.insertion_index] if inp.insertion_index < len(deck.slides) else None
    outline = [
        {"position": i, "id": slide.id, "headline": slide.headline, "purpose": slide.purpose}
        for i, slide in enumerate(deck.slides, 1)
    ]
    parts = [
        f"<deck_context>\nTitle: {deck.title}\nAudience: {deck.audience}\n"
        f"Narrative: {json.dumps(deck.narrative)}\n</deck_context>",
        f"<ordered_slide_outline>\n{json.dumps(outline, indent=2)}\n</ordered_slide_outline>",
        f"<insertion_boundary>\nIndex: {inp.insertion_index}\n"
        f"Before: {before.model_dump_json() if before else 'start of deck'}\n"
        f"After: {after.model_dump_json() if after else 'end of deck'}\n</insertion_boundary>",
        f"<user_instruction>\n{inp.instruction}\n</user_instruction>",
    ]
    if inp.template_guidance:
        parts.append(f"<template_guidance>\n{inp.template_guidance}\n</template_guidance>")
    if inp.evidence_digest:
        parts.append(f"<evidence>\n{inp.evidence_digest}\n</evidence>")
    return "\n\n".join(parts)


class SlideInsertionAgent(Agent[SlideInsertionPlan]):
    name = "slide_inserter"
    output_type = SlideInsertionPlan
    system_prompt = INSERT_SLIDE_SYSTEM

    async def run(self, inp: SlideInsertionInput) -> SlideInsertionPlan:
        result = await self.ask(render_slide_insertion_input(inp), temperature=0.2)
        if result.parsed is None:
            raise ValueError("slide insertion returned no structured draft")
        return result.parsed


SECTION_INSERT_SYSTEM = f"""Draft the requested new section or sequence for an existing Word document.
Use the objective, ordered outline, adjacent sections, evidence, and template guidance. Continue the argument,
avoid duplication, preserve facts, and cite only supplied claim IDs. Follow the observed heading hierarchy and
page/style constraints. Do not invent section IDs or template properties, and do not rewrite existing sections.
Return ID-free drafts in narrative order; the application assigns IDs and performs insertion/rendering.
{UNTRUSTED_NOTE}"""


@dataclass
class SectionInsertionInput:
    document: DocumentPlan
    instruction: str
    insertion_index: int
    template_guidance: str | None = None
    evidence_digest: str | None = None


def render_section_insertion_input(inp: SectionInsertionInput) -> str:
    sections = inp.document.sections
    before = sections[inp.insertion_index - 1] if inp.insertion_index else None
    after = sections[inp.insertion_index] if inp.insertion_index < len(sections) else None
    outline = [
        {"position": i, "id": section.id, "heading": section.heading, "purpose": section.purpose}
        for i, section in enumerate(sections, 1)
    ]
    parts = [
        f"<document>\nTitle: {inp.document.title}\nType: {inp.document.doc_type}\n</document>",
        f"<ordered_sections>\n{json.dumps(outline, indent=2)}\n</ordered_sections>",
        f"<boundary>\nIndex: {inp.insertion_index}\n"
        f"Before: {before.model_dump_json(exclude={'blocks', 'subsections'}) if before else 'start'}\n"
        f"After: {after.model_dump_json(exclude={'blocks', 'subsections'}) if after else 'end'}\n</boundary>",
        f"<user_instruction>\n{inp.instruction}\n</user_instruction>",
    ]
    if inp.template_guidance:
        parts.append(f"<template_guidance>\n{inp.template_guidance}\n</template_guidance>")
    if inp.evidence_digest:
        parts.append(f"<evidence>\n{inp.evidence_digest}\n</evidence>")
    return "\n\n".join(parts)


class SectionInsertionAgent(Agent[SectionInsertionPlan]):
    name = "section_inserter"
    output_type = SectionInsertionPlan
    system_prompt = SECTION_INSERT_SYSTEM

    async def run(self, inp: SectionInsertionInput) -> SectionInsertionPlan:
        result = await self.ask(render_section_insertion_input(inp), temperature=0.2)
        if result.parsed is None:
            raise ValueError("section insertion returned no structured plan")
        return result.parsed


SLIDE_SYSTEM = f"""You are an expert presentation editor. You edit ONE slide in a PowerPoint presentation according to user instructions.

Rules:
- You must update ONLY what the user asked to change. Keep all other content, structure, and details intact.
- Keep the exact same slide id: preserve the input slide's id field.
- Keep the archetype unless the instruction explicitly asks to change it.
- If the user asks to change or add a specific bullet, edit only that bullet and preserve the others.
- If the user asks to update numbers or text in a table or chart, update only those numbers/text.
- Every block object must include its "type" field (e.g. "paragraph", "bullets", "table", "chart", "kpi", "callout", "quote").
- Never invent citations. Keep existing claim_ids unless instructed to update them.
- Return the full updated SlidePlan.
{UNTRUSTED_NOTE}"""

SECTION_SYSTEM = f"""You are an expert document editor. You edit ONE section in a professional document (Word/DOCX) according to user instructions.

Rules:
- You must update ONLY what the user asked to change. Keep all other content, headings, and subsections intact.
- Keep the exact same section id: preserve the input section's id field.
- Keep the heading unless the instruction asks to rename it.
- Edit paragraphs, bullets, tables, figures, or callouts as requested.
- Every block object must include its "type" field (e.g. "paragraph", "bullets", "table", "chart", "kpi", "callout", "quote").
- Maintain professional style, tone, and formatting.
- Return the full updated SectionPlan.
{UNTRUSTED_NOTE}"""

SHEET_SYSTEM = f"""You are an expert financial and data analyst. You edit ONE sheet in an Excel workbook according to user instructions.

Rules:
- You must update ONLY what the user asked to change. Keep all other tables, formulas, and cells intact.
- Keep the exact same sheet id: preserve the input sheet's id field, and sheet name.
- Standard Excel functions only: SUM, AVERAGE, MIN, MAX, COUNT, COUNTIF, SUMIF, IF, IFERROR, ROUND, INDEX, MATCH.
- If updating a formula, ensure correct row/column coordinates and quote sheet names with spaces: 'Sheet name'!A1.
- Calculated table columns must use {{row}} in formula_template, e.g. "=B{{row}}*C{{row}}".
- Return the full updated SheetPlan.
{UNTRUSTED_NOTE}"""


@dataclass
class SlideEditorInput:
    slide: SlidePlan
    instruction: str
    outline: list[tuple[str, str]]
    evidence_digest: str | None = None


@dataclass
class SectionEditorInput:
    section: SectionPlan
    instruction: str
    outline: list[tuple[str, str]]
    evidence_digest: str | None = None


@dataclass(frozen=True)
class SectionBlockSelection:
    section_id: str
    block_index: int
    block: Block


_BLOCK_STOP_WORDS = {
    "change", "edit", "make", "update", "rewrite", "replace", "the", "this", "that",
    "paragraph", "section", "document", "text", "content", "please", "only", "to", "with",
}

_SECTION_LEVEL_EDIT = re.compile(
    r"\brename\s+(?:the\s+)?section\s+#?\d+\b|"
    r"\brename\s+(?:the\s+)?(?:first|second|third|\d+(?:st|nd|rd|th)?)\s+section\b|"
    r"\b(?:rename|change|update)\s+(?:the\s+)?(?:section\s+)?heading\b|"
    r"\bchange\s+the\s+section\s+title\b",
    re.IGNORECASE,
)


def is_section_level_edit(instruction: str) -> bool:
    return bool(_SECTION_LEVEL_EDIT.search(instruction))


def select_section_block(section: SectionPlan, instruction: str) -> SectionBlockSelection | None:
    """Find one unambiguous top-level block to edit."""
    blocks = list(enumerate(section.blocks))
    if not blocks:
        return None
    quoted = [item.lower() for item in re.findall(r"['\"]([^'\"]{2,200})['\"]", instruction)]
    if quoted:
        matches = [
            (index, block)
            for index, block in blocks
            if any(quote in block.model_dump_json().lower() for quote in quoted)
        ]
        if len(matches) == 1:
            index, block = matches[0]
            return SectionBlockSelection(section.id, index, block)
        return None

    words = {
        word.lower()
        for word in re.findall(r"\b[a-zA-Z0-9]{4,}\b", instruction)
        if word.lower() not in _BLOCK_STOP_WORDS
    }
    if not words:
        return None
    scored = []
    for index, block in blocks:
        text = block.model_dump_json().lower()
        score = sum(1 for word in words if re.search(rf"\b{re.escape(word)}\b", text))
        if score:
            scored.append((score, index, block))
    scored.sort(key=lambda item: item[0], reverse=True)
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        _, index, block = scored[0]
        return SectionBlockSelection(section.id, index, block)
    return None


_EXACT_REPLACEMENT = re.compile(
    r"\b(?:replace|change)\s+(?:the\s+)?(?:text|sentence|phrase|bullet|word|caption)?\s*"
    r"(?P<old>[\"'].*?[\"'])\s+(?:with|to)\s+(?P<new>[\"'].*?[\"'])",
    re.IGNORECASE | re.DOTALL,
)


def _quoted(value: str) -> str:
    return value[1:-1].strip()


def _replace_strings(value, old: str, new: str) -> tuple[object, int]:
    if isinstance(value, str):
        count = value.count(old)
        return value.replace(old, new), count
    if isinstance(value, list):
        updated = []
        count = 0
        for item in value:
            replacement, item_count = _replace_strings(item, old, new)
            updated.append(replacement)
            count += item_count
        return updated, count
    if isinstance(value, dict):
        updated = {}
        count = 0
        for key, item in value.items():
            replacement, item_count = _replace_strings(item, old, new)
            updated[key] = replacement
            count += item_count
        return updated, count
    return value, 0


def exact_section_replacement(section: SectionPlan, instruction: str) -> SectionPlan | None:
    """Apply one unambiguous quoted text replacement without rewriting the section."""
    match = _EXACT_REPLACEMENT.search(instruction)
    if match is None:
        return None
    old, new = _quoted(match.group("old")), _quoted(match.group("new"))
    if not old or old == new:
        return None
    blocks = []
    total_count = 0
    for block in section.blocks:
        block_data, count = _replace_strings(block.model_dump(), old, new)
        blocks.append(type(block).model_validate(block_data))
        total_count += count
    if total_count != 1:
        return None
    return section.model_copy(update={"blocks": blocks})


@dataclass
class SheetEditorInput:
    sheet: SheetPlan
    instruction: str
    outline: list[tuple[str, str]]
    named_ranges_summary: str | None = None


def render_slide_editor_input(inp: SlideEditorInput) -> str:
    outline_text = "\n".join(f"{uid}: {label}" for uid, label in inp.outline)
    parts = [
        f"<presentation_outline>\n{outline_text}\n</presentation_outline>",
        f"<current_slide_to_edit>\n{inp.slide.model_dump_json(indent=2)}\n</current_slide_to_edit>",
        f"<edit_instruction>\n{inp.instruction}\n</edit_instruction>",
    ]
    if inp.evidence_digest:
        parts.append(f"<evidence>\n{inp.evidence_digest}\n</evidence>")
    return "\n\n".join(parts)


def render_section_editor_input(inp: SectionEditorInput) -> str:
    outline_text = "\n".join(f"{uid}: {label}" for uid, label in inp.outline)
    parts = [
        f"<document_outline>\n{outline_text}\n</document_outline>",
        f"<current_section_to_edit>\n{inp.section.model_dump_json(indent=2)}\n</current_section_to_edit>",
        f"<edit_instruction>\n{inp.instruction}\n</edit_instruction>",
    ]
    if inp.evidence_digest:
        parts.append(f"<evidence>\n{inp.evidence_digest}\n</evidence>")
    return "\n\n".join(parts)


def render_sheet_editor_input(inp: SheetEditorInput) -> str:
    outline_text = "\n".join(f"{uid}: {label}" for uid, label in inp.outline)
    parts = [
        f"<workbook_sheets>\n{outline_text}\n</workbook_sheets>",
        f"<current_sheet_to_edit>\n{inp.sheet.model_dump_json(indent=2)}\n</current_sheet_to_edit>",
        f"<edit_instruction>\n{inp.instruction}\n</edit_instruction>",
    ]
    if inp.named_ranges_summary:
        parts.append(f"<named_ranges>\n{inp.named_ranges_summary}\n</named_ranges>")
    return "\n\n".join(parts)


class SlideEditorAgent(Agent[SlidePlan]):
    name = "slide_editor"
    output_type = SlidePlan
    system_prompt = SLIDE_SYSTEM

    async def run(self, inp: SlideEditorInput) -> SlidePlan:
        result = await self.ask(render_slide_editor_input(inp), temperature=0.1)
        slide = result.parsed
        # Enforce preserved unit id
        if slide.id != inp.slide.id:
            slide = slide.model_copy(update={"id": inp.slide.id})
        return slide


class SectionEditorAgent(Agent[SectionPlan]):
    name = "section_editor"
    output_type = SectionPlan
    system_prompt = SECTION_SYSTEM

    async def run(self, inp: SectionEditorInput) -> SectionPlan:
        result = await self.ask(render_section_editor_input(inp), temperature=0.1)
        sec = result.parsed
        if sec.id != inp.section.id:
            sec = sec.model_copy(update={"id": inp.section.id})
        return sec


class SheetEditorAgent(Agent[SheetPlan]):
    name = "sheet_editor"
    output_type = SheetPlan
    system_prompt = SHEET_SYSTEM

    async def run(self, inp: SheetEditorInput) -> SheetPlan:
        result = await self.ask(render_sheet_editor_input(inp), temperature=0.1)
        sheet = result.parsed
        if sheet.id != inp.sheet.id:
            sheet = sheet.model_copy(update={"id": inp.sheet.id})
        return sheet
