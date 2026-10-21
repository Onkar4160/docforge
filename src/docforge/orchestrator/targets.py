"""Target resolver: maps user locators to unit IDs in the IR (Stage 4 / 11, FR-CONV-3, FR-EDIT-1)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from docforge.models.intent import ChangeRequest
from docforge.models.ir import DeckPlan, DocumentPlan, SlidePlan, WorkbookPlan

if TYPE_CHECKING:
    from docforge.models.ir import ArtifactIR

_ORDINALS = {
    "first": 1,
    "1st": 1,
    "second": 2,
    "2nd": 2,
    "third": 3,
    "3rd": 3,
    "fourth": 4,
    "4th": 4,
    "fifth": 5,
    "5th": 5,
    "sixth": 6,
    "6th": 6,
    "seventh": 7,
    "7th": 7,
    "eighth": 8,
    "8th": 8,
    "ninth": 9,
    "9th": 9,
    "tenth": 10,
    "10th": 10,
}

_SLIDE_PATTERN = re.compile(
    r"\b(?:slide|page)\s*#?\s*(\d+)\b|\b(" + "|".join(_ORDINALS.keys()) + r")\s+(?:slide|page)\b",
    re.IGNORECASE,
)
_SECTION_PATTERN = re.compile(
    r"\b(?:section|heading|part)\s*#?\s*(\d+)\b|\b(" + "|".join(_ORDINALS.keys()) + r")\s+(?:section|part)\b",
    re.IGNORECASE,
)
_SHEET_PATTERN = re.compile(
    r"\b(?:sheet|tab)\s*#?\s*(\d+)\b|\b(" + "|".join(_ORDINALS.keys()) + r")\s+(?:sheet|tab)\b",
    re.IGNORECASE,
)
_QUOTED_PATTERN = re.compile(r"['\"]([^'\"]{2,40})['\"]")


@dataclass
class ResolvedTarget:
    unit_id: str
    label: str
    kind: str  # "slide" | "section" | "sheet"
    confidence: float = 1.0


@dataclass
class TargetResolutionResult:
    targets: list[ResolvedTarget] = field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str | None = None
    options: list[str] = field(default_factory=list)


def _extract_index_from_text(text: str, pattern: re.Pattern) -> int | None:
    match = pattern.search(text)
    if not match:
        return None
    num_str, ord_str = match.groups()
    if num_str:
        return int(num_str)
    if ord_str:
        return _ORDINALS.get(ord_str.lower())
    return None


def resolve_targets(
    ir: ArtifactIR, change: ChangeRequest | None, message_text: str
) -> TargetResolutionResult:
    """Resolve which unit(s) in the IR are targeted by the change request or user message."""
    search_texts = [message_text]
    if change and change.instruction:
        search_texts.append(change.instruction)
    combined_text = " ".join(search_texts).strip()

    if isinstance(ir, DeckPlan):
        return _resolve_deck_targets(ir, change, combined_text)
    if isinstance(ir, DocumentPlan):
        return _resolve_document_targets(ir, change, combined_text)
    if isinstance(ir, WorkbookPlan):
        return _resolve_workbook_targets(ir, change, combined_text)
    return TargetResolutionResult()


# ---------------------------------------------------------------- Deck targets


def _resolve_deck_targets(deck: DeckPlan, change: ChangeRequest | None, text: str) -> TargetResolutionResult:
    total_slides = len(deck.slides)
    if total_slides == 0:
        return TargetResolutionResult()

    # 1. Check if change.scope has explicit targets already resolved
    if change and change.scope and change.scope.targets:
        known_ids = {s.id: s for s in deck.slides}
        resolved = []
        for t in change.scope.targets:
            if t.resolved_unit_id and t.resolved_unit_id in known_ids:
                s = known_ids[t.resolved_unit_id]
                resolved.append(ResolvedTarget(unit_id=s.id, label=s.headline, kind="slide"))
            elif t.locator:
                idx = _extract_index_from_text(t.locator, _SLIDE_PATTERN)
                if idx is not None and 1 <= idx <= total_slides:
                    s = deck.slides[idx - 1]
                    resolved.append(ResolvedTarget(unit_id=s.id, label=s.headline, kind="slide"))
        if resolved:
            return TargetResolutionResult(targets=resolved)

    # 2. Match numeric / ordinal index in text (e.g. "slide 3", "third slide", "slide #2")
    idx = _extract_index_from_text(text, _SLIDE_PATTERN)
    if idx is not None:
        if 1 <= idx <= total_slides:
            s = deck.slides[idx - 1]
            return TargetResolutionResult(
                targets=[ResolvedTarget(unit_id=s.id, label=s.headline, kind="slide")]
            )
        # Out of bounds index
        options = [f"Slide {i}: “{s.headline}”" for i, s in enumerate(deck.slides, 1)]
        q = f"The presentation has {total_slides} slides. Which slide would you like to edit?"
        return TargetResolutionResult(
            clarification_needed=True,
            clarification_question=q,
            options=options[:6],
        )

    # Check for "last slide"
    if re.search(r"\b(last|closing|final)\s+(?:slide|page)\b", text, re.IGNORECASE):
        s = deck.slides[-1]
        return TargetResolutionResult(targets=[ResolvedTarget(unit_id=s.id, label=s.headline, kind="slide")])

    # Check for "first slide" / "title slide" / "cover"
    if re.search(r"\b(first|title|cover)\s+(?:slide|page)\b", text, re.IGNORECASE):
        s = deck.slides[0]
        return TargetResolutionResult(targets=[ResolvedTarget(unit_id=s.id, label=s.headline, kind="slide")])

    # 3. Match quoted strings against headlines
    quoted = _QUOTED_PATTERN.findall(text)
    for q in quoted:
        q_lower = q.lower().strip()
        matched = [s for s in deck.slides if q_lower in s.headline.lower() or q_lower in s.purpose.lower()]
        if len(matched) == 1:
            return TargetResolutionResult(
                targets=[ResolvedTarget(unit_id=matched[0].id, label=matched[0].headline, kind="slide")]
            )

    # 4. Keyword matching against slide headlines & archetypes
    stop_words = {
        "make",
        "change",
        "edit",
        "slide",
        "slides",
        "please",
        "point",
        "points",
        "bullet",
        "bullets",
        "update",
        "better",
        "content",
        "text",
        "words",
        "something",
        "things",
        "about",
        "with",
        "this",
        "that",
        "these",
        "those",
        "have",
        "from",
        "more",
        "less",
        "some",
        "only",
        "other",
    }
    clean_words = [w.lower() for w in re.findall(r"\b\w{3,}\b", text) if w.lower() not in stop_words]
    if len(clean_words) >= 1:
        scored: list[tuple[int, SlidePlan]] = []
        for s in deck.slides:
            haystack = f"{s.headline} {s.purpose} {s.archetype.value} {s.key_message}".lower()
            score = sum(1 for w in clean_words if re.search(rf"\b{re.escape(w)}\b", haystack))
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Require clear leader: score >= 2 or, if score == 1, exactly 1 slide matched
        if scored:
            best_score, best_slide = scored[0]
            if best_score >= 2:
                # If runner up has same score, ambiguous
                if len(scored) > 1 and scored[1][0] == best_score:
                    pass
                else:
                    return TargetResolutionResult(
                        targets=[
                            ResolvedTarget(
                                unit_id=best_slide.id, label=best_slide.headline, kind="slide", confidence=0.8
                            )
                        ]
                    )
            elif best_score == 1 and len(scored) == 1 and len(clean_words) >= 2:
                return TargetResolutionResult(
                    targets=[
                        ResolvedTarget(
                            unit_id=best_slide.id, label=best_slide.headline, kind="slide", confidence=0.7
                        )
                    ]
                )

    # If ambiguous, prompt clarification
    options = [f"Slide {i}: “{s.headline}”" for i, s in enumerate(deck.slides[:6], 1)]
    return TargetResolutionResult(
        clarification_needed=True,
        clarification_question="Which slide would you like to make changes to?",
        options=options,
    )


# ---------------------------------------------------------------- Document targets


def _resolve_document_targets(
    doc: DocumentPlan, change: ChangeRequest | None, text: str
) -> TargetResolutionResult:
    all_secs = doc.all_sections()
    total_secs = len(all_secs)
    if total_secs == 0:
        return TargetResolutionResult()

    # 1. Scope targets
    if change and change.scope and change.scope.targets:
        known_ids = {s.id: s for s in all_secs}
        resolved = []
        for t in change.scope.targets:
            if t.resolved_unit_id and t.resolved_unit_id in known_ids:
                s = known_ids[t.resolved_unit_id]
                resolved.append(ResolvedTarget(unit_id=s.id, label=s.heading, kind="section"))
            elif t.locator:
                idx = _extract_index_from_text(t.locator, _SECTION_PATTERN)
                if idx is not None and 1 <= idx <= total_secs:
                    s = all_secs[idx - 1]
                    resolved.append(ResolvedTarget(unit_id=s.id, label=s.heading, kind="section"))
        if resolved:
            return TargetResolutionResult(targets=resolved)

    # 2. Numeric / ordinal index in text (e.g. "section 2", "second section")
    idx = _extract_index_from_text(text, _SECTION_PATTERN)
    if idx is not None:
        if 1 <= idx <= total_secs:
            s = all_secs[idx - 1]
            return TargetResolutionResult(
                targets=[ResolvedTarget(unit_id=s.id, label=s.heading, kind="section")]
            )
        options = [f"Section {i}: “{s.heading}”" for i, s in enumerate(all_secs, 1)]
        q = f"The document has {total_secs} sections. Which section would you like to edit?"
        return TargetResolutionResult(
            clarification_needed=True,
            clarification_question=q,
            options=options[:6],
        )

    # Check for "executive summary"
    if re.search(r"\bexecutive\s+summary\b", text, re.IGNORECASE):
        matched = [s for s in all_secs if "executive" in s.heading.lower()]
        if matched:
            return TargetResolutionResult(
                targets=[ResolvedTarget(unit_id=matched[0].id, label=matched[0].heading, kind="section")]
            )

    # Check for "introduction" / "conclusion"
    for keyword in ("introduction", "conclusion", "methodology", "background", "recommendations"):
        if re.search(rf"\b{keyword}\b", text, re.IGNORECASE):
            matched = [s for s in all_secs if keyword in s.heading.lower()]
            if len(matched) == 1:
                return TargetResolutionResult(
                    targets=[ResolvedTarget(unit_id=matched[0].id, label=matched[0].heading, kind="section")]
                )

    # 3. Match quoted strings against headings
    quoted = _QUOTED_PATTERN.findall(text)
    for q in quoted:
        q_lower = q.lower().strip()
        matched = [s for s in all_secs if q_lower in s.heading.lower()]
        if len(matched) == 1:
            return TargetResolutionResult(
                targets=[ResolvedTarget(unit_id=matched[0].id, label=matched[0].heading, kind="section")]
            )

    # 4. Keyword matching
    clean_words = [
        w.lower()
        for w in re.findall(r"\b\w{4,}\b", text)
        if w.lower() not in {"make", "change", "edit", "section", "please", "document", "update", "write"}
    ]
    if clean_words:
        scored = []
        for s in all_secs:
            haystack = f"{s.heading} {s.purpose}".lower()
            score = sum(1 for w in clean_words if w in haystack)
            if score > 0:
                scored.append((score, s))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] >= 2:
            best = scored[0][1]
            return TargetResolutionResult(
                targets=[ResolvedTarget(unit_id=best.id, label=best.heading, kind="section", confidence=0.8)]
            )
        if len(scored) == 1:
            best = scored[0][1]
            return TargetResolutionResult(
                targets=[ResolvedTarget(unit_id=best.id, label=best.heading, kind="section", confidence=0.7)]
            )

    options = [f"Section {i}: “{s.heading}”" for i, s in enumerate(all_secs[:6], 1)]
    return TargetResolutionResult(
        clarification_needed=True,
        clarification_question="Which section of the document would you like to edit?",
        options=options,
    )


# ---------------------------------------------------------------- Workbook targets


def _resolve_workbook_targets(
    wb: WorkbookPlan, change: ChangeRequest | None, text: str
) -> TargetResolutionResult:
    total_sheets = len(wb.sheets)
    if total_sheets == 0:
        return TargetResolutionResult()

    # 1. Scope targets
    if change and change.scope and change.scope.targets:
        known_ids = {s.id: s for s in wb.sheets}
        resolved = []
        for t in change.scope.targets:
            if t.resolved_unit_id and t.resolved_unit_id in known_ids:
                s = known_ids[t.resolved_unit_id]
                resolved.append(ResolvedTarget(unit_id=s.id, label=s.name, kind="sheet"))
            elif t.locator:
                matched = [s for s in wb.sheets if s.name.lower() == t.locator.lower().strip()]
                if matched:
                    resolved.append(
                        ResolvedTarget(unit_id=matched[0].id, label=matched[0].name, kind="sheet")
                    )
        if resolved:
            return TargetResolutionResult(targets=resolved)

    # 2. Numeric / ordinal index (e.g. "sheet 2")
    idx = _extract_index_from_text(text, _SHEET_PATTERN)
    if idx is not None:
        if 1 <= idx <= total_sheets:
            s = wb.sheets[idx - 1]
            return TargetResolutionResult(targets=[ResolvedTarget(unit_id=s.id, label=s.name, kind="sheet")])
        options = [f"Sheet {i}: “{s.name}”" for i, s in enumerate(wb.sheets, 1)]
        q = f"The workbook has {total_sheets} sheets. Which sheet would you like to edit?"
        return TargetResolutionResult(
            clarification_needed=True,
            clarification_question=q,
            options=options[:6],
        )

    # 3. Match by sheet role or sheet name in text
    for s in wb.sheets:
        if s.name.lower() in text.lower():
            return TargetResolutionResult(targets=[ResolvedTarget(unit_id=s.id, label=s.name, kind="sheet")])
        if s.role.value in text.lower():
            return TargetResolutionResult(targets=[ResolvedTarget(unit_id=s.id, label=s.name, kind="sheet")])

    options = [f"Sheet “{s.name}” ({s.role.value})" for s in wb.sheets]
    return TargetResolutionResult(
        clarification_needed=True,
        clarification_question="Which sheet would you like to make changes in?",
        options=options,
    )
