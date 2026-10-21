"""EditorAgent: edits targeted units in intermediate representations (Stage 11, FR-EDIT-1..4).

Takes the existing unit (slide, section, sheet) plus surrounding outline and user instruction,
and returns the updated unit. All other units in the deliverable remain 100% untouched.
"""

from __future__ import annotations

from dataclasses import dataclass

from docforge.agents.base import UNTRUSTED_NOTE, Agent
from docforge.models.ir import SectionPlan, SheetPlan, SlidePlan

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
