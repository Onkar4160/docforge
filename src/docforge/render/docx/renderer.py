"""DocumentPlan → editable DOCX (Stage 9, FR-DOCX-1..5).

Without a template, a clean style set is defined from design tokens. With a template, its styles,
page setup, headers and footers are kept and only the body content is replaced (FR-DOCX-4).
Formatting is applied through named styles, so later restyles touch styles, not runs (FR-DOCX-5).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from docx.text.paragraph import Paragraph

from docforge.design.system import readable_on
from docforge.models.design import DesignTokens
from docforge.models.evidence import ResearchDossier
from docforge.models.intent import CitationStyle
from docforge.models.ir import (
    BulletsBlock,
    CalloutBlock,
    ChartBlock,
    ComparisonBlock,
    DocumentPlan,
    ImageBlock,
    KPIBlock,
    ParagraphBlock,
    ProcessBlock,
    QuoteBlock,
    SectionPlan,
    TableBlock,
    TimelineBlock,
)
from docforge.render.charts import chart_png
from docforge.render.citations import Citations

DEFAULT_SIZES = {"title": 28.0, "h1": 16.0, "h2": 13.0, "h3": 12.0}
_ALIGNMENT = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}


@dataclass
class DocRenderResult:
    path: Path
    words: int
    tables: int
    figures: int
    references: int
    headings: list[tuple[int, str]] = field(default_factory=list)


def _rgb(hex_color: str) -> RGBColor:
    s = hex_color.strip().removeprefix("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    elif len(s) == 8:
        s = s[2:]
    return RGBColor.from_string(s.upper())


def _add_field(paragraph, instruction: str, placeholder: str = "") -> None:
    def fld(kind: str):
        el = OxmlElement("w:fldChar")
        el.set(qn("w:fldCharType"), kind)
        run = paragraph.add_run()
        run._r.append(el)

    fld("begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    paragraph.add_run()._r.append(instr)
    fld("separate")
    if placeholder:
        paragraph.add_run(placeholder)
    fld("end")


def _shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill.strip().removeprefix("#").upper())
    tc_pr.append(shd)


def _repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def _clear_body(doc) -> None:
    body = doc.element.body
    for child in list(body):
        if child.tag == qn("w:sectPr"):
            continue
        sect_prs = child.xpath(".//w:sectPr")
        if sect_prs:
            for sub in list(child):
                if sub.tag != qn("w:pPr"):
                    child.remove(sub)
            p_pr = child.find(qn("w:pPr"))
            if p_pr is not None:
                for psub in list(p_pr):
                    if psub.tag != qn("w:sectPr"):
                        p_pr.remove(psub)
        else:
            body.remove(child)


class DocxRenderer:
    def __init__(
        self,
        tokens: DesignTokens,
        citations: Citations,
        *,
        styled: bool,
        fig_dir: Path,
        assets=None,
        cover_logo: bytes | None = None,
        cover_logo_width_emu: int | None = None,
        cover_logo_alignment=None,
    ) -> None:
        self.assets = assets
        self.base_tokens = tokens
        self.t = tokens
        self.cite = citations
        self.styled = styled  # False when a template provides the styles
        self.tables = 0
        self.figures = 0
        self.tmp = fig_dir
        self.current_style = None
        self.role_style_map: dict[str, str] = {}
        self.cover_logo = cover_logo
        self.cover_logo_width_emu = cover_logo_width_emu
        self.cover_logo_alignment = cover_logo_alignment

    # ---------------------------------------------------------------- styles

    def _apply_style(self, style) -> None:
        self.current_style = style
        palette_update = {
            key: value
            for key, value in style.palette_overrides.items()
            if key not in {f"accent{i}" for i in range(1, 7)}
        }
        accents = list(self.base_tokens.palette.accents)
        for index in range(1, 7):
            color = style.palette_overrides.get(f"accent{index}")
            while color is not None and len(accents) < index:
                accents.append(accents[-1] if accents else self.base_tokens.palette.primary)
            if color is not None:
                accents[index - 1] = color
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

    def setup_styles(self, doc, plan: DocumentPlan) -> None:
        self._apply_style(plan.style)
        style = plan.style
        sizes = dict(DEFAULT_SIZES) if self.styled else {}
        sizes.update(
            {key: value for key, value in style.heading_sizes_pt.model_dump().items() if value is not None}
        )
        body_font = style.body_font or self.t.fonts.body
        heading_font = style.heading_font or self.t.fonts.heading
        normal = doc.styles["Normal"]
        if self.styled or style.body_font:
            normal.font.name = body_font
            normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), body_font)
        if self.styled or style.body_size_pt is not None:
            normal.font.size = Pt(style.body_size_pt or 11)
        if self.styled or "text" in style.palette_overrides:
            normal.font.color.rgb = _rgb(self.t.palette.text)
        fmt = normal.paragraph_format
        if self.styled or style.paragraph_spacing_pt is not None:
            fmt.space_after = Pt(style.paragraph_spacing_pt if style.paragraph_spacing_pt is not None else 8)
        if self.styled or style.line_spacing is not None:
            fmt.line_spacing = style.line_spacing if style.line_spacing is not None else 1.15
        if style.body_alignment:
            fmt.alignment = _ALIGNMENT[style.body_alignment]
        for role, default_name, size_key, color in (
            ("title", "Title", "title", self.t.palette.primary),
            ("h1", "Heading 1", "h1", self.t.palette.primary),
            ("h2", "Heading 2", "h2", self.t.palette.primary),
            ("h3", "Heading 3", "h3", self.t.palette.text),
        ):
            name = self.role_style_map.get(role, default_name)
            if name not in doc.styles:
                name = default_name
            heading_style = doc.styles[name]
            if self.styled or style.heading_font:
                heading_style.font.name = heading_font
                heading_style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), heading_font)
            if size_key in sizes:
                heading_style.font.size = Pt(sizes[size_key])
            if self.styled or any(key in style.palette_overrides for key in ("primary", "text")):
                heading_style.font.color.rgb = _rgb(color)
            if self.styled:
                heading_style.font.bold = name != "Title"
                heading_style.paragraph_format.space_before = Pt(18 if role == "h1" else 12)
                heading_style.paragraph_format.space_after = Pt(6)
                heading_style.paragraph_format.keep_with_next = True
            if style.heading_alignment:
                heading_style.paragraph_format.alignment = _ALIGNMENT[style.heading_alignment]
        for name in ("Subtitle", "Caption", "Quote"):
            if name in doc.styles and (self.styled or style.body_font):
                doc.styles[name].font.name = body_font
        if "Caption" in doc.styles and (self.styled or "text_muted" in style.palette_overrides):
            doc.styles["Caption"].font.color.rgb = _rgb(self.t.palette.text_muted)
        if self.styled or style.margins_in is not None:
            margins = Inches(style.margins_in if style.margins_in is not None else 1.0)
            for section in doc.sections:
                section.left_margin = section.right_margin = margins
                section.top_margin = section.bottom_margin = margins
        if style.page_orientation:
            for section in doc.sections:
                if style.page_orientation == "landscape":
                    section.orientation = WD_ORIENT.LANDSCAPE
                    if section.page_width < section.page_height:
                        section.page_width, section.page_height = section.page_height, section.page_width
                else:
                    section.orientation = WD_ORIENT.PORTRAIT
                    if section.page_width > section.page_height:
                        section.page_width, section.page_height = section.page_height, section.page_width

    def _format_paragraph(self, paragraph, style, *, heading: bool = False, level: int | None = None) -> None:
        font_name = style.heading_font if heading else style.body_font
        font_size = None
        if heading:
            if level is not None:
                key = f"h{min(level, 3)}" if level > 0 else "title"
            elif paragraph.style.name.startswith("Heading "):
                key = f"h{paragraph.style.name.rsplit(' ', 1)[-1]}"
            else:
                key = "title"
            font_size = getattr(style.heading_sizes_pt, key, None)
        else:
            font_size = style.body_size_pt
        color_role = "primary" if heading else "text"
        color = style.palette_overrides.get(color_role)
        if font_name or font_size is not None or color:
            for run in paragraph.runs:
                if font_name:
                    run.font.name = font_name
                    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), font_name)
                if font_size is not None:
                    run.font.size = Pt(font_size)
                if color:
                    run.font.color.rgb = _rgb(color)
        alignment = style.heading_alignment if heading else style.body_alignment
        if alignment:
            paragraph.alignment = _ALIGNMENT[alignment]
        if style.paragraph_spacing_pt is not None:
            paragraph.paragraph_format.space_after = Pt(style.paragraph_spacing_pt)
        if style.line_spacing is not None:
            paragraph.paragraph_format.line_spacing = style.line_spacing

    def header_footer(self, doc, plan: DocumentPlan) -> None:
        body_font = plan.style.body_font or self.t.fonts.body
        text_muted = plan.style.palette_overrides.get("text_muted", self.t.palette.text_muted)

        def _has_content(part) -> bool:
            if not part:
                return False
            if any(p.text.strip() for p in part.paragraphs):
                return True
            if len(part.tables) > 0:
                return True
            xml = part._element.xml
            return "<w:drawing" in xml or "<w:pict" in xml

        for section in doc.sections:
            if self.styled:
                section.different_first_page_header_footer = True

            if self.styled or not _has_content(section.header):
                if not section.header.paragraphs:
                    section.header.add_paragraph()
                hp = section.header.paragraphs[0]
                hp.text = plan.title
                hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                for r in hp.runs:
                    r.font.size = Pt(9)
                    r.font.color.rgb = _rgb(text_muted)
                    if body_font:
                        r.font.name = body_font
                        r._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), body_font)

            footer = section.footer
            has_footer = _has_content(footer)
            if "PAGE" not in footer._element.xml and (self.styled or not has_footer):
                if not footer.paragraphs:
                    footer.add_paragraph()
                fp = footer.paragraphs[0]
                fp.text = ""
                fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                fp.add_run("Page ")
                _add_field(fp, "PAGE", "1")
                fp.add_run(" of ")
                _add_field(fp, "NUMPAGES", "1")
                for r in fp.runs:
                    r.font.size = Pt(9)
                    r.font.color.rgb = _rgb(text_muted)
                    if body_font:
                        r.font.name = body_font
                        r._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), body_font)

    # ---------------------------------------------------------------- document parts

    def title_page(self, doc, plan: DocumentPlan, audience: str) -> None:
        style = plan.style
        sect_break_p = next(
            (c for c in list(doc.element.body) if c.tag != qn("w:sectPr") and c.xpath(".//w:sectPr")),
            None,
        )

        def _add_p(text: str = "", p_style=None) -> Paragraph:
            if sect_break_p is not None:
                p_elem = doc._body._element._new_p()
                sect_break_p.addprevious(p_elem)
                p = Paragraph(p_elem, doc)
                if p_style is not None:
                    p.style = p_style
                if text:
                    p.text = text
                return p
            return doc.add_paragraph(text, style=p_style)

        if self.cover_logo:
            p_logo = _add_p()
            p_logo.alignment = self.cover_logo_alignment or WD_ALIGN_PARAGRAPH.CENTER
            r_logo = p_logo.add_run()
            width = Inches(self.cover_logo_width_emu / 914400) if self.cover_logo_width_emu else Inches(2.0)
            r_logo.add_picture(io.BytesIO(self.cover_logo), width=width)
        for _ in range(3 if self.cover_logo else 6):
            _add_p()
        p_title = _add_p(plan.title, p_style=self.role_style_map.get("title", "Title"))
        self._format_paragraph(p_title, style, heading=True, level=0)
        if plan.subtitle:
            p_sub = _add_p(plan.subtitle, p_style="Subtitle" if "Subtitle" in doc.styles else None)
            self._format_paragraph(p_sub, style)
        meta = [
            m
            for m in (
                audience and f"Prepared for: {audience}",
                plan.author,
                datetime.now(UTC).strftime("%B %Y"),
            )
            if m
        ]
        p = _add_p(" · ".join(meta))
        text_muted = style.palette_overrides.get("text_muted", self.t.palette.text_muted)
        for r in p.runs:
            r.font.color.rgb = _rgb(text_muted)
            if style.body_font:
                r.font.name = style.body_font
                r._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), style.body_font)
        if sect_break_p is None:
            p.add_run().add_break(WD_BREAK.PAGE)

    def toc(self, doc) -> None:
        heading = doc.add_paragraph("Contents", style="TOC Heading" if "TOC Heading" in doc.styles else None)
        if heading.style.name != "TOC Heading":
            for r in heading.runs:
                r.font.size, r.font.bold = Pt(16), True
        _add_field(
            doc.add_paragraph(),
            'TOC \\o "1-3" \\h \\z \\u',
            "",
        )
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        settings = doc.settings.element
        if settings.find(qn("w:updateFields")) is None:
            upd = OxmlElement("w:updateFields")
            upd.set(qn("w:val"), "true")
            settings.append(upd)

    def _merge_style(self, inherited, local):
        update = {}
        for field_name in (
            "heading_font",
            "body_font",
            "body_size_pt",
            "line_spacing",
            "paragraph_spacing_pt",
            "margins_in",
            "heading_alignment",
            "body_alignment",
            "page_orientation",
        ):
            value = getattr(local, field_name)
            if value is not None:
                update[field_name] = value
        sizes = inherited.heading_sizes_pt.model_dump(exclude_none=True)
        sizes.update(local.heading_sizes_pt.model_dump(exclude_none=True))
        update["heading_sizes_pt"] = inherited.heading_sizes_pt.model_copy(update=sizes)
        colors = dict(inherited.palette_overrides)
        colors.update(local.palette_overrides)
        update["palette_overrides"] = colors
        return inherited.model_copy(update=update)

    def section(self, doc, section: SectionPlan, inherited_style) -> None:
        style = self._merge_style(inherited_style, section.style)
        self._apply_style(style)
        level_key = f"h{min(section.level, 3)}"
        heading_name = self.role_style_map.get(level_key, f"Heading {min(section.level, 3)}")
        heading = doc.add_paragraph(section.heading, style=heading_name)
        self._format_paragraph(heading, style, heading=True, level=section.level)
        for block in section.blocks:
            self.block(doc, block)
        for sub in section.subsections:
            self.section(doc, sub, inherited_style)
        self._apply_style(inherited_style)

    def references(self, doc) -> int:
        entries = self.cite.reference_entries()
        if not entries:
            return 0
        h = doc.add_heading("References", level=1)
        self._format_paragraph(h, self.current_style, heading=True, level=1)
        for entry in entries:
            p = doc.add_paragraph(entry)
            self._format_paragraph(p, self.current_style)
            p.paragraph_format.left_indent = Inches(0.35)
            p.paragraph_format.first_line_indent = Inches(-0.35)
            p.paragraph_format.space_after = Pt(4)
        return len(entries)

    # ---------------------------------------------------------------- blocks

    def _p(self, doc, text: str, claim_ids=(), style: str | None = None):
        paragraph = doc.add_paragraph(
            text + self.cite.marker(claim_ids),
            style=style or self.role_style_map.get("body", "Normal"),
        )
        self._format_paragraph(paragraph, self.current_style)
        return paragraph

    def block(self, doc, block) -> None:
        if isinstance(block, ParagraphBlock):
            self._p(doc, block.text, block.claim_ids)
        elif isinstance(block, BulletsBlock):
            for item in block.items:
                style = "List Bullet" if item.level == 0 else "List Bullet 2"
                self._p(doc, item.text, [*item.claim_ids, *block.claim_ids][:4], style=style)
        elif isinstance(block, TableBlock):
            self.table(doc, block.columns, block.rows, block.caption, block.claim_ids)
        elif isinstance(block, ChartBlock):
            self.chart(doc, block)
        elif isinstance(block, TimelineBlock):
            rows = [
                [e.date or "", e.label + (f" — {e.description}" if e.description else "")]
                for e in block.events
            ]
            self.table(doc, ["When", "What"], rows, None, block.claim_ids, widths=(1.3, 5.2))
        elif isinstance(block, ProcessBlock):
            for i, step in enumerate(block.steps, 1):
                p = doc.add_paragraph(style="List Number")
                p.add_run(step.title).bold = True
                if step.description:
                    p.add_run(f" — {step.description}")
                self._format_paragraph(p, self.current_style)
                del i
        elif isinstance(block, ComparisonBlock):
            depth = max(len(c.points) for c in block.columns)
            rows = [[c.points[i] if i < len(c.points) else "" for c in block.columns] for i in range(depth)]
            self.table(doc, [c.heading for c in block.columns], rows, None, block.claim_ids)
        elif isinstance(block, KPIBlock):
            self.kpis(doc, block)
        elif isinstance(block, QuoteBlock):
            style = "Intense Quote" if "Intense Quote" in doc.styles else None
            self._p(
                doc,
                f"“{block.text}”" + (f" — {block.attribution}" if block.attribution else ""),
                block.claim_ids,
                style=style,
            )
        elif isinstance(block, CalloutBlock):
            table = doc.add_table(rows=1, cols=1)
            cell = table.cell(0, 0)
            surface = self.current_style.palette_overrides.get("surface", self.t.palette.surface)
            _shade(cell, surface)
            p = cell.paragraphs[0]
            run = p.add_run(block.text + self.cite.marker(block.claim_ids))
            run.bold = True
            body_font = self.current_style.body_font or self.t.fonts.body
            if body_font:
                run.font.name = body_font
                run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), body_font)
            if self.current_style.body_size_pt is not None:
                run.font.size = Pt(self.current_style.body_size_pt)
            text_color = self.current_style.palette_overrides.get("text", self.t.palette.text)
            run.font.color.rgb = _rgb(text_color)
            if self.current_style.body_alignment:
                p.alignment = _ALIGNMENT[self.current_style.body_alignment]
            doc.add_paragraph()
        elif isinstance(block, ImageBlock) and block.asset_path and self.assets is not None:
            self.figures += 1
            doc.add_picture(str(self.assets(block.asset_path)), width=Inches(6.0))
            pic = doc.paragraphs[-1]
            pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
            doc_pr = pic._p.xpath(".//wp:docPr")
            if doc_pr:
                doc_pr[0].set("descr", block.alt_text)
            credit = f" {block.credit}." if block.credit else ""
            self._p(doc, f"Figure {self.figures}: {block.alt_text}.{credit}", style="Caption")

    def table(self, doc, columns, rows, caption, claim_ids, widths=None) -> None:
        self.tables += 1
        table = doc.add_table(rows=1, cols=len(columns))
        table.style = "Table Grid" if "Table Grid" in doc.styles else table.style
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        primary = self.current_style.palette_overrides.get("primary", self.t.palette.primary)
        surface = self.current_style.palette_overrides.get("surface", self.t.palette.surface)
        header_text = readable_on(primary)
        heading_font = self.current_style.heading_font or self.current_style.body_font or self.t.fonts.heading
        body_font = self.current_style.body_font or self.t.fonts.body
        for i, col in enumerate(columns):
            cell = table.rows[0].cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(str(col))
            run.bold = True
            run.font.color.rgb = _rgb(header_text)
            if heading_font:
                run.font.name = heading_font
                run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), heading_font)
            _shade(cell, primary)
        _repeat_header(table.rows[0])
        for r_i, row in enumerate(rows):
            cells = table.add_row().cells
            for c_i, value in enumerate(row):
                cells[c_i].text = ""
                run = cells[c_i].paragraphs[0].add_run(str(value))
                if body_font:
                    run.font.name = body_font
                    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), body_font)
                if self.current_style.body_size_pt is not None:
                    run.font.size = Pt(self.current_style.body_size_pt)
                text_color = self.current_style.palette_overrides.get("text", self.t.palette.text)
                run.font.color.rgb = _rgb(text_color)
                if r_i % 2 == 1:
                    _shade(cells[c_i], surface)
        if widths:
            for row in table.rows:
                for cell, w in zip(row.cells, widths, strict=False):
                    cell.width = Inches(w)
        label = f"Table {self.tables}" + (f": {caption}" if caption else "")
        self._p(doc, label, claim_ids, style="Caption")

    def chart(self, doc, block: ChartBlock) -> None:
        self.figures += 1
        png = chart_png(block, self.t.palette.accents[:4], self.tmp / f"fig{self.figures}.png")
        doc.add_picture(str(png), width=Inches(6.0))
        pic = doc.paragraphs[-1]
        pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
        doc_pr = pic._p.xpath(".//wp:docPr")
        if doc_pr:
            doc_pr[0].set("descr", block.title or f"{block.chart_type.value} chart")
        title = block.title or ", ".join(s.name for s in block.series)
        self._p(
            doc,
            f"Figure {self.figures}: {title}" + (f" ({block.unit})" if block.unit else ""),
            block.claim_ids,
            style="Caption",
        )

    def kpis(self, doc, block: KPIBlock) -> None:
        table = doc.add_table(rows=2, cols=len(block.metrics))
        primary = self.current_style.palette_overrides.get("primary", self.t.palette.primary)
        surface = self.current_style.palette_overrides.get("surface", self.t.palette.surface)
        heading_font = self.current_style.heading_font or self.t.fonts.heading
        body_font = self.current_style.body_font or self.t.fonts.body
        for i, m in enumerate(block.metrics):
            top, bottom = table.cell(0, i), table.cell(1, i)
            for c in (top, bottom):
                _shade(c, surface)
            run = top.paragraphs[0].add_run(m.value)
            run.bold, run.font.size = True, Pt(20)
            run.font.color.rgb = _rgb(primary)
            if heading_font:
                run.font.name = heading_font
                run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), heading_font)
            label = m.label + (f" ({m.delta})" if m.delta else "") + self.cite.marker(m.claim_ids)
            bottom_run = bottom.paragraphs[0].add_run(label)
            bottom_run.font.size = Pt(9.5)
            if body_font:
                bottom_run.font.name = body_font
                bottom_run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), body_font)
            text_muted = self.current_style.palette_overrides.get("text_muted", self.t.palette.text_muted)
            bottom_run.font.color.rgb = _rgb(text_muted)
        doc.add_paragraph()


def _extract_cover_logo(doc) -> tuple[bytes | None, int | None, WD_ALIGN_PARAGRAPH | None]:
    for p in doc.paragraphs[:10]:
        xml = p._element.xml
        if "<w:drawing" in xml or "<w:pict" in xml:
            for blip in p._p.xpath(".//a:blip"):
                rid = blip.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                if not rid:
                    continue
                target_part = getattr(doc.part, "related_parts", {}).get(rid)
                if target_part is None and hasattr(doc.part, "rels") and rid in doc.part.rels:
                    target_part = doc.part.rels[rid].target_part
                if target_part and hasattr(target_part, "blob"):
                    exts = p._p.xpath(".//wp:extent")
                    cx = int(exts[0].attrib.get("cx")) if exts and exts[0].attrib.get("cx") else None
                    alignment = p.alignment
                    return target_part.blob, cx, alignment
    return None, None, None


def render_document(
    plan: DocumentPlan,
    tokens: DesignTokens,
    out_path: Path,
    *,
    dossier: ResearchDossier | None = None,
    citation_style: CitationStyle = CitationStyle.numeric,
    audience: str = "",
    template: Path | None = None,
    template_manifest=None,
    asset_resolver=None,
) -> DocRenderResult:
    doc = Document(str(template)) if template else Document()
    cover_logo, cover_w, cover_align = None, None, None
    if template:
        cover_logo, cover_w, cover_align = _extract_cover_logo(doc)
        _clear_body(doc)

    if cover_logo is None and template_manifest is not None and template_manifest.docx is not None:
        for asset in template_manifest.docx.image_assets:
            if (
                asset.is_logo
                and asset.location == "body"
                and asset.file_path
                and Path(asset.file_path).exists()
            ):
                try:
                    cover_logo = Path(asset.file_path).read_bytes()
                    cover_w = asset.width_emu
                    break
                except OSError:
                    pass

    fig_dir = out_path.parent / f".{out_path.stem}-figures"
    renderer = DocxRenderer(
        tokens,
        Citations(dossier, citation_style),
        styled=template is None,
        fig_dir=fig_dir,
        assets=asset_resolver,
        cover_logo=cover_logo,
        cover_logo_width_emu=cover_w,
        cover_logo_alignment=cover_align,
    )
    if template_manifest is not None and template_manifest.docx is not None:
        renderer.role_style_map = template_manifest.docx.role_style_map
    renderer.setup_styles(doc, plan)
    doc.core_properties.title = plan.title[:255]
    doc.core_properties.author = plan.author or "DocForge"

    renderer.title_page(doc, plan, audience)
    if plan.front_matter.include_toc:
        renderer.toc(doc)
    if plan.front_matter.abstract:
        h = doc.add_heading("Abstract", level=1)
        renderer._format_paragraph(h, plan.style, heading=True, level=1)
        p = doc.add_paragraph(plan.front_matter.abstract)
        renderer._format_paragraph(p, plan.style)
    if plan.front_matter.executive_summary:
        h = doc.add_heading("Executive summary", level=1)
        renderer._format_paragraph(h, plan.style, heading=True, level=1)
        for block in plan.front_matter.executive_summary:
            renderer.block(doc, block)
    for section in plan.sections:
        renderer.section(doc, section, plan.style)
    references = renderer.references(doc)
    renderer.header_footer(doc, plan)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out_path))
    text = "\n".join(p.text for p in doc.paragraphs)
    headings = [
        (int(p.style.name.split()[-1]), p.text)
        for p in doc.paragraphs
        if re.fullmatch(r"Heading [1-9]", p.style.name)
    ]
    return DocRenderResult(
        out_path, len(text.split()), renderer.tables, renderer.figures, references, headings
    )
