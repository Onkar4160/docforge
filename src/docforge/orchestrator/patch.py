"""IR patch operations and Scope Guard (ADR-003, DATA_MODELS §7, FR-EDIT-2..4).

Ensures only targeted units are changed while all other units remain 100% byte-for-byte identical.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from docforge.core.errors import DocForgeError
from docforge.models.edit import IRPatch, PatchOp
from docforge.models.intent import StyleChange
from docforge.models.ir import Block, DeckPlan, DocumentPlan, SectionPlan, SheetPlan, SlidePlan, WorkbookPlan

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


def apply_slide_insert(
    deck: DeckPlan, slide: SlidePlan, index: int, *, instruction: str = "", base_version: int = 1
) -> tuple[DeckPlan, IRPatch]:
    """Insert a new slide at a list position without replacing or renumbering existing slides."""
    existing_ids = {item.id for item in deck.slides}
    if slide.id in existing_ids:
        raise ScopeViolationError(f"Slide id '{slide.id}' already exists in deck")
    if not 0 <= index <= len(deck.slides):
        raise ScopeViolationError(f"Slide insertion index {index} is outside the deck")
    new_slides = [*deck.slides[:index], slide, *deck.slides[index:]]
    if [item.id for item in new_slides if item.id != slide.id] != [item.id for item in deck.slides]:
        raise ScopeViolationError("Slide insertion changed the existing slide order")
    new_deck = deck.model_copy(update={"slides": new_slides})
    patch = IRPatch(
        base_version=base_version,
        ops=[PatchOp(op="add", path=f"/slides/{index}", value=slide.model_dump())],
        affected_unit_ids=[slide.id],
        rationale=instruction or f"Inserted slide {slide.id}",
    )
    return new_deck, patch


def apply_slide_move(
    deck: DeckPlan, slide_id: str, index: int, *, instruction: str = "", base_version: int = 1
) -> tuple[DeckPlan, IRPatch]:
    """Move one existing slide while retaining stable IDs and all other slide content."""
    old_index = next((i for i, item in enumerate(deck.slides) if item.id == slide_id), None)
    if old_index is None:
        raise ScopeViolationError(f"Slide id '{slide_id}' not found in deck")
    if not 0 <= index < len(deck.slides):
        raise ScopeViolationError(f"Slide destination index {index} is outside the deck")
    new_slides = list(deck.slides)
    slide = new_slides.pop(old_index)
    new_slides.insert(index, slide)
    if slide.id != new_slides[index].id or {item.id for item in new_slides} != {
        item.id for item in deck.slides
    }:
        raise ScopeViolationError("Slide move changed slide identity")
    new_deck = deck.model_copy(update={"slides": new_slides})
    patch = IRPatch(
        base_version=base_version,
        ops=[PatchOp(op="move", path=f"/slides/{index}", from_=f"/slides/{old_index}")],
        affected_unit_ids=[slide_id],
        rationale=instruction or f"Moved slide {slide_id}",
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


def apply_section_block_edit(
    doc: DocumentPlan,
    section_id: str,
    block_index: int,
    edited_block: Block,
    *,
    instruction: str = "",
    base_version: int = 1,
) -> tuple[DocumentPlan, IRPatch]:
    """Replace exactly one block in one section and preserve every other IR node."""
    changed = False

    def update_sections(sections: list[SectionPlan]) -> list[SectionPlan]:
        nonlocal changed
        updated = []
        for section in sections:
            if section.id == section_id:
                if not 0 <= block_index < len(section.blocks):
                    raise ScopeViolationError(
                        f"Block index {block_index} is outside section '{section_id}'"
                    )
                blocks = list(section.blocks)
                blocks[block_index] = edited_block
                updated.append(section.model_copy(update={"blocks": blocks}))
                changed = True
            else:
                updated.append(
                    section.model_copy(update={"subsections": update_sections(section.subsections)})
                    if section.subsections
                    else section
                )
        return updated

    new_doc = doc.model_copy(update={"sections": update_sections(doc.sections)})
    if not changed:
        raise ScopeViolationError(f"Target section id '{section_id}' not found in document")
    if any(
        original != updated
        for original, updated in zip(doc.all_sections(), new_doc.all_sections(), strict=True)
        if original.id != section_id
    ):
        raise ScopeViolationError("Scope guard failed: out-of-scope document content was modified")
    return new_doc, IRPatch(
        base_version=base_version,
        ops=[
            PatchOp(
                op="replace",
                path=f"/sections/{section_id}/blocks/{block_index}",
                value=edited_block.model_dump(),
            )
        ],
        affected_unit_ids=[section_id],
        rationale=instruction,
    )


def apply_section_insert(
    doc: DocumentPlan,
    section: SectionPlan,
    index: int,
    *,
    instruction: str = "",
    base_version: int = 1,
) -> tuple[DocumentPlan, IRPatch]:
    """Insert a new top-level section without replacing or renumbering existing sections."""
    existing_ids = {item.id for item in doc.all_sections()}
    inserted_ids = {item.id for item in section.walk()}
    if existing_ids & inserted_ids:
        raise ScopeViolationError("Inserted section IDs must be unique within the document")
    if not 0 <= index <= len(doc.sections):
        raise ScopeViolationError(f"Section insertion index {index} is outside the document")
    sections = [*doc.sections[:index], section, *doc.sections[index:]]
    new_doc = doc.model_copy(update={"sections": sections})
    patch = IRPatch(
        base_version=base_version,
        ops=[PatchOp(op="add", path=f"/sections/{index}", value=section.model_dump())],
        affected_unit_ids=list(inserted_ids),
        rationale=instruction or f"Inserted section {section.id}",
    )
    return new_doc, patch


def apply_section_move(
    doc: DocumentPlan,
    section_id: str,
    index: int,
    *,
    instruction: str = "",
    base_version: int = 1,
) -> tuple[DocumentPlan, IRPatch]:
    """Move a top-level section while retaining its ID and all nested section content."""
    old_index = next((i for i, section in enumerate(doc.sections) if section.id == section_id), None)
    if old_index is None:
        raise ScopeViolationError("Only top-level sections can be reordered")
    if not 0 <= index < len(doc.sections):
        raise ScopeViolationError(f"Section destination index {index} is outside the document")
    sections = list(doc.sections)
    section = sections.pop(old_index)
    sections.insert(index, section)
    new_doc = doc.model_copy(update={"sections": sections})
    patch = IRPatch(
        base_version=base_version,
        ops=[PatchOp(op="move", path=f"/sections/{index}", from_=f"/sections/{old_index}")],
        affected_unit_ids=[section_id],
        rationale=instruction or f"Moved section {section_id}",
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


def _remove_section_recursive(sections: list[SectionPlan], unit_id: str) -> tuple[list[SectionPlan], bool]:
    updated_list = []
    removed = False
    for s in sections:
        if s.id == unit_id:
            removed = True
            continue
        if s.subsections:
            new_subs, sub_removed = _remove_section_recursive(s.subsections, unit_id)
            if sub_removed:
                removed = True
                s = s.model_copy(update={"subsections": new_subs})
        updated_list.append(s)
    return updated_list, removed


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
        new_sections, removed = _remove_section_recursive(ir.sections, unit_id)
        if not removed:
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
    ir: ArtifactIR,
    style_changes: list[StyleChange],
    *,
    instruction: str = "",
    base_version: int = 1,
    slide_ids: list[str] | None = None,
    section_ids: list[str] | None = None,
) -> tuple[ArtifactIR, IRPatch]:
    """Apply supported style changes globally or to selected units without changing content."""
    if not style_changes:
        raise ScopeViolationError("No supported style changes were provided")
    if slide_ids and section_ids:
        raise ScopeViolationError("A style patch cannot target slides and document sections together")

    def update_style(style, change: StyleChange):
        prop = change.property.lower().strip()
        value = change.value.strip()
        if prop in ("font_heading", "title_font"):
            prop = "heading_font"
        elif prop in ("font_body", "font"):
            prop = "body_font"
        elif prop in ("body_size", "font_size", "body_font_size"):
            prop = "body_size_pt"
        elif prop in ("heading_size", "title_size", "heading_font_size"):
            prop = "heading_sizes_pt.title"
        elif prop in ("margins", "margin"):
            prop = "margins_in"
        elif prop in ("orientation", "doc_orientation"):
            prop = "page_orientation"
        elif prop in ("alignment", "align", "text_align", "text_alignment"):
            prop = "body_alignment"
        elif prop in ("paragraph_spacing", "spacing", "para_spacing"):
            prop = "paragraph_spacing_pt"

        if prop in ("heading_font", "body_font"):
            if not value:
                raise ScopeViolationError(f"Style property '{prop}' cannot be empty")
            return style.model_copy(update={prop: value}), prop, value
        if prop in ("heading_alignment", "body_alignment"):
            if value.lower() not in {"left", "center", "right", "justify"}:
                raise ScopeViolationError(f"Unsupported alignment '{value}'")
            return style.model_copy(update={prop: value.lower()}), prop, value.lower()
        if prop == "page_orientation" and section_ids is None:
            if value.lower() not in {"portrait", "landscape"}:
                raise ScopeViolationError(f"Unsupported page orientation '{value}'")
            return style.model_copy(update={prop: value.lower()}), prop, value.lower()
        if prop == "page_orientation":
            raise ScopeViolationError("Page orientation can only be changed for the entire document")
        if prop.startswith(("heading_sizes_pt.", "heading_size.", "heading_sizes.", "headings.")):
            key = prop.split(".", 1)[1]
            if key not in {"title", "h1", "h2", "h3"}:
                raise ScopeViolationError(f"Unsupported heading size role '{key}'")
            parsed = _style_number(prop, value)
            sizes = style.heading_sizes_pt.model_copy(update={key: parsed})
            return style.model_copy(update={"heading_sizes_pt": sizes}), f"heading_sizes_pt.{key}", parsed
        if prop in ("h1", "h2", "h3", "title"):
            parsed = _style_number(prop, value)
            sizes = style.heading_sizes_pt.model_copy(update={prop: parsed})
            return style.model_copy(update={"heading_sizes_pt": sizes}), f"heading_sizes_pt.{prop}", parsed
        if prop in ("body_size_pt", "line_spacing", "paragraph_spacing_pt", "margins_in"):
            parsed = _style_number(prop, value)
            return style.model_copy(update={prop: parsed}), prop, parsed

        roles = {
            "background",
            "surface",
            "text",
            "text_muted",
            "primary",
            "secondary",
            "positive",
            "negative",
            "accent1",
            "accent2",
            "accent3",
            "accent4",
            "accent5",
            "accent6",
        }
        named_colors = {
            "navy": "000080",
            "darkblue": "00008B",
            "blue": "0000FF",
            "black": "000000",
            "white": "FFFFFF",
            "red": "FF0000",
            "green": "008000",
            "gray": "808080",
            "grey": "808080",
            "charcoal": "333333",
            "teal": "008080",
            "maroon": "800000",
            "purple": "800080",
            "orange": "FFA500",
        }
        color_key = None
        if prop in roles:
            color_key = prop
        elif prop.startswith(("palette.", "colors.", "palette_overrides.")):
            color_key = prop.split(".", 1)[1]
        elif prop.endswith(tuple(f"_{r}" for r in roles)):
            color_key = prop.rsplit("_", 1)[1]
        elif prop.endswith(tuple(f".{r}" for r in roles)):
            color_key = prop.rsplit(".", 1)[1]

        if color_key in roles:
            raw_val = value.lower().strip()
            if raw_val in named_colors:
                color = named_colors[raw_val]
            else:
                color = value.removeprefix("#").upper()
                if len(color) == 3 and all(c in "0123456789ABCDEF" for c in color):
                    color = "".join(c * 2 for c in color)
            if len(color) != 6 or any(char not in "0123456789ABCDEF" for char in color):
                raise ScopeViolationError(f"Invalid hexadecimal color for palette role '{color_key}'")
            overrides = dict(style.palette_overrides)
            overrides[color_key] = color
            return (
                style.model_copy(update={"palette_overrides": overrides}),
                f"palette_overrides.{color_key}",
                color,
            )
        raise ScopeViolationError(f"Unsupported style property '{change.property}'")

    ops: list[PatchOp] = []
    if slide_ids:
        if not isinstance(ir, DeckPlan):
            raise ScopeViolationError("Slide-scoped restyling requires a presentation")
        unknown = set(slide_ids) - {slide.id for slide in ir.slides}
        if unknown:
            raise ScopeViolationError(f"Unknown slide IDs in style scope: {sorted(unknown)}")
        slides = []
        for index, slide in enumerate(ir.slides):
            style = slide.style
            if slide.id in slide_ids:
                for change in style_changes:
                    style, prop, value = update_style(style, change)
                    ops.append(
                        PatchOp(
                            op="replace",
                            path=f"/slides/{index}/style/{prop.replace('.', '/')}",
                            value=value,
                        )
                    )
                slide = slide.model_copy(update={"style": style})
            slides.append(slide)
        new_ir = ir.model_copy(update={"slides": slides})
        affected = list(dict.fromkeys(slide_ids))
    elif section_ids:
        if not isinstance(ir, DocumentPlan):
            raise ScopeViolationError("Section-scoped restyling requires a Word document")
        known_ids = {section.id for section in ir.all_sections()}
        unknown = set(section_ids) - known_ids
        if unknown:
            raise ScopeViolationError(f"Unknown section IDs in style scope: {sorted(unknown)}")

        def update_sections(sections: list[SectionPlan]) -> list[SectionPlan]:
            updated = []
            for section in sections:
                if section.subsections:
                    section = section.model_copy(update={"subsections": update_sections(section.subsections)})
                if section.id in section_ids:
                    style = section.style
                    for change in style_changes:
                        style, prop, value = update_style(style, change)
                        ops.append(
                            PatchOp(
                                op="replace",
                                path=f"/sections/{section.id}/style/{prop.replace('.', '/')}",
                                value=value,
                            )
                        )
                    section = section.model_copy(update={"style": style})
                updated.append(section)
            return updated

        new_ir = ir.model_copy(update={"sections": update_sections(ir.sections)})
        affected = list(dict.fromkeys(section_ids))
    else:
        style = ir.style
        for change in style_changes:
            style, prop, value = update_style(style, change)
            ops.append(PatchOp(op="replace", path=f"/style/{prop.replace('.', '/')}", value=value))
        new_ir = ir.model_copy(update={"style": style})
        affected = ["style"]

    patch = IRPatch(
        base_version=base_version,
        ops=ops,
        affected_unit_ids=affected,
        rationale=instruction or "Restyle document",
    )
    return new_ir, patch


def _style_number(prop: str, value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ScopeViolationError(f"Style property '{prop}' must be numeric") from exc
    if not math.isfinite(parsed):
        raise ScopeViolationError(f"Style property '{prop}' must be finite")
    if prop.endswith("_pt") and not 6 <= parsed <= 96:
        raise ScopeViolationError(f"Style property '{prop}' must be between 6 and 96 points")
    if prop == "margins_in" and not 0 <= parsed <= 2:
        raise ScopeViolationError(f"Style property '{prop}' must be between 0 and 2 inches")
    if prop == "line_spacing" and not 0.5 <= parsed <= 3:
        raise ScopeViolationError(f"Style property '{prop}' must be between 0.5 and 3")
    if prop == "paragraph_spacing_pt" and not 0 <= parsed <= 72:
        raise ScopeViolationError(f"Style property '{prop}' must be between 0 and 72 points")
    return parsed
