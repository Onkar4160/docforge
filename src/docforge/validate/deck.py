"""Render → validate → repair loop for decks (FR-VAL-1/2/3)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from docforge.core.ids import new_id
from docforge.models.design import DesignTokens
from docforge.models.evidence import ResearchDossier
from docforge.models.intent import LengthUnit, OutputSpec
from docforge.models.ir import DeckPlan
from docforge.models.quality import Finding, FindingStatus, QualityReport
from docforge.models.template import TemplateManifest
from docforge.render.pptx import render_deck
from docforge.validate.common import CheckRun
from docforge.validate.plan_checks import check_deck_plan
from docforge.validate.pptx_checks import check_pptx_file, check_template_fidelity
from docforge.validate.repair import repair_deck


@dataclass
class DeckBuild:
    deck: DeckPlan
    path: Path
    report: QualityReport


def validate_deck_file(
    path: Path,
    deck: DeckPlan,
    spec: OutputSpec | None,
    dossier: ResearchDossier | None,
    libreoffice: Path | None,
    manifest: TemplateManifest | None = None,
) -> CheckRun:
    run = CheckRun()
    check_deck_plan(run, deck, spec, dossier)
    fonts = (manifest.theme.major_font, manifest.theme.minor_font) if manifest else (None, None)
    check_pptx_file(run, path, [s.id for s in deck.slides], libreoffice=libreoffice, theme_fonts=fonts)
    if manifest is not None:
        explicit_fonts = {
            font
            for style in (deck.style, *(slide.style for slide in deck.slides))
            for font in (style.heading_font, style.body_font)
            if font
        }
        check_template_fidelity(run, path, manifest, allowed_fonts=explicit_fonts)
    return run


def build_deck(
    deck: DeckPlan,
    tokens: DesignTokens,
    out_dir: Path,
    *,
    spec: OutputSpec | None,
    dossier: ResearchDossier | None,
    max_iterations: int,
    libreoffice: Path | None,
    artifact_id: str = "",
    version: int = 1,
    asset_resolver: Callable[[str], Path] | None = None,
    template: Path | None = None,
    manifest: TemplateManifest | None = None,
) -> DeckBuild:
    fixed_length = bool(spec and spec.length.explicit and spec.length.unit == LengthUnit.slides)
    corrected: list[Finding] = []
    current = deck
    iteration = 0
    while True:
        path = out_dir / f"deck-r{iteration}.pptx"
        render_deck(
            current,
            tokens,
            path,
            dossier=dossier,
            asset_resolver=asset_resolver,
            template=template,
            manifest=manifest,
        )
        run = validate_deck_file(
            path, current, spec, dossier, libreoffice, manifest=manifest if template else None
        )
        if iteration >= max_iterations:
            break
        repaired, actions = repair_deck(current, run.findings, allow_growth=not fixed_length)
        if not actions:
            break
        by_id = {f.id: f for f in run.findings}
        for action in actions:
            original = by_id[action.finding_id]
            corrected.append(
                original.model_copy(
                    update={"status": FindingStatus.corrected, "repair_action": action.action}
                )
            )
        current = repaired
        iteration += 1

    remaining = [f.model_copy(update={"status": FindingStatus.unresolved}) for f in run.findings]
    still_open = {(f.check_id, f.unit_id) for f in remaining}
    # A correction only counts if the same problem is gone from the final render.
    confirmed = [f for f in corrected if (f.check_id, f.unit_id) not in still_open]
    report = QualityReport(
        id=new_id("report"),
        artifact_id=artifact_id,
        version=version,
        iterations=iteration,
        checks=run.checks,
        findings=confirmed + remaining,
    ).finalize()
    return DeckBuild(deck=current, path=path, report=report)
