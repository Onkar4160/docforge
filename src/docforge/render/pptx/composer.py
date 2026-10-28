"""Compose slides from a DeckPlan on a generated design (no template) — FR-PPTX-1/3/4/5/6.

Each archetype has one method. When a slide lacks the block its archetype needs, it is composed
with the closest archetype that fits its content instead of rendering an empty frame.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from pptx.enum.shapes import MSO_SHAPE

from docforge.design.system import contrast_ratio, dark_color, readable_on
from docforge.layout.backdrop import color_under, is_dark
from docforge.layout.text import Para
from docforge.models.design import DesignTokens
from docforge.models.evidence import ResearchDossier
from docforge.models.ir import (
    BulletsBlock,
    CalloutBlock,
    ChartBlock,
    ComparisonBlock,
    DeckPlan,
    ImageBlock,
    KPIBlock,
    ParagraphBlock,
    ProcessBlock,
    QuoteBlock,
    SlideArchetype,
    SlidePlan,
    StyleSpec,
    TableBlock,
    TimelineBlock,
    block_claim_ids,
)
from docforge.render.pptx.canvas import (
    BulletPara,
    Canvas,
    CanvasLog,
    Rect,
    TextStyle,
    content_height,
    rgb,
    set_geometry,
)

if TYPE_CHECKING:
    from docforge.render.pptx.template import TemplateContext

W, H = 13.333, 7.5
M = 0.6
GAP = 0.35
HEADLINE = Rect(M, 0.42, W - 2 * M, 1.2)
BODY = Rect(M, 1.85, W - 2 * M, 4.75)
FOOTER_Y = 6.92

# Minimum sizes (QUALITY §2.2 and design floor): body 14pt, captions/footnotes 10pt, headlines 22pt.
MIN_BODY, MIN_CAPTION, MIN_HEADLINE = 14, 10, 22
MIN_TITLE = 24

CARD_PAD_X, CARD_PAD_Y = 0.3, 0.28

_DARK = {SlideArchetype.title, SlideArchetype.section, SlideArchetype.closing}


@dataclass(frozen=True)
class Frame:
    """Slide geometry in inches. Generated designs use DEFAULT_FRAME; templates derive one per layout."""

    w: float
    h: float
    m: float
    headline: Rect
    body: Rect
    footer_y: float
    scale: float = 1.0  # type scale relative to a 7.5-inch-tall slide


DEFAULT_FRAME = Frame(W, H, M, HEADLINE, BODY, FOOTER_Y)


@dataclass
class SourceRef:
    number: int
    label: str


def citation_numbers(deck: DeckPlan, dossier: ResearchDossier | None) -> dict[str, int]:
    """Number sources in order of first citation across the deck."""
    if dossier is None:
        return {}
    evidence = {e.id: e for e in dossier.evidence}
    numbers: dict[str, int] = {}
    for slide in deck.slides:
        for claim_id in _slide_claims(slide):
            claim = dossier.claim(claim_id)
            for evd in claim.evidence_ids if claim else []:
                src = evidence[evd].source_id if evd in evidence else None
                if src and src not in numbers:
                    numbers[src] = len(numbers) + 1
    return numbers


def _slide_claims(slide: SlidePlan) -> list[str]:
    ids = list(slide.claim_ids)
    for block in slide.blocks:
        ids.extend(sorted(block_claim_ids(block)))
    return list(dict.fromkeys(ids))


def lines_from_blocks(blocks) -> list[tuple[str, int | None]]:
    """Flatten any blocks into (text, bullet level) lines, for fallback compositions."""
    out: list[tuple[str, int | None]] = []
    for b in blocks:
        if isinstance(b, BulletsBlock):
            out += [(i.text, i.level) for i in b.items]
        elif isinstance(b, ParagraphBlock | CalloutBlock):
            out.append((b.text, None))
        elif isinstance(b, QuoteBlock):
            out.append((f"“{b.text}”" + (f" — {b.attribution}" if b.attribution else ""), None))
        elif isinstance(b, KPIBlock):
            out += [(f"{m.label}: {m.value}" + (f" ({m.delta})" if m.delta else ""), 0) for m in b.metrics]
        elif isinstance(b, TimelineBlock):
            out += [(" — ".join(x for x in (e.date, e.label, e.description) if x), 0) for e in b.events]
        elif isinstance(b, ProcessBlock):
            out += [(f"{s.title}: {s.description}" if s.description else s.title, 0) for s in b.steps]
        elif isinstance(b, ComparisonBlock):
            for col in b.columns:
                out.append((col.heading, 0))
                out += [(pt, 1) for pt in col.points]
    return out


def _first(slide: SlidePlan, kind):
    return next((b for b in slide.blocks if isinstance(b, kind)), None)


def effective_archetype(slide: SlidePlan) -> SlideArchetype:
    a = slide.archetype
    needs = {
        SlideArchetype.chart: ChartBlock,
        SlideArchetype.table: TableBlock,
        SlideArchetype.kpi: KPIBlock,
        SlideArchetype.timeline: TimelineBlock,
        SlideArchetype.process: ProcessBlock,
        SlideArchetype.quote: QuoteBlock,
    }
    if a in needs and _first(slide, needs[a]) is None:
        return SlideArchetype.bullets
    image = _first(slide, ImageBlock)
    if a == SlideArchetype.image_text:
        return a if image is not None and image.asset_path else SlideArchetype.bullets
    if a in (SlideArchetype.bullets, SlideArchetype.two_column):
        for kind, target in (
            (ChartBlock, SlideArchetype.chart),
            (TableBlock, SlideArchetype.table),
            (KPIBlock, SlideArchetype.kpi),
            (TimelineBlock, SlideArchetype.timeline),
            (ProcessBlock, SlideArchetype.process),
            (ComparisonBlock, SlideArchetype.comparison),
        ):
            if _first(slide, kind) is not None:
                return target
    return a


class DeckComposer:
    def __init__(
        self,
        tokens: DesignTokens,
        dossier: ResearchDossier | None = None,
        asset_resolver: Callable[[str], Path] | None = None,
        template: TemplateContext | None = None,
    ) -> None:
        self.assets = asset_resolver
        self.tpl = template
        self.base_tokens = tokens
        self.f = DEFAULT_FRAME
        self.slots: dict = {}
        self.t = tokens
        self.current_style = StyleSpec()
        self.pal = tokens.palette
        self.dark = dark_color(tokens)
        self.on_dark = readable_on(self.dark)
        self.dossier = dossier
        self.heading_font = tokens.fonts.heading
        self.body_font = tokens.fonts.body
        self.colors = [c for c in tokens.palette.accents[:4]] or [tokens.palette.primary]

    # ---------------------------------------------------------------- entry

    def compose(self, prs, deck: DeckPlan) -> CanvasLog:
        log = CanvasLog()
        self.numbers = citation_numbers(deck, self.dossier)
        self.section_count = 0
        if self.tpl is not None:
            self.tpl.prepare([effective_archetype(s) for s in deck.slides])
        for slide_plan in deck.slides:
            self._apply_style(self._merge_style(deck.style, slide_plan.style))
            archetype = effective_archetype(slide_plan)
            dark = archetype in _DARK
            if self.tpl is not None:
                slide, self.f, self.slots = self.tpl.add_slide(prs, archetype, slide_plan)
                canvas = Canvas(slide, log, scale=self.f.scale)
                bg_color = color_under(slide, (0, 0, int(prs.slide_width), int(prs.slide_height)))
                if bg_color and is_dark(bg_color) and not dark:
                    old_text = self.pal.text
                    self.pal = self.pal.model_copy(update={"text": readable_on(bg_color)})
                    try:
                        getattr(self, f"_{archetype.value}")(canvas, slide_plan, deck)
                        self._footer(canvas, slide_plan, len(prs.slides._sldIdLst))
                    finally:
                        self.pal = self.pal.model_copy(update={"text": old_text})
                elif dark:
                    self._template_structural(canvas, slide_plan, deck, archetype)
                else:
                    getattr(self, f"_{archetype.value}")(canvas, slide_plan, deck)
                    self._footer(canvas, slide_plan, len(prs.slides._sldIdLst))
                self._fill_photo(canvas, slide_plan)
                self.tpl.finish_slide(slide, self.slots)
            else:
                slide = prs.slides.add_slide(prs.slide_layouts[6])
                canvas = Canvas(slide, log)
                canvas.background(self.dark if dark else self.pal.background)
                getattr(self, f"_{archetype.value}")(canvas, slide_plan, deck)
                if not dark:
                    self._footer(canvas, slide_plan, len(prs.slides._sldIdLst))
            canvas.notes(slide_plan.notes)
        if self.numbers and not any(s.archetype == SlideArchetype.references for s in deck.slides):
            self._apply_style(deck.style)
            if self.tpl is not None:
                slide, self.f, self.slots = self.tpl.add_slide(prs, SlideArchetype.references, None)
                self._references(Canvas(slide, log, scale=self.f.scale), None, deck)
                self.tpl.finish_slide(slide, self.slots)
            else:
                canvas = Canvas(prs.slides.add_slide(prs.slide_layouts[6]), log)
                canvas.background(self.pal.background)
                self._references(canvas, None, deck)
        if self.tpl is not None:
            self.tpl.close(prs)
        return log

    @staticmethod
    def _merge_style(global_style: StyleSpec, slide_style: StyleSpec) -> StyleSpec:
        update = {}
        for field in ("heading_font", "body_font", "body_size_pt"):
            value = getattr(slide_style, field)
            if value is not None:
                update[field] = value
        heading_sizes = global_style.heading_sizes_pt.model_dump(exclude_none=True)
        heading_sizes.update(slide_style.heading_sizes_pt.model_dump(exclude_none=True))
        update["heading_sizes_pt"] = global_style.heading_sizes_pt.model_copy(update=heading_sizes)
        palette = dict(global_style.palette_overrides)
        palette.update(slide_style.palette_overrides)
        update["palette_overrides"] = palette
        return global_style.model_copy(update=update)

    def _apply_style(self, style: StyleSpec) -> None:
        self.current_style = style

        def _norm(c: str) -> str:
            c = c.strip().removeprefix("#")
            if len(c) == 3:
                c = "".join(ch * 2 for ch in c)
            return c.upper()

        palette_update = {
            key: _norm(value) if isinstance(value, str) else value
            for key, value in style.palette_overrides.items()
            if key not in {f"accent{i}" for i in range(1, 7)}
        }
        accents = list(self.base_tokens.palette.accents)
        for index in range(1, 7):
            color = style.palette_overrides.get(f"accent{index}")
            while color is not None and len(accents) < index:
                accents.append(accents[-1] if accents else self.base_tokens.palette.primary)
            if color is not None:
                accents[index - 1] = _norm(color) if isinstance(color, str) else color
        palette_update["accents"] = accents
        palette = self.base_tokens.palette.model_copy(update=palette_update)
        fonts = self.base_tokens.fonts.model_copy(
            update={
                key: value
                for key, value in {"heading": style.heading_font, "body": style.body_font}.items()
                if value is not None
            }
        )
        scale = self.base_tokens.type_scale.model_copy(
            update={
                key: value
                for key, value in {
                    **style.heading_sizes_pt.model_dump(exclude_none=True),
                    "body": style.body_size_pt,
                }.items()
                if value is not None
            }
        )
        self.t = self.base_tokens.model_copy(update={"palette": palette, "fonts": fonts, "type_scale": scale})
        self.pal = self.t.palette
        self.dark = dark_color(self.t)
        self.on_dark = readable_on(self.dark)
        self.heading_font = self.t.fonts.heading
        self.body_font = self.t.fonts.body
        self.colors = [c for c in self.t.palette.accents[:4]] or [self.t.palette.primary]

    def _template_structural(
        self, c: Canvas, s: SlidePlan, deck: DeckPlan, archetype: SlideArchetype
    ) -> None:
        """Title, section and closing slides use the template's own placeholders (fidelity first)."""
        title = s.headline or deck.title
        if archetype == SlideArchetype.title:
            second = [(s.key_message or deck.subtitle or "", None)]
        elif archetype == SlideArchetype.closing:
            second = ([(s.key_message, None)] if s.key_message else []) + lines_from_blocks(s.blocks)
        else:
            second = [(s.key_message, None)] if s.key_message else []
        second = [(t, lvl) for t, lvl in second if t]
        title_ph = self.slots.get("title")
        size = {SlideArchetype.title: 44, SlideArchetype.section: 36, SlideArchetype.closing: 36}[archetype]
        if archetype == SlideArchetype.title:
            self._fill_photo(c, s)
        if title_ph is not None:
            c.placeholder_text(
                title_ph,
                [BulletPara(self._p(title, size, heading=True))],
                name="content:title",
                min_pt=MIN_TITLE,
            )
            c.tighten(title_ph)
            self._readable(c, title_ph)
            self._clear_title(c, title_ph)
        else:
            self._headline(c, s)
        if not second:
            return
        body_ph = self.slots.get("subtitle")
        paras = [
            BulletPara(self._p(t, 20 if archetype == SlideArchetype.title else 18), level=lvl)
            for t, lvl in second
        ]
        if body_ph is not None:
            # The subtitle box holds one line; further points (closing actions) go below it at body size,
            # when the slide has room for them there.
            room = self.f.h - (int(body_ph.top) + int(body_ph.height)) / 914400 - 0.85 * self.f.scale
            if room < 0.45 * self.f.scale * max(len(paras) - 1, 1):
                paras = [BulletPara(bp.para, level=bp.level) for bp in paras]
                c.placeholder_text(body_ph, paras, name="content:subtitle", min_pt=MIN_BODY)
                self._readable(c, body_ph)
                if title_ph is not None:
                    c.separate(title_ph, body_ph)
                return
            c.placeholder_text(body_ph, paras[:1], name="content:subtitle", min_pt=MIN_BODY)
            self._readable(c, body_ph)
            if title_ph is not None:
                c.separate(title_ph, body_ph)
            rest = paras[1:]
            if rest:
                top = (int(body_ph.top) + int(body_ph.height)) / 914400 + 0.25 * self.f.scale
                width = int(body_ph.width) / 914400
                area = Rect(
                    int(body_ph.left) / 914400, top, width, max(self.f.h - top - 0.6 * self.f.scale, 0.5)
                )
                c.text(
                    area,
                    [BulletPara(bp.para, level=0) for bp in rest],
                    TextStyle(self.pal.text, bullet_color=self.pal.primary, align="center"),
                    name="content:body",
                    min_pt=MIN_BODY,
                )
        else:
            c.text(
                self.f.body,
                paras,
                TextStyle(self.pal.text, bullet_color=self.pal.primary),
                name="content:body",
                min_pt=MIN_BODY,
            )

    # ---------------------------------------------------------------- text helpers

    def _p(
        self, text: str, size: float, *, bold: bool = False, heading: bool = False, after: float = 0
    ) -> Para:
        if heading:
            sizes = self.current_style.heading_sizes_pt
            if size >= 40 and sizes.title is not None:
                size = sizes.title
            elif size >= 30 and sizes.h1 is not None:
                size = sizes.h1
            elif size >= 20 and sizes.h2 is not None:
                size = sizes.h2
            elif sizes.h3 is not None:
                size = sizes.h3
        elif self.current_style.body_size_pt is not None:
            size = self.current_style.body_size_pt
        return Para(
            text,
            round(size * self.f.scale, 1),
            bold=bold,
            font=self.heading_font if heading else self.body_font,
            space_after_pt=after,
        )

    def _headline(
        self, c: Canvas, s: SlidePlan, *, rect: Rect | None = None, color: str | None = None
    ) -> None:
        title_ph = self.slots.get("title") if self.tpl is not None else None
        if title_ph is not None and rect is None:
            c.placeholder_text(
                title_ph,
                [BulletPara(self._p(s.headline, 30, heading=True))],
                name="content:headline",
                min_pt=MIN_HEADLINE,
            )
            self._readable(c, title_ph)
            self._clear_title(c, title_ph)
            bottom = (int(title_ph.top) + int(title_ph.height)) / 914400 + 0.15 * self.f.scale
            body = self.f.body
            if body.y < bottom < body.y + body.h * 0.6:
                self.f = replace(self.f, body=Rect(body.x, bottom, body.w, body.y + body.h - bottom))
            return
        rect = rect or self.f.headline
        text_color = color or self.pal.text
        if not color and self.tpl is not None:
            box = (int(rect.x * 914400), int(rect.y * 914400), int(rect.w * 914400), int(rect.h * 914400))
            under = color_under(c.slide, box)
            if under and contrast_ratio(self.pal.text, under) < 3.0:
                text_color = readable_on(under)
        c.text(
            rect,
            [BulletPara(self._p(s.headline, 30, bold=True, heading=True))],
            TextStyle(text_color),
            name="content:headline",
            min_pt=MIN_HEADLINE,
        )

    def _lead(self, c: Canvas, s: SlidePlan, body: Rect | None = None) -> Rect:
        """Render the key message as a lead line above the body; returns the remaining body area."""
        body = body or self.f.body
        if not s.key_message:
            return body
        lead, rest = body.take_top(0.55 * self.f.scale, 0.2 * self.f.scale)
        c.text(
            lead,
            [BulletPara(self._p(s.key_message, 18))],
            TextStyle(self.pal.text_muted),
            name="content:lead",
            min_pt=MIN_BODY,
        )
        return rest

    def _bullet_paras(
        self, lines: list[tuple[str, int | None]], *, color: str | None = None, base: float | None = None
    ) -> list[BulletPara]:
        # Sparse slides get larger type; the fitter only ever shrinks from here.
        size = base or (24 if len(lines) <= 3 else 20 if len(lines) <= 5 else 18)
        out = []
        for text, level in lines:
            sz = size if not level else size - 2
            out.append(BulletPara(self._p(text, sz, after=12), level=level, color=color))
        return out

    def _card(self, c: Canvas, r: Rect, name: str = "decor:card") -> Rect:
        c.rect(r, self.pal.surface, name, rounded=True)
        return r.inset(CARD_PAD_X, CARD_PAD_Y)

    @staticmethod
    def _card_row(body: Rect, n: int, gap: float, needed_inner: list[float]) -> list[Rect]:
        """Cards sized to the tallest content (within limits), vertically centred in ``body``."""
        height = max(needed_inner, default=0) + 2 * CARD_PAD_Y
        height = min(body.h, max(height, body.h * 0.45))
        row = Rect(body.x, body.y + (body.h - height) / 2, body.w, height)
        return row.split_h(n, gap)

    def _footer(self, c: Canvas, s: SlidePlan, number: int) -> None:
        if self.tpl is None:
            self._slide_number(c, number)
        refs = sorted({n for cid in _slide_claims(s) for n in self._numbers_for_claim(cid)})
        if refs:
            label = "Sources: " + " ".join(f"[{n}]" for n in refs)
            c.text(
                Rect(self.f.m, self.f.footer_y, min(8.0, self.f.w - 2 * self.f.m - 1.2), 0.35),
                [BulletPara(self._p(label, 10))],
                TextStyle(self.pal.text_muted),
                name="footer:sources",
                min_pt=MIN_CAPTION,
            )

    def _slide_number(self, c: Canvas, number: int) -> None:
        c.text(
            Rect(self.f.w - self.f.m - 1.0, self.f.footer_y, 1.0, 0.35),
            [BulletPara(self._p(str(number), 10))],
            TextStyle(self.pal.text_muted, align="right"),
            name="footer:number",
            min_pt=MIN_CAPTION,
        )

    def _numbers_for_claim(self, claim_id: str) -> list[int]:
        if not self.dossier:
            return []
        claim = self.dossier.claim(claim_id)
        if claim is None:
            return []
        src_by_evd = {e.id: e.source_id for e in self.dossier.evidence}
        return [self.numbers[src_by_evd[e]] for e in claim.evidence_ids if src_by_evd.get(e) in self.numbers]

    # ---------------------------------------------------------------- dark archetypes

    def _asset(self, s: SlidePlan) -> tuple[ImageBlock, Path] | None:
        image = _first(s, ImageBlock)
        if image is None or not image.asset_path or self.assets is None:
            return None
        try:
            return image, self.assets(image.asset_path)
        except Exception:  # a missing asset must not break the deck; fall back to the plain layout
            return None

    def _title(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        hero = self._asset(s)
        if hero is not None:
            self._hero_title(c, s, deck, *hero)
            return
        c.circle(11.2, 2.3, 3.4, self.pal.secondary, "decor:orb-large")
        c.circle(
            9.75, 5.2, 1.5, self.colors[2] if len(self.colors) > 2 else self.pal.primary, "decor:orb-small"
        )
        c.text(
            Rect(self.f.m, 2.0, 8.4, 2.3),
            [BulletPara(self._p(s.headline or deck.title, 44, bold=True, heading=True))],
            TextStyle(self.on_dark, anchor="bottom"),
            name="content:title",
            min_pt=28,
        )
        subtitle = s.key_message or deck.subtitle
        if subtitle:
            c.text(
                Rect(self.f.m, 4.45, 8.2, 1.1),
                [BulletPara(self._p(subtitle, 20))],
                TextStyle(self.on_dark),
                name="content:subtitle",
                min_pt=MIN_BODY,
            )
        if deck.audience:
            c.text(
                Rect(self.f.m, 6.4, 8.0, 0.45),
                [BulletPara(self._p(deck.audience, 12))],
                TextStyle(self.on_dark),
                name="content:audience",
                min_pt=MIN_CAPTION,
            )

    def _section(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self.section_count += 1
        accent = self.colors[2] if len(self.colors) > 2 else self.pal.secondary
        c.badge(
            self.f.m + 0.55,
            3.05,
            1.1,
            f"{self.section_count:02d}",
            accent,
            readable_on(accent),
            self.heading_font,
            "decor:section-number",
        )
        c.text(
            Rect(self.f.m + 1.5, 2.35, self.f.w - 2 * self.f.m - 1.5, 1.4),
            [BulletPara(self._p(s.headline, 36, bold=True, heading=True))],
            TextStyle(self.on_dark, anchor="middle"),
            name="content:headline",
            min_pt=MIN_HEADLINE + 2,
        )
        if s.key_message:
            c.text(
                Rect(self.f.m + 1.5, 3.85, self.f.w - 2 * self.f.m - 1.5, 1.2),
                [BulletPara(self._p(s.key_message, 18))],
                TextStyle(self.on_dark),
                name="content:lead",
                min_pt=MIN_BODY,
            )

    def _closing(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        c.circle(11.6, 1.4, 2.2, self.pal.secondary, "decor:orb-large")
        c.text(
            Rect(self.f.m, 0.9, 9.6, 1.5),
            [BulletPara(self._p(s.headline, 40, bold=True, heading=True))],
            TextStyle(self.on_dark, anchor="bottom"),
            name="content:headline",
            min_pt=MIN_HEADLINE + 4,
        )
        top = 2.6
        if s.key_message:
            c.text(
                Rect(self.f.m, top, 9.6, 1.0),
                [BulletPara(self._p(s.key_message, 20))],
                TextStyle(self.on_dark),
                name="content:lead",
                min_pt=MIN_BODY,
            )
            top += 1.2
        lines = lines_from_blocks(s.blocks)
        if lines:
            c.text(
                Rect(self.f.m, top, 10.5, self.f.h - top - 0.6),
                self._bullet_paras(lines, color=self.on_dark),
                TextStyle(self.on_dark, bullet_color=self.on_dark),
                name="content:body",
                min_pt=MIN_BODY,
            )

    # ---------------------------------------------------------------- light archetypes

    def _numbered_rows(self, c: Canvas, s: SlidePlan, fill: str) -> None:
        self._headline(c, s)
        items = [t for t, _ in lines_from_blocks(s.blocks)] or [s.key_message or ""]
        cols = 1 if len(items) <= 5 else 2
        per_col = -(-len(items) // cols)
        col_rects = self.f.body.split_h(cols, GAP * 2)
        row_h = min(1.1, self.f.body.h / per_col)
        size = 24 if len(items) <= 4 else 20 if len(items) <= 6 else 18
        for i, item in enumerate(items):
            col, row = divmod(i, per_col)
            r = col_rects[col]
            y = r.y + row * row_h
            d = min(0.6, row_h * 0.7)
            c.badge(
                r.x + d / 2,
                y + row_h / 2,
                d,
                str(i + 1),
                fill,
                readable_on(fill),
                self.heading_font,
                f"decor:badge-{i + 1}",
            )
            c.text(
                Rect(r.x + d + 0.3, y, r.w - d - 0.3, row_h),
                [BulletPara(self._p(item, size))],
                TextStyle(self.pal.text, anchor="middle"),
                name=f"content:item-{i + 1}",
                min_pt=MIN_BODY,
            )

    def _agenda(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self._numbered_rows(c, s, self.pal.primary)

    def _summary(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self._numbered_rows(c, s, self.pal.secondary)

    def _bullets(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self._headline(c, s)
        lines = lines_from_blocks(s.blocks)
        callout = _first(s, CalloutBlock)
        panel_text = s.key_message or (callout.text if callout else "")
        if callout:
            lines = [ln for ln in lines if ln[0] != callout.text]
        if panel_text and lines:
            left, right = self.f.body.take_left(self.f.body.w * 0.6, 0.45 * self.f.scale)
            inner = self._card(c, right)
            c.text(
                inner,
                [BulletPara(self._p(panel_text, 24, heading=True), italic=True)],
                TextStyle(self.pal.primary, anchor="middle"),
                name="content:key-message",
                min_pt=16,
            )
            body = left
        else:
            body = self.f.body
            if panel_text and not lines:
                lines = [(panel_text, None)]
        c.text(
            body,
            self._bullet_paras(lines),
            TextStyle(self.pal.text, bullet_color=self.pal.primary),
            name="content:body",
            min_pt=MIN_BODY,
        )

    @staticmethod
    def _clear_title(c: Canvas, shape) -> None:
        """Template accent lines drawn under a one-word sample title must not strike through ours."""
        top, bottom = int(shape.top), int(shape.top) + int(shape.height)
        left, right = int(shape.left), int(shape.left) + int(shape.width)
        thin = 914400 * 0.06
        for other in c.slide.shapes:
            if other is shape or other.name.startswith(("content:", "footer:")) or other.width is None:
                continue
            ox, oy, ow, oh = int(other.left), int(other.top), int(other.width), int(other.height)
            horizontal = oh <= thin and ow > thin
            if horizontal and top + 0.15 * (bottom - top) < oy < bottom and ox < right and ox + ow > left:
                set_geometry(other, y=bottom + int(914400 * 0.05))

    def _readable(self, c: Canvas, shape) -> None:
        """Keep the template's title colour unless it would be unreadable on what is really behind it."""
        runs = [r for p in shape.text_frame.paragraphs for r in p.runs]
        if not runs:
            return
        try:
            color = str(runs[0].font.color.rgb) if runs[0].font.color.type is not None else None
        except AttributeError:
            color = None
        box = (int(shape.left), int(shape.top), int(shape.width), int(shape.height))
        under = color_under(c.slide, box, stop_at=shape._element)
        if color and under and contrast_ratio(color, under) >= 3:
            return
        best = max((self.pal.text, "FFFFFF", "1F2328"), key=lambda x: contrast_ratio(x, under or "FFFFFF"))
        for r in runs:
            r.font.color.rgb = rgb(best)

    def _fill_photo(self, c: Canvas, s: SlidePlan) -> bool:
        """Put the slide's photo into the template's picture frame; True when one was filled."""
        photos = self.slots.get("photos") or []
        frames = self.slots.get("frames") or []
        asset = self._asset(s)
        if (not photos and not frames) or asset is None or self.slots.get("photo_done"):
            return False
        image, path = asset
        frame = photos[0] if photos else frames[0]
        r = Rect(frame.left / 914400, frame.top / 914400, frame.width / 914400, frame.height / 914400)
        if not photos:  # a drawn frame stays visible as a border around the photo
            r = r.inset(r.w * 0.04, r.w * 0.04)
        c.picture(r, path, name="content:image", alt=image.alt_text)
        if photos:
            frame._element.getparent().remove(frame._element)
        self.slots["photo_done"] = True
        return True

    def _bullets_body(self, c: Canvas, s: SlidePlan, body: Rect) -> None:
        paras = []
        if s.key_message:
            paras.append(
                BulletPara(
                    self._p(s.key_message, 22, bold=True, heading=True, after=14), color=self.pal.primary
                )
            )
        paras += self._bullet_paras(lines_from_blocks(s.blocks), base=18)
        if paras:
            c.text(
                body,
                paras,
                TextStyle(self.pal.text, bullet_color=self.pal.primary),
                name="content:body",
                min_pt=MIN_BODY,
            )

    def _hero_title(self, c: Canvas, s: SlidePlan, deck: DeckPlan, image: ImageBlock, path: Path) -> None:
        """Gamma-style cover: dark text panel left, full-height photo right."""
        split = 7.1
        c.picture(
            Rect(split, 0, self.f.w - split, self.f.h), path, name="content:hero-image", alt=image.alt_text
        )
        c.text(
            Rect(self.f.m, 1.7, split - self.f.m - 0.5, 2.6),
            [BulletPara(self._p(s.headline or deck.title, 44, bold=True, heading=True))],
            TextStyle(self.on_dark, anchor="bottom"),
            name="content:title",
            min_pt=28,
        )
        subtitle = s.key_message or deck.subtitle
        if subtitle:
            c.text(
                Rect(self.f.m, 4.5, split - self.f.m - 0.5, 1.2),
                [BulletPara(self._p(subtitle, 20))],
                TextStyle(self.on_dark),
                name="content:subtitle",
                min_pt=MIN_BODY,
            )
        footer = " · ".join(x for x in (deck.audience, image.credit) if x)
        if footer:
            c.text(
                Rect(self.f.m, 6.55, split - self.f.m - 0.3, 0.6),
                [BulletPara(self._p(footer, 10))],
                TextStyle(self.on_dark),
                name="content:caption-credit",
                min_pt=MIN_CAPTION - 1,
            )

    def _image_text(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        asset = self._asset(s)
        if asset is None:
            self._bullets(c, s, deck)
            return
        image, path = asset
        self._headline(c, s)
        if self._fill_photo(c, s):
            self._bullets_body(c, s, self.f.body)
            return
        text_r, image_r = self.f.body.take_left(self.f.body.w * 0.5, 0.45 * self.f.scale)
        pic_r, credit_r = image_r.take_top(image_r.h - 0.32 * self.f.scale, 0.04 * self.f.scale)
        c.picture(pic_r, path, name="content:image", alt=image.alt_text)
        if image.credit:
            c.text(
                credit_r,
                [BulletPara(self._p(image.credit, 10))],
                TextStyle(self.pal.text_muted, align="right"),
                name="content:caption-credit",
                min_pt=MIN_CAPTION - 1,
            )
        paras = []
        if s.key_message:
            paras.append(
                BulletPara(
                    self._p(s.key_message, 22, bold=True, heading=True, after=14), color=self.pal.primary
                )
            )
        paras += self._bullet_paras(lines_from_blocks(s.blocks), base=18)
        if paras:
            c.text(
                text_r,
                paras,
                TextStyle(self.pal.text, bullet_color=self.pal.primary),
                name="content:body",
                min_pt=MIN_BODY,
            )

    def _comparison(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self._headline(c, s)
        body = self._lead(c, s)
        block = _first(s, ComparisonBlock)
        if block is not None:
            columns = [(col.heading, col.points) for col in block.columns]
        else:
            lines = [t for t, _ in lines_from_blocks(s.blocks)]
            half = -(-len(lines) // 2)
            columns = [("", lines[:half]), ("", lines[half:])]
        inner_w = (body.w - GAP * (len(columns) - 1)) / len(columns) - 2 * CARD_PAD_X
        contents = []
        for heading, points in columns:
            paras = []
            if heading:
                paras.append(
                    BulletPara(
                        self._p(heading, 24, bold=True, heading=True, after=14), color=self.pal.primary
                    )
                )
            paras += self._bullet_paras([(p, 0) for p in points], base=18 if len(columns) > 2 else 20)
            contents.append(paras)
        rects = self._card_row(body, len(columns), GAP, [content_height(p, inner_w) for p in contents])
        for i, (paras, r) in enumerate(zip(contents, rects, strict=True)):
            inner = self._card(c, r, f"decor:card-{i + 1}")
            c.text(
                inner,
                paras,
                TextStyle(self.pal.text, bullet_color=self.pal.primary),
                name=f"content:column-{i + 1}",
                min_pt=MIN_BODY,
            )

    _two_column = _comparison

    def _timeline(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self._headline(c, s)
        body = self._lead(c, s)
        events = _first(s, TimelineBlock).events
        n = len(events)
        col_w = body.w / n
        texts = []
        for e in events:
            paras = [BulletPara(self._p(e.label, 20, bold=True, after=8))]
            if e.description:
                paras.append(BulletPara(self._p(e.description, 16), color=self.pal.text_muted))
            texts.append(paras)
        date_h, marker_gap = 0.75, 0.4
        text_h = min(body.h - date_h - marker_gap, max(content_height(t, col_w - 0.16) for t in texts) + 0.1)
        group_h = date_h + marker_gap + text_h
        top = body.y + (body.h - group_h) / 2
        line_y = top + date_h + 0.12
        c.line(body.x + col_w / 2, line_y, body.right_x - col_w / 2, line_y, self.pal.secondary, "decor:axis")
        for i, (e, paras) in enumerate(zip(events, texts, strict=True)):
            x = body.x + i * col_w
            c.circle(x + col_w / 2, line_y, 0.34, self.pal.primary, f"decor:marker-{i + 1}")
            if e.date:
                c.text(
                    Rect(x + 0.05, top - 0.05, col_w - 0.1, date_h - 0.1),
                    [BulletPara(self._p(e.date, 20, bold=True))],
                    TextStyle(self.pal.primary, align="center", anchor="bottom"),
                    name=f"content:date-{i + 1}",
                    min_pt=MIN_BODY,
                )
            c.text(
                Rect(x + 0.08, line_y + marker_gap - 0.05, col_w - 0.16, text_h),
                paras,
                TextStyle(self.pal.text, align="center"),
                name=f"content:event-{i + 1}",
                min_pt=MIN_BODY,
            )

    def _process(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self._headline(c, s)
        body = self._lead(c, s)
        steps = _first(s, ProcessBlock).steps
        gap = 0.5
        badge_band = 0.85
        inner_w = (body.w - gap * (len(steps) - 1)) / len(steps) - 2 * CARD_PAD_X
        contents = []
        for step in steps:
            paras = [BulletPara(self._p(step.title, 20, bold=True, after=8), color=self.pal.primary)]
            if step.description:
                paras.append(BulletPara(self._p(step.description, 16)))
            contents.append(paras)
        rects = self._card_row(
            body, len(steps), gap, [badge_band + content_height(p, inner_w) for p in contents]
        )
        for i, (paras, r) in enumerate(zip(contents, rects, strict=True)):
            inner = self._card(c, r, f"decor:card-{i + 1}")
            c.badge(
                inner.x + 0.3,
                inner.y + 0.3,
                0.6,
                str(i + 1),
                self.pal.primary,
                readable_on(self.pal.primary),
                self.heading_font,
                f"decor:step-{i + 1}",
            )
            c.text(
                Rect(inner.x, inner.y + badge_band, inner.w, inner.h - badge_band),
                paras,
                TextStyle(self.pal.text),
                name=f"content:step-{i + 1}",
                min_pt=MIN_BODY,
            )
            if i < len(steps) - 1:
                c.shape(
                    MSO_SHAPE.CHEVRON,
                    Rect(r.right_x + 0.12, r.y + r.h / 2 - 0.15, 0.26, 0.3),
                    fill=self.pal.secondary,
                    name=f"decor:arrow-{i + 1}",
                )

    def _chart(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self._headline(c, s)
        block = _first(s, ChartBlock)
        side_lines = [ln for ln in lines_from_blocks([b for b in s.blocks if b is not block])]
        if s.key_message or side_lines:
            chart_r, side = self.f.body.take_left(self.f.body.w * 0.64, 0.45 * self.f.scale)
            inner = self._card(c, side)
            paras = []
            if s.key_message:
                paras.append(
                    BulletPara(
                        self._p(s.key_message, 20, bold=True, heading=True, after=12), color=self.pal.primary
                    )
                )
            paras += self._bullet_paras(side_lines, base=15)
            c.text(
                inner,
                paras,
                TextStyle(self.pal.text, bullet_color=self.pal.primary),
                name="content:takeaway",
                min_pt=MIN_BODY,
            )
        else:
            chart_r = self.f.body
        c.chart(chart_r, block, self.colors, self.pal.text, self.pal.text_muted, self.body_font)

    def _table(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self._headline(c, s)
        body = self._lead(c, s)
        block = _first(s, TableBlock)
        dense = len(block.rows) > 6 or len(block.columns) > 5
        table_area = body
        if block.caption:
            table_area, cap = body.take_top(body.h - 0.45 * self.f.scale, 0.1 * self.f.scale)
            c.text(
                cap,
                [BulletPara(self._p(block.caption, 12))],
                TextStyle(self.pal.text_muted),
                name="content:caption",
                min_pt=MIN_CAPTION,
            )
        c.table(
            table_area,
            block.columns,
            block.rows,
            header_fill=self.pal.primary,
            header_text=readable_on(self.pal.primary),
            zebra=self.pal.surface,
            text_color=self.pal.text,
            font=self.body_font,
            size_pt=12 if dense else 16,
        )

    def _kpi(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        self._headline(c, s)
        body = self._lead(c, s)
        metrics = _first(s, KPIBlock).metrics
        inner_w = (body.w - GAP * (len(metrics) - 1)) / len(metrics) - 2 * CARD_PAD_X
        value_h = 1.25
        contents = []
        for m in metrics:
            paras = [BulletPara(self._p(m.label, 20, bold=True, after=8))]
            if m.delta:
                negative = m.delta.strip().startswith(("-", "−", "▼"))
                paras.append(
                    BulletPara(
                        self._p(m.delta, 18, bold=True, after=8),
                        color=self.pal.negative if negative else self.pal.positive,
                    )
                )
            if m.note:
                paras.append(BulletPara(self._p(m.note, 16), color=self.pal.text_muted))
            contents.append(paras)
        rects = self._card_row(
            body, len(metrics), GAP, [value_h + 0.15 + content_height(p, inner_w) for p in contents]
        )
        for i, (m, paras, r) in enumerate(zip(metrics, contents, rects, strict=True)):
            inner = self._card(c, r, f"decor:card-{i + 1}")
            c.text(
                Rect(inner.x, inner.y, inner.w, value_h),
                [BulletPara(self._p(m.value, 54, bold=True, heading=True))],
                TextStyle(self.pal.primary, anchor="bottom"),
                name=f"content:kpi-value-{i + 1}",
                min_pt=24,
            )
            c.text(
                Rect(inner.x, inner.y + value_h + 0.15, inner.w, inner.h - value_h - 0.15),
                paras,
                TextStyle(self.pal.text),
                name=f"content:kpi-text-{i + 1}",
                min_pt=MIN_BODY,
            )

    def _quote(self, c: Canvas, s: SlidePlan, deck: DeckPlan) -> None:
        block = _first(s, QuoteBlock)
        if self.tpl is not None:  # designed slides: headline in the title box, quote in the content area
            self._headline(c, s)
            self._fill_photo(c, s)
            paras = [BulletPara(self._p(f"“{block.text}”", 26, heading=True, after=14), italic=True)]
            if block.attribution:
                paras.append(BulletPara(self._p(f"— {block.attribution}", 16), color=self.pal.text_muted))
            c.text(
                self.f.body,
                paras,
                TextStyle(self.pal.text, anchor="middle"),
                name="content:quote",
                min_pt=MIN_BODY + 2,
            )
            return
        c.text(
            Rect(self.f.m, 0.9 * self.f.scale, 1.6 * self.f.scale, 1.8 * self.f.scale),
            [BulletPara(self._p("“", 140, bold=True, heading=True))],
            TextStyle(self.pal.secondary),
            name="decor:quote-mark",
            min_pt=60,
        )
        paras = [BulletPara(self._p(block.text, 30, heading=True, after=18), italic=True)]
        if block.attribution:
            paras.append(BulletPara(self._p(f"— {block.attribution}", 18), color=self.pal.text_muted))
        c.text(
            Rect(
                self.f.m + 1.6 * self.f.scale,
                1.6 * self.f.scale,
                self.f.w - 2 * self.f.m - 2.2 * self.f.scale,
                self.f.h - 2.9 * self.f.scale,
            ),
            paras,
            TextStyle(self.pal.text, anchor="middle"),
            name="content:quote",
            min_pt=MIN_BODY + 4,
        )
        if s.headline:
            c.text(
                Rect(
                    self.f.m + 1.6 * self.f.scale,
                    self.f.h - 1.25 * self.f.scale,
                    self.f.w - 2 * self.f.m - 2.2 * self.f.scale,
                    0.5 * self.f.scale,
                ),
                [BulletPara(self._p(s.headline, 14))],
                TextStyle(self.pal.text_muted),
                name="content:caption",
                min_pt=MIN_CAPTION,
            )

    def _references(self, c: Canvas, s: SlidePlan | None, deck: DeckPlan) -> None:
        headline = s.headline if s else "Sources"
        self._headline(
            c, s or SlidePlan(id="refs", purpose="sources", archetype="references", headline=headline)
        )
        entries = self._reference_entries()
        if not entries and s is not None:
            entries = [t for t, _ in lines_from_blocks(s.blocks)]
        if not entries:
            entries = ["No external sources were cited in this deck."]
        cols = 1 if len(entries) <= 8 else 2
        per = -(-len(entries) // cols)
        for i, r in enumerate(self.f.body.split_h(cols, GAP)):
            chunk = entries[i * per : (i + 1) * per]
            if chunk:
                c.text(
                    r,
                    [BulletPara(self._p(e, 12, after=6)) for e in chunk],
                    TextStyle(self.pal.text),
                    name=f"content:references-{i + 1}",
                    min_pt=MIN_CAPTION,
                )

    def _reference_entries(self) -> list[str]:
        if not self.dossier or not self.numbers:
            return []
        by_id = {src.id: src for src in self.dossier.sources}
        out = []
        for src_id, n in sorted(self.numbers.items(), key=lambda kv: kv[1]):
            src = by_id[src_id]
            parts = [src.title, src.publisher, src.published_at, _domain(src.url)]
            out.append(_wrap_long_tokens(f"[{n}] " + ". ".join(p for p in parts if p)))
        return out


def _domain(url: str | None) -> str | None:
    """Slides show the site, not the full URL (full links are in the speaker notes and documents)."""
    if not url:
        return None
    from urllib.parse import urlparse

    host = urlparse(url).netloc or url
    return host.removeprefix("www.")


def _wrap_long_tokens(text: str, limit: int = 32) -> str:
    """Break tokens longer than ``limit`` characters so no single word is wider than its box."""
    out = []
    for word in text.split(" "):
        while len(word) > limit:
            out.append(word[:limit])
            word = word[limit:]
        out.append(word)
    return " ".join(out)
