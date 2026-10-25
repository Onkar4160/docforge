"""Clone-based template rendering for templates whose design lives on the sample slides (ADR-019).

Each output slide starts as a copy of the best sample slide for its archetype: backgrounds, artwork, panels
and logos are kept; sample text, charts and tables are dropped; the title box keeps its styling for our
headline; the area the sample body text used becomes the content region. Sample slides are removed at the
end, so only cloned slides remain.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field

from docforge.layout.backdrop import is_dark
from docforge.layout.text import EMU_PER_INCH
from docforge.models.ir import SlideArchetype, SlidePlan
from docforge.models.template import Box, SlideBase, TemplateManifest
from docforge.render.pptx.canvas import Rect
from docforge.render.pptx.composer import Frame

_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL_ATTRS = (f"{{{_R}}}embed", f"{{{_R}}}link", f"{{{_R}}}id", f"{{{_R}}}pict")
# Archetypes that lay content out side by side need a wide area; lists need a medium one.
_WIDE = {
    SlideArchetype.chart,
    SlideArchetype.table,
    SlideArchetype.timeline,
    SlideArchetype.process,
    SlideArchetype.comparison,
    SlideArchetype.kpi,
    SlideArchetype.references,
}
_MEDIUM = {SlideArchetype.two_column, SlideArchetype.agenda}


def _in(v: int) -> float:
    return v / EMU_PER_INCH


def assign_bases(archetypes: list[SlideArchetype], manifest: TemplateManifest) -> list[SlideBase]:
    """Deterministic base per slide: cover/closing by role, content bases rotated for variety."""
    info = manifest.pptx
    full = info.slide_width * info.slide_height
    bases = info.slide_bases
    covers = [b for b in bases if b.kind == "cover"]
    closings = [b for b in bases if b.kind == "closing"]
    sections = [b for b in bases if b.kind == "section"]
    contents = sorted((b for b in bases if b.kind == "content"), key=lambda b: -b.score)
    light = [b for b in contents if not is_dark(b.region_color)]
    contents = light or contents  # our body text is dark; dark panels are used only if nothing else exists
    sw = info.slide_width

    def roomy(b: SlideBase, area: float, width: float) -> bool:
        return b.region is not None and b.region.area() / full >= area and b.region.w / sw >= width

    contents = [b for b in contents if roomy(b, 0.1, 0.3)] or contents
    large = [b for b in contents if roomy(b, 0.18, 0.45)] or contents
    wide = [b for b in large if roomy(b, 0.2, 0.55)] or large
    photo = [b for b in contents if b.photo_shapes or b.frame_shapes] or contents
    fallback = (contents or covers or bases)[0]
    counters = {"light": 0, "heavy": 0, "wide": 0, "photo": 0, "section": 0}
    out: list[SlideBase] = []

    def rotate(pool: list[SlideBase], key: str) -> SlideBase:
        pick = pool[counters[key] % len(pool)]
        if out and pick.index == out[-1].index and len(pool) > 1:  # never the same design twice in a row
            counters[key] += 1
            pick = pool[counters[key] % len(pool)]
        counters[key] += 1
        return pick

    for a in archetypes:
        if a == SlideArchetype.title:
            out.append(covers[0] if covers else fallback)
        elif a == SlideArchetype.closing:
            out.append((closings or covers or [fallback])[0])
        elif a == SlideArchetype.section:
            out.append(rotate(sections, "section") if sections else (covers or [fallback])[0])
        elif a in (SlideArchetype.image_text, SlideArchetype.quote):
            out.append(rotate(photo, "photo"))
        elif a in _WIDE:
            out.append(rotate(wide, "wide") if wide else fallback)
        elif a in _MEDIUM:
            out.append(rotate(large, "heavy") if large else fallback)
        else:
            out.append(rotate(contents, "light") if contents else fallback)
    return out


def _copy_shape(src_part, dst_part, element):
    el = deepcopy(element)
    for node in el.iter():
        for attr in _REL_ATTRS:
            rid = node.get(attr)
            if not rid or rid not in src_part.rels:
                continue
            rel = src_part.rels[rid]
            if rel.is_external:
                new = dst_part.relate_to(rel.target_ref, rel.reltype, is_external=True)
            else:
                new = dst_part.relate_to(rel.target_part, rel.reltype)
            node.set(attr, new)
    return el


@dataclass
class CloneContext:
    manifest: TemplateManifest
    sources: list  # original sample slides
    plan: list[SlideBase] = field(default_factory=list)
    _cursor: int = 0
    _sample_ids: list = field(default_factory=list)
    _title_geometry: dict = field(default_factory=dict)

    @classmethod
    def open(cls, prs, manifest: TemplateManifest) -> CloneContext:
        return cls(manifest=manifest, sources=list(prs.slides), _sample_ids=list(prs.slides._sldIdLst))

    def prepare(self, archetypes: list[SlideArchetype]) -> None:
        self.plan = assign_bases(archetypes, self.manifest)
        self._cursor = 0

    # ---------------------------------------------------------------- per slide

    def add_slide(self, prs, archetype: SlideArchetype, slide_plan: SlidePlan | None):
        if self._cursor < len(self.plan):
            base = self.plan[self._cursor]
        else:  # slides added after planning (e.g. the automatic references slide)
            base = assign_bases([archetype], self.manifest)[0]
        self._cursor += 1
        src = self.sources[base.index]
        slide = prs.slides.add_slide(src.slide_layout)
        tree = slide.shapes._spTree
        for shape in list(slide.shapes):  # layout placeholders: the clone brings its own shapes
            tree.remove(shape._element)
        bg = src._element.cSld.bg
        if bg is not None:
            slide._element.cSld.insert(0, _copy_shape(src.part, slide.part, bg))
        drop = set(base.remove_shapes)
        kept: list[int] = []
        for i, shape in enumerate(src.shapes):
            if i in drop:
                continue
            tree.append(_copy_shape(src.part, slide.part, shape._element))
            kept.append(i)
        shapes = list(slide.shapes)
        by_index = dict(zip(kept, shapes, strict=True))
        title_shape = by_index.get(base.title_shape) if base.title_shape is not None else None
        if title_shape is not None:
            self._widen_title(title_shape, base)
        slots = {
            "title": by_index.get(base.title_shape) if base.title_shape is not None else None,
            "subtitle": by_index.get(base.subtitle_shape) if base.subtitle_shape is not None else None,
            "photos": [by_index[i] for i in base.photo_shapes if i in by_index],
            "frames": [by_index[i] for i in base.frame_shapes if i in by_index],
            "sample_title": base.title_text,
        }
        if slots["subtitle"] is not None and title_shape is not None:
            self._widen_like(slots["subtitle"], title_shape)
        return slide, self._frame(base), slots

    def _widen_title(self, shape, base: SlideBase) -> None:
        info = self.manifest.pptx
        sw, sh = info.slide_width, info.slide_height
        margin = int(sw * 0.04)
        x, y, w, h = int(shape.left), int(shape.top), int(shape.width), int(shape.height)
        # Grow within the title's own column and the content area below it, never across panels.
        region = base.region
        target_w = min(max(w, region.w if region else int(sw * 0.6)), sw - 2 * margin)
        algn = shape.text_frame.paragraphs[0].alignment if shape.has_text_frame else None
        name = getattr(algn, "name", "") or ""
        if name == "CENTER":
            nx = x + w // 2 - target_w // 2
        elif name == "RIGHT":
            nx = x + w - target_w
        else:
            nx = x
        lo = min(x, region.x) if region else margin
        hi = max(x + w, region.right) if region else sw - margin
        nx = min(max(nx, lo, margin), max(hi - target_w, margin))
        nh = h
        if base.kind == "content" and base.region is not None and base.region.y > y + h:
            nh = max(h, min(base.region.y - y - int(sh * 0.02), int(h * 1.8)))
        shape.left, shape.top, shape.width, shape.height = nx, y, target_w, nh
        self._title_geometry[base.index] = (nx, y, target_w, nh)

    def _widen_like(self, shape, title) -> None:
        """Subtitles get the title's width (sample subtitles are sized to one short line)."""
        sw = self.manifest.pptx.slide_width
        margin = int(sw * 0.04)
        if int(shape.width) < int(title.width):
            width = min(int(title.width), sw - 2 * margin)
            center = int(shape.left) + int(shape.width) // 2
            shape.width = width
            shape.left = min(max(margin, center - width // 2), sw - margin - width)

    def _frame(self, base: SlideBase) -> Frame:
        info = self.manifest.pptx
        w, h = _in(info.slide_width), _in(info.slide_height)
        scale = h / 7.5
        geo = self._title_geometry.get(base.index)
        if geo is not None:
            headline = Rect(*(_in(v) for v in geo))
        else:
            headline = Rect(0.6 * scale, 0.42 * scale, w - 1.2 * scale, 1.2 * scale)
        if base.region is not None:
            r: Box = base.region
            body = Rect(_in(r.x), _in(r.y), _in(r.w), _in(r.h))
        else:
            top = headline.y + headline.h + 0.3 * scale
            body = Rect(headline.x, top, headline.w, max(1.0, h - top - 0.8 * scale))
        margin = max(0.3 * scale, min(headline.x, body.x))
        return Frame(w=w, h=h, m=margin, headline=headline, body=body, footer_y=h - 0.45 * scale, scale=scale)

    def finish_slide(self, slide, slots: dict | None = None) -> None:
        """Drop placeholders that stayed empty (unfilled photo frames would show prompts in edit mode)."""
        for ph in list(slide.placeholders):
            empty = not ph.has_text_frame or not ph.text_frame.text.strip()
            if empty:
                ph._element.getparent().remove(ph._element)
        slots = slots or {}
        for key in ("title", "subtitle"):
            shape = slots.get(key)
            # A slot our content did not use still holds the template's sample words.
            if shape is not None and not shape.name.startswith("content:"):
                shape._element.getparent().remove(shape._element)

    def close(self, prs) -> None:
        id_list = prs.slides._sldIdLst
        for sld_id in self._sample_ids:
            prs.part.drop_rel(sld_id.rId)
            id_list.remove(sld_id)
