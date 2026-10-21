"""WorkbookPlannerAgent: objective + datasets + evidence → WorkbookPlan (Stage 10, FR-XLSX-1..7)."""

from __future__ import annotations

from dataclasses import dataclass, field

from docforge.agents.base import UNTRUSTED_NOTE, Agent
from docforge.llm.base import ChatMessage
from docforge.models.intent import OutputSpec
from docforge.models.ir import WorkbookPlan

SYSTEM = f"""You are a senior financial and data analyst. You design Excel workbooks as structured data that a \
renderer writes with openpyxl. The workbook must calculate with real formulas.

Structure:
- Separate concerns: an "assumptions" sheet (inputs, each a named range), "data" sheets (raw records), \
"calculations" sheets (formulas only), a "report" sheet (headline KPIs and charts). A README and a Sources sheet \
are added automatically; do not plan them. Sheet names <= 31 chars, unique, no []:*?/\\ characters.
- Each sheet: id (sh-1, sh-2...), name, role, description (one line), tables and/or cells, optional charts, freeze \
(e.g. "A2" under a header row).
- Tables: anchor is the header cell (e.g. "A1"); columns have dtype (text, int, float, currency, percent, date, \
bool), unit and, for calculated columns, formula_template using {{row}} for the row number, e.g. "=C{{row}}*D{{row}}" \
or "=C{{row}}*(1+growth)". rows hold one value per column (use null for calculated columns). To load a user dataset, \
set source_dataset to its id, copy its column names exactly and leave rows empty.
- Cells: ref like "B4"; value for inputs and labels, formula for outputs (e.g. "=SUM('Revenue model'!E2:E61)"). \
style_role: label, input (assumptions), output (results), header, note.
- named_ranges: one per assumption, pointing at its input cell (ref like "B3"); formulas may use the names.
- Formulas: standard Excel functions only (SUM, AVERAGE, MIN, MAX, COUNT, COUNTIF, SUMIF, SUMPRODUCT, IF, IFERROR, \
ROUND, INDEX, MATCH, XLOOKUP is not allowed). Quote sheet names with spaces: 'Sheet name'!A1. Never divide by a \
cell that can be zero without IFERROR, e.g. =IFERROR(numerator/denominator, 0). Every reference must point at an existing \
cell filled by the plan. Table row formulas must use dynamic formula_template with {{row}}, not hardcoded static numbers. \
Table summaries must reference the exact data range (e.g. data rows 2 to 13 -> =SUM(B2:B13)).
- Charts: data_ref includes the header row (e.g. "B1:B13") and categories_ref the category cells (e.g. "A2:A13") on \
the same sheet; anchor a free cell to the right of the data.
- checks: 1-5 expected values you can compute exactly from inputs (e.g. a total of literal values).
Evidence: numeric assumptions taken from evidence cite claim ids in that sheet's claim_ids; label other assumptions \
as assumptions in a note cell. Never invent precise statistics. Use realistic, internally consistent values.
{UNTRUSTED_NOTE}"""


@dataclass
class WorkbookInput:
    objective: str
    spec: OutputSpec
    dataset_profiles: list[str] = field(default_factory=list)
    evidence_digest: str | None = None


def render_input(inp: WorkbookInput) -> str:
    parts = [
        f"<objective>\n{inp.objective}\n</objective>",
        f"<requirements>\nAudience: {inp.spec.audience}\nDetail level: {inp.spec.detail_level.value}\n"
        + (f"Style notes: {'; '.join(inp.spec.style_notes)}\n" if inp.spec.style_notes else "")
        + "</requirements>",
    ]
    if inp.dataset_profiles:
        parts.append("<datasets>\n" + "\n\n".join(inp.dataset_profiles) + "\n</datasets>")
    parts.append(f"<evidence>\n{inp.evidence_digest or 'No researched evidence is available.'}\n</evidence>")
    return "\n\n".join(parts)


def normalise(plan: WorkbookPlan) -> WorkbookPlan:
    """Code owns sheet IDs and sanitises names (Excel rejects []:*?/\\ and names > 31 chars)."""
    id_map, sheets, used = {}, [], set()
    for i, sheet in enumerate(plan.sheets, start=1):
        name = "".join(ch for ch in sheet.name if ch not in "[]:*?/\\").strip()[:31] or f"Sheet{i}"
        while name.lower() in used or name.lower() in ("readme", "sources"):
            name = f"{name[:28]} {i}"
        used.add(name.lower())
        id_map[sheet.id] = f"sh-{i}"
        sheets.append(sheet.model_copy(update={"id": f"sh-{i}", "name": name}))
    return plan.model_copy(
        update={
            "sheets": sheets,
            "named_ranges": [
                n.model_copy(update={"sheet_id": id_map.get(n.sheet_id, n.sheet_id)})
                for n in plan.named_ranges
            ],
            "checks": [
                c.model_copy(update={"sheet_id": id_map.get(c.sheet_id, c.sheet_id)}) for c in plan.checks
            ],
        }
    )


class WorkbookPlannerAgent(Agent[WorkbookPlan]):
    name = "workbook_planner"
    output_type = WorkbookPlan
    system_prompt = SYSTEM

    async def run(self, inp: WorkbookInput) -> WorkbookPlan:
        result = await self.ask(render_input(inp), temperature=0.2)
        return normalise(result.parsed)

    async def revise(self, inp: WorkbookInput, previous: WorkbookPlan, problems: list[str]) -> WorkbookPlan:
        history = [
            ChatMessage("user", render_input(inp)),
            ChatMessage("assistant", previous.model_dump_json()),
        ]
        feedback = (
            "The workbook was built and recalculated using an independent calculation engine. "
            "Please fix the following formula and data problems, and return the complete corrected WorkbookPlan JSON:\n"
            + "\n".join(f"- {p}" for p in problems)
            + "\n\nKey correction requirements:\n"
            "1. Fix every formula error (#NAME?, #REF!, #DIV/0!, #VALUE!). Ensure named ranges match defined names exactly.\n"
            "2. Ensure all calculated table columns have formula_template using {row} (e.g. '=B{row}*C{row}'), with null in rows.\n"
            "3. Ensure all formula references point to existing cells that are filled by the plan.\n"
            "4. Return the full corrected WorkbookPlan."
        )
        result = await self.ask(feedback, history=history, temperature=0.2)
        return normalise(result.parsed)
