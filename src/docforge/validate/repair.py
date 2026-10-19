"""Deterministic IR repairs (ARCHITECTURE §7). LLM-assisted repairs (condensing text) join in Stage 7."""

from __future__ import annotations

import math
from dataclasses import dataclass

from docforge.models.ir import (
    BulletsBlock,
    DeckPlan,
    KPIBlock,
    ProcessBlock,
    SlideArchetype,
    SlidePlan,
    TableBlock,
    TimelineBlock,
)
from docforge.models.quality import Finding

_SPLITTABLE = {
    BulletsBlock: "items",
    TimelineBlock: "events",
    ProcessBlock: "steps",
    KPIBlock: "metrics",
    TableBlock: "rows",
}
_SPLIT_TRIGGERS = {"pptx.text_overflow", "pptx.density"}


@dataclass
class RepairAction:
    finding_id: str
    check_id: str
    unit_id: str
    action: str


def split_slide(slide: SlidePlan) -> list[SlidePlan] | None:
    """Split the first splittable block in half across two slides; None when nothing can be split."""
    if slide.archetype in (SlideArchetype.title, SlideArchetype.section, SlideArchetype.closing):
        return None
    for index, block in enumerate(slide.blocks):
        attr = next((a for kind, a in _SPLITTABLE.items() if isinstance(block, kind)), None)
        if attr is None:
            continue
        seq = getattr(block, attr)
        if len(seq) < 2:
            continue
        half = math.ceil(len(seq) / 2)
        first = block.model_copy(update={attr: seq[:half]})
        second = block.model_copy(update={attr: seq[half:]})
        part1 = slide.model_copy(
            update={"blocks": [*slide.blocks[:index], first, *slide.blocks[index + 1 :]]}
        )
        part2 = slide.model_copy(
            update={
                "id": f"{slide.id}-2",
                "headline": f"{slide.headline} (continued)",
                "key_message": "",
                "blocks": [second],
                "notes": None,
            }
        )
        return [part1, part2]
    return None


def repair_deck(
    deck: DeckPlan, findings: list[Finding], *, allow_growth: bool
) -> tuple[DeckPlan, list[RepairAction]]:
    """Apply one round of repairs. Splitting adds slides, so it is skipped when the length is fixed."""
    actions: list[RepairAction] = []
    if not allow_growth:
        return deck, actions
    targets: dict[str, Finding] = {}
    for f in findings:
        # Splitting only helps body content; an overflowing headline needs shorter text, not more slides.
        title_like = (f.element or "").startswith(("content:headline", "content:title"))
        if (
            f.check_id in _SPLIT_TRIGGERS
            and f.unit_id
            and f.severity in ("critical", "major")
            and not title_like
        ):
            targets.setdefault(f.unit_id, f)
    if not targets:
        return deck, actions
    slides: list[SlidePlan] = []
    existing = {s.id for s in deck.slides}
    for slide in deck.slides:
        finding = targets.get(slide.id)
        parts = split_slide(slide) if finding else None
        if parts and parts[1].id not in existing:
            slides.extend(parts)
            for f in findings:
                if f.unit_id == slide.id and f.check_id in _SPLIT_TRIGGERS:
                    actions.append(RepairAction(f.id, f.check_id, slide.id, "split slide into two"))
        else:
            slides.append(slide)
    return deck.model_copy(update={"slides": slides}), actions
