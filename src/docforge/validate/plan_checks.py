"""Plan-level checks on a DeckPlan before and after rendering (FR-PLAN-6, QUALITY §2.1)."""

from __future__ import annotations

import re

from docforge.models.evidence import ResearchDossier
from docforge.models.intent import LengthUnit, OutputSpec
from docforge.models.ir import (
    BulletsBlock,
    ChartBlock,
    ComparisonBlock,
    DeckPlan,
    KPIBlock,
    ProcessBlock,
    SlideArchetype,
    TableBlock,
    TimelineBlock,
    block_claim_ids,
)
from docforge.models.quality import Dimension, Severity
from docforge.validate.common import PLACEHOLDER_PATTERNS, CheckRun, similar

# Upper bounds before a composition becomes unreadable on one slide (repairable by splitting).
LIMITS = {
    TimelineBlock: ("events", 6),
    ProcessBlock: ("steps", 5),
    KPIBlock: ("metrics", 4),
    ComparisonBlock: ("columns", 4),
    TableBlock: ("rows", 10),
    BulletsBlock: ("items", 7),
}

# Quantities that must be backed by evidence when research was performed.
_FIGURE = re.compile(
    r"[$€£¥]\s?\d|\d[\d,.]*\s?(%|percent|bn|billion|million|mn|trillion|k\b|x\b|GW|MW|kWh|TWh)", re.IGNORECASE
)

_STRUCTURAL = {
    SlideArchetype.title,
    SlideArchetype.section,
    SlideArchetype.closing,
    SlideArchetype.references,
}


def check_deck_plan(
    run: CheckRun, deck: DeckPlan, spec: OutputSpec | None, dossier: ResearchDossier | None
) -> None:
    with run.check("common.length", 1):
        fixed = spec is not None and spec.length.explicit and spec.length.unit == LengthUnit.slides
        if fixed and spec.length.target and len(deck.slides) != spec.length.target:
            run.finding(
                "common.length",
                Dimension.structure,
                Severity.major,
                f"deck has {len(deck.slides)} slides; {spec.length.target} were requested",
                requested=spec.length.target,
                actual=len(deck.slides),
            )

    with run.check("content.empty_units", 1):
        for s in deck.slides:
            if s.archetype not in _STRUCTURAL and not s.blocks and not s.key_message:
                run.finding(
                    "content.empty_units",
                    Dimension.content,
                    Severity.critical,
                    f"slide '{s.headline}' has no content",
                    unit_id=s.id,
                )
            if not s.headline.strip() and s.archetype != SlideArchetype.quote:
                run.finding(
                    "content.empty_units",
                    Dimension.content,
                    Severity.major,
                    "slide has no headline",
                    unit_id=s.id,
                )

    with run.check("content.duplicates", 1):
        for i, a in enumerate(deck.slides):
            for b in deck.slides[i + 1 :]:
                if a.headline and b.headline and similar(a.headline, b.headline) >= 0.9:
                    run.finding(
                        "content.duplicates",
                        Dimension.content,
                        Severity.major,
                        f"slides '{a.headline}' and '{b.headline}' repeat the same message",
                        unit_id=b.id,
                        duplicate_of=a.id,
                    )

    with run.check("content.placeholder_text", 1):
        for s in deck.slides:
            texts = [s.headline, s.key_message, *(_block_texts(s.blocks))]
            hit = next((t for t in texts if t and PLACEHOLDER_PATTERNS.search(t)), None)
            if hit:
                run.finding(
                    "content.placeholder_text",
                    Dimension.content,
                    Severity.critical,
                    f"placeholder text in plan: '{hit[:60]}'",
                    unit_id=s.id,
                )

    with run.check("pptx.density", 2):
        for s in deck.slides:
            for block in s.blocks:
                for kind, (attr, limit) in LIMITS.items():
                    if isinstance(block, kind) and len(getattr(block, attr)) > limit:
                        run.finding(
                            "pptx.density",
                            Dimension.layout,
                            Severity.major,
                            f"{attr} on slide '{s.headline}' exceed {limit} ({len(getattr(block, attr))})",
                            unit_id=s.id,
                            block=kind.__name__,
                            count=len(getattr(block, attr)),
                            limit=limit,
                        )

    with run.check("evidence.citations_resolve", 1):
        known = {c.id for c in dossier.claims} if dossier else set()
        for s in deck.slides:
            cited = set(s.claim_ids) | {cid for b in s.blocks for cid in block_claim_ids(b)}
            missing = sorted(cited - known)
            if missing:
                run.finding(
                    "evidence.citations_resolve",
                    Dimension.evidence,
                    Severity.critical,
                    f"slide cites unknown claims: {', '.join(missing[:5])}",
                    unit_id=s.id,
                    missing=missing,
                )

    check_uncited_figures(run, deck, dossier)


def _block_texts(blocks) -> list[str]:
    out: list[str] = []
    for b in blocks:
        for attr in ("text", "caption", "title", "attribution"):
            v = getattr(b, attr, None)
            if isinstance(v, str):
                out.append(v)
        for item in getattr(b, "items", []) or []:
            out.append(item.text)
        for col in getattr(b, "columns", []) or []:
            if isinstance(col, str):
                out.append(col)
            else:
                out += [col.heading, *col.points]
    return out


def check_uncited_figures(run: CheckRun, deck: DeckPlan, dossier: ResearchDossier | None) -> None:
    """With a dossier, quantitative statements and data visuals must cite claims (evidence.coverage)."""
    if dossier is None or not dossier.performed:
        return
    with run.check("evidence.coverage", 1):
        for s in deck.slides:
            slide_cites = bool(s.claim_ids)
            for block in s.blocks:
                needs = isinstance(block, (ChartBlock, KPIBlock, TableBlock))
                items = getattr(block, "items", None) or getattr(block, "metrics", None)
                if items:
                    for item in items:
                        text = getattr(item, "text", None) or f"{getattr(item, 'value', '')} {item.label}"
                        if (_FIGURE.search(text) or needs) and not (
                            item.claim_ids or block.claim_ids or slide_cites
                        ):
                            run.finding(
                                "evidence.coverage",
                                Dimension.evidence,
                                Severity.major,
                                f"uncited figure on slide '{s.headline}': '{text[:60]}'",
                                unit_id=s.id,
                            )
                elif needs and not (block.claim_ids or slide_cites):
                    run.finding(
                        "evidence.coverage",
                        Dimension.evidence,
                        Severity.major,
                        f"{type(block).__name__.removesuffix('Block').lower()} on slide '{s.headline}' "
                        "cites no evidence",
                        unit_id=s.id,
                    )
