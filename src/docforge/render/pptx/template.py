"""Render on top of a user's PPTX template (ADR-007, FR-PPTX-2/7).

The template package is kept (masters, layouts, theme, media); sample slides are removed; each new slide
uses the best layout for its archetype; branding pictures that lived on sample slides are re-applied.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from pptx.util import Emu

from docforge.layout.text import EMU_PER_INCH
from docforge.models.ir import SlideArchetype
from docforge.models.template import ElementKind, ElementRole, LayoutArchetype, TemplateManifest
from docforge.render.pptx.canvas import Rect
from docforge.render.pptx.composer import Frame

_PREFS: dict[SlideArchetype, tuple[LayoutArchetype, ...]] = {
    SlideArchetype.title: (LayoutArchetype.title,),
    SlideArchetype.section: (LayoutArchetype.section, LayoutArchetype.title_only, LayoutArchetype.title),
    SlideArchetype.closing: (
        LayoutArchetype.closing,
        LayoutArchetype.title,
        LayoutArchetype.section,
        LayoutArchetype.title_only,
    ),
}
_CONTENT_PREFS = (
    LayoutArchetype.title_only,
    LayoutArchetype.content,
    LayoutArchetype.two_column,
    LayoutArchetype.comparison,
    LayoutArchetype.image_text,
    LayoutArchetype.other,
    LayoutArchetype.blank,
)


def _inches(v: int) -> float:
    return v / EMU_PER_INCH


@dataclass
class BrandingPicture:
    blob: bytes
    x: int
    y: int
    w: int
    h: int
    name: str


@dataclass
class TemplateContext:
    manifest: TemplateManifest
    layouts: dict[str, object]  # manifest layout id -> python-pptx SlideLayout
    branding: list[BrandingPicture] = field(default_factory=list)

    @classmethod
    def open(cls, prs, manifest: TemplateManifest) -> TemplateContext:
        """Index layouts, capture branding pictures, then remove all sample slides from ``prs``."""
        layouts = {
            f"m{m}l{lay}": layout
            for m, master in enumerate(prs.slide_masters)
            for lay, layout in enumerate(master.slide_layouts)
        }
        branding: list[BrandingPicture] = []
        seen: set[tuple[int, int, int]] = set()
        branded_names = {
            (inv.index, e.name)
            for inv in manifest.pptx.sample_slides
            for e in inv.elements
            if e.role == ElementRole.branding and e.kind == ElementKind.picture
        }
        for index, slide in enumerate(prs.slides):
            for shape in slide.shapes:
                if (index, shape.name) not in branded_names:
                    continue
                key = (int(shape.left) // 91440, int(shape.top) // 91440, int(shape.width) // 91440)
                if key in seen:
                    continue
                seen.add(key)
                branding.append(
                    BrandingPicture(
                        shape.image.blob,
                        int(shape.left),
                        int(shape.top),
                        int(shape.width),
                        int(shape.height),
                        shape.name,
                    )
                )
        id_list = prs.slides._sldIdLst
        for sld_id in list(id_list):
            prs.part.drop_rel(sld_id.rId)  # unreachable slide parts are not written on save
            id_list.remove(sld_id)
        return cls(manifest, layouts, branding)

    # ---------------------------------------------------------------- layout choice

    def layout_for(self, archetype: SlideArchetype):
        specs = self.manifest.pptx.layouts
        prefs = _PREFS.get(archetype, _CONTENT_PREFS)
        for wanted in prefs:
            for spec in specs:
                if spec.archetype == wanted:
                    return self.layouts[spec.id]
        titled = next(
            (s for s in specs if any(p.type in ("title", "center_title") for p in s.placeholders)), None
        )
        return self.layouts[(titled or specs[0]).id]

    def _spec(self, layout):
        return next(s for s in self.manifest.pptx.layouts if self.layouts[s.id] is layout)

    def frame_for(self, layout) -> Frame:
        info = self.manifest.pptx
        w, h = _inches(info.slide_width), _inches(info.slide_height)
        scale = h / 7.5  # type scales with slide height (a 4:3 slide is as tall as 16:9)
        spec = self._spec(layout)
        title = next((p for p in spec.placeholders if p.type in ("title", "center_title") and p.bbox), None)
        body = next((p for p in spec.placeholders if p.type in ("body", "object") and p.bbox), None)
        margin = 0.6 * scale
        if title is not None:
            b = title.bbox
            headline = Rect(_inches(b.x), _inches(b.y), _inches(b.w), _inches(b.h))
        else:
            headline = Rect(margin, 0.42 * scale, w - 2 * margin, 1.2 * scale)
        if body is not None and spec.archetype == LayoutArchetype.content:
            b = body.bbox
            region = Rect(_inches(b.x), _inches(b.y), _inches(b.w), _inches(b.h))
        else:
            top = headline.bottom_y + 0.3 * scale
            region = Rect(headline.x, top, headline.w, max(1.0, h - top - 0.75 * scale))
        return Frame(
            w=w, h=h, m=headline.x, headline=headline, body=region, footer_y=h - 0.5 * scale, scale=scale
        )

    # ---------------------------------------------------------------- per-slide finishing

    def prepare(self, archetypes) -> None:
        """Layouts are chosen per slide; nothing to plan ahead."""

    def add_slide(self, prs, archetype: SlideArchetype, slide_plan):
        layout = self.layout_for(archetype)
        slide = prs.slides.add_slide(layout)
        subtitle = next(
            (
                ph
                for ph in slide.placeholders
                if ph.placeholder_format.idx != 0 and ph.has_text_frame and not ph.text_frame.text
            ),
            None,
        )
        return (
            slide,
            self.frame_for(layout),
            {"title": slide.shapes.title, "subtitle": subtitle, "photos": []},
        )

    def close(self, prs) -> None:
        """Sample slides were removed when the template was opened."""

    def finish_slide(self, slide, slots: dict | None = None) -> None:
        """Remove unused placeholders (empty ones render as prompts) and re-apply branding pictures."""
        for ph in list(slide.placeholders):
            if not ph.has_text_frame or not ph.text_frame.text.strip():
                ph._element.getparent().remove(ph._element)
        for n, pic in enumerate(self.branding, start=1):
            shape = slide.shapes.add_picture(
                io.BytesIO(pic.blob), Emu(pic.x), Emu(pic.y), Emu(pic.w), Emu(pic.h)
            )
            shape.name = f"branding:{n}"
            shape._element.nvPicPr.cNvPr.set("descr", "Logo")
