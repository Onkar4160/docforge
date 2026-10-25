"""DeckPlan → editable PPTX (Stage 8). Deterministic for a given plan, tokens and dossier."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pptx import Presentation

from docforge.models.design import DesignTokens
from docforge.models.evidence import ResearchDossier
from docforge.models.ir import DeckPlan
from docforge.models.template import TemplateManifest
from docforge.render.pptx.canvas import CanvasLog, inch
from docforge.render.pptx.clone import CloneContext
from docforge.render.pptx.composer import DeckComposer, H, W
from docforge.render.pptx.template import TemplateContext
from docforge.template.pptx_analyzer import analyze_pptx


@dataclass
class RenderResult:
    path: Path
    slide_count: int
    log: CanvasLog


def render_deck(
    deck: DeckPlan,
    tokens: DesignTokens,
    out_path: Path,
    *,
    dossier: ResearchDossier | None = None,
    asset_resolver: Callable[[str], Path] | None = None,
    template: Path | None = None,
    manifest: TemplateManifest | None = None,
) -> RenderResult:
    context = None
    if template is not None:
        prs = Presentation(str(template))
        manifest = manifest or analyze_pptx(template)
        if manifest.pptx.design_mode == "slides":
            context = CloneContext.open(prs, manifest)
        else:
            context = TemplateContext.open(prs, manifest)
    else:
        prs = Presentation()
        prs.slide_width = inch(W)
        prs.slide_height = inch(H)
    props = prs.core_properties
    props.title = deck.title[:255]
    props.subject = (deck.subtitle or "")[:255]
    props.author = "DocForge"
    props.last_modified_by = "DocForge"

    log = DeckComposer(tokens, dossier, asset_resolver, template=context).compose(prs, deck)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(out_path))
    return RenderResult(path=out_path, slide_count=len(prs.slides), log=log)
