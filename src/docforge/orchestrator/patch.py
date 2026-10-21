"""IR patch operations and Scope Guard (ADR-003, DATA_MODELS §7, FR-EDIT-2..4).

Ensures only targeted units are changed while all other units remain 100% byte-for-byte identical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from docforge.core.errors import DocForgeError
from docforge.models.edit import IRPatch, PatchOp
from docforge.models.intent import StyleChange
from docforge.models.ir import DeckPlan, DocumentPlan, SectionPlan, SheetPlan, SlidePlan, WorkbookPlan

if TYPE_CHECKING:
    from docforge.models.ir import ArtifactIR


class ScopeViolationError(DocForgeError):
    """Raised when an edit attempts to modify units outside the resolved target scope."""

    code = "scope_violation"


def apply_slide_edit(
    deck: DeckPlan, edited_slide: SlidePlan, *, instruction: str = "", base_version: int = 1
) -> tuple[DeckPlan, IRPatch]:
    """Replace only the targeted slide in the deck; all other slides remain untouched."""
    idx = next((i for i, s in enumerate(deck.slides) if s.id == edited_slide.id), None)
    if idx is None:
        raise ScopeViolationError(f"Target slide id '{edited_slide.id}' not found in deck")

    new_slides: list[SlidePlan] = []
    for i, s in enumerate(deck.slides):
        if i == idx:
            new_slides.append(edited_slide)
        else:
            new_slides.append(s)

    # Scope guard: verify other slides are untouched
    for i, (orig, updated) in enumerate(zip(deck.slides, new_slides, strict=False)):
        if i != idx and orig != updated:
            raise ScopeViolationError(
                f"Scope guard failed: slide {orig.id} was modified outside target scope"
            )

    new_deck = deck.model_copy(update={"slides": new_slides})
    patch = IRPatch(
        base_version=base_version,
        ops=[PatchOp(op="replace", path=f"/slides/{idx}", value=edited_slide.model_dump())],
        affected_unit_ids=[edited_slide.id],
        rationale=instruction,
    )
    return new_deck, patch


def _replace_section_recursive(
    sections: list[SectionPlan], edited: SectionPlan
) -> tuple[list[SectionPlan], bool]:
    updated_list = []
    found = False
    for s in sections:
        if s.id == edited.id:
            updated_list.append(edited)
            found = True
        elif s.subsections:
            new_subs, sub_found = _replace_section_recursive(s.subsections, edited)
            if sub_found:
                found = True
                updated_list.append(s.model_copy(update={"subsections": new_subs}))
            else:
                updated_list.append(s)
        else:
            updated_list.append(s)
    return updated_list, found


def apply_section_edit(
    doc: DocumentPlan, edited_section: SectionPlan, *, instruction: str = "", base_version: int = 1
) -> tuple[DocumentPlan, IRPatch]:
    """Replace only the targeted section in the document; all other sections remain untouched."""
    new_sections, found = _replace_section_recursive(doc.sections, edited_section)
    if not found:
        raise ScopeViolationError(f"Target section id '{edited_section.id}' not found in document")

    # Scope guard: verify out-of-scope sections are untouched
    orig_map = {s.id: s for s in doc.all_sections() if s.id != edited_section.id}
    new_doc = doc.model_copy(update={"sections": new_sections})
    new_map = {s.id: s for s in new_doc.all_sections() if s.id != edited_section.id}
    if orig_map != new_map:
        raise ScopeViolationError("Scope guard failed: out-of-scope sections were modified")

    patch = IRPatch(
        base_version=base_version,
        ops=[PatchOp(op="replace", path=f"/sections/{edited_section.id}", value=edited_section.model_dump())],
        affected_unit_ids=[edited_section.id],
        rationale=instruction,
    )
    return new_doc, patch


def apply_sheet_edit(
    wb: WorkbookPlan, edited_sheet: SheetPlan, *, instruction: str = "", base_version: int = 1
) -> tuple[WorkbookPlan, IRPatch]:
    """Replace only the targeted sheet in the workbook; all other sheets remain untouched."""
    idx = next((i for i, s in enumerate(wb.sheets) if s.id == edited_sheet.id), None)
    if idx is None:
        raise ScopeViolationError(f"Target sheet id '{edited_sheet.id}' not found in workbook")

    new_sheets = []
    for i, s in enumerate(wb.sheets):
        if i == idx:
            new_sheets.append(edited_sheet)
        else:
            new_sheets.append(s)

    for i, (orig, updated) in enumerate(zip(wb.sheets, new_sheets, strict=False)):
        if i != idx and orig != updated:
            raise ScopeViolationError(
                f"Scope guard failed: sheet {orig.id} was modified outside target scope"
            )

    new_wb = wb.model_copy(update={"sheets": new_sheets})
    patch = IRPatch(
        base_version=base_version,
        ops=[PatchOp(op="replace", path=f"/sheets/{idx}", value=edited_sheet.model_dump())],
        affected_unit_ids=[edited_sheet.id],
        rationale=instruction,
    )
    return new_wb, patch


def apply_remove_unit(
    ir: ArtifactIR, unit_id: str, *, instruction: str = "", base_version: int = 1
) -> tuple[ArtifactIR, IRPatch]:
    """Remove a unit (slide, section, sheet) from the IR."""
    if isinstance(ir, DeckPlan):
        new_slides = [s for s in ir.slides if s.id != unit_id]
        if len(new_slides) == len(ir.slides):
            raise ScopeViolationError(f"Slide '{unit_id}' not found to remove")
        new_ir = ir.model_copy(update={"slides": new_slides})
    elif isinstance(ir, DocumentPlan):
        new_sections = [s for s in ir.sections if s.id != unit_id]
        if len(new_sections) == len(ir.sections):
            raise ScopeViolationError(f"Section '{unit_id}' not found to remove")
        new_ir = ir.model_copy(update={"sections": new_sections})
    elif isinstance(ir, WorkbookPlan):
        new_sheets = [s for s in ir.sheets if s.id != unit_id]
        if len(new_sheets) == len(ir.sheets):
            raise ScopeViolationError(f"Sheet '{unit_id}' not found to remove")
        new_ir = ir.model_copy(update={"sheets": new_sheets})
    else:
        raise ScopeViolationError(f"Unsupported IR format: {type(ir)}")

    patch = IRPatch(
        base_version=base_version,
        ops=[PatchOp(op="remove", path=f"/units/{unit_id}")],
        affected_unit_ids=[unit_id],
        rationale=instruction or f"Removed unit {unit_id}",
    )
    return new_ir, patch


def apply_restyle(
    ir: ArtifactIR, style_changes: list[StyleChange], *, instruction: str = "", base_version: int = 1
) -> tuple[ArtifactIR, IRPatch]:
    """Apply style changes directly to ir.style without modifying content."""
    style = ir.style.model_copy()
    ops: list[PatchOp] = []
    for sc in style_changes:
        prop = sc.property.lower().strip()
        val = sc.value.strip()
        if prop in ("heading_font", "font_heading", "title_font"):
            style = style.model_copy(update={"heading_font": val})
            ops.append(PatchOp(op="replace", path="/style/heading_font", value=val))
        elif prop in ("body_font", "font_body", "font"):
            style = style.model_copy(update={"body_font": val})
            ops.append(PatchOp(op="replace", path="/style/body_font", value=val))
        elif prop in ("body_size_pt", "body_size"):
            try:
                style = style.model_copy(update={"body_size_pt": float(val)})
                ops.append(PatchOp(op="replace", path="/style/body_size_pt", value=float(val)))
            except ValueError:
                pass
        elif prop.startswith("palette.") or prop.startswith("colors."):
            key = prop.split(".", 1)[1]
            overrides = dict(style.palette_overrides)
            overrides[key] = val
            style = style.model_copy(update={"palette_overrides": overrides})
            ops.append(PatchOp(op="replace", path=f"/style/palette_overrides/{key}", value=val))

    new_ir = ir.model_copy(update={"style": style})
    patch = IRPatch(
        base_version=base_version,
        ops=ops,
        affected_unit_ids=["style"],
        rationale=instruction or "Restyle document",
    )
    return new_ir, patch
