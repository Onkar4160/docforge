"""DocumentPlan → editable DOCX (Stage 9, FR-DOCX-1..5).

Without a template, a clean style set is defined from design tokens. With a template, its styles,
page setup, headers and footers are kept and only the body content is replaced (FR-DOCX-4).
Formatting is applied through named styles, so later restyles touch styles, not runs (FR-DOCX-5).
"""

from __future__ import annotations

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


@dataclass
class DocRenderResult:
    path: Path
    words: int
    tables: int
    figures: int
    references: int
    headings: list[tuple[int, str]] = field(default_factory=list)


def _rgb(hex_color: str) -> RGBColor:
    return RGBColor.from_string(hex_color.upper())


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
    paragraph.add_run(placeholder)
    fld("end")


def _shade(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill.upper())
    tc_pr.append(shd)


def _repeat_header(row) -> None:
    tr_pr = row._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    tr_pr.append(el)


def _clear_body(doc) -> None:
    body = doc.element.body
    for child in list(body):
        if child.tag != qn("w:sectPr"):
            body.remove(child)


class DocxRenderer:
    def __init__(
        self, tokens: DesignTokens, citations: Citations, *, styled: bool, fig_dir: Path, assets=None
    ) -> None:
        self.assets = assets
        self.t = tokens
        self.cite = citations
        self.styled = styled  # False when a template provides the styles
        self.tables = 0
        self.figures = 0
        self.tmp = fig_dir

    # ---------------------------------------------------------------- styles

    def setup_styles(self, doc, plan: DocumentPlan) -> None:
        if not self.styled:
            return
        sizes = {**DEFAULT_SIZES, **{k: v for k, v in plan.style.heading_sizes_pt.model_dump().items() if v}}
        body_font = plan.style.body_font or self.t.fonts.body
        heading_font = plan.style.heading_font or self.t.fonts.heading
        normal = doc.styles["Normal"]
        normal.font.name = body_font
        normal.element.rPr.rFonts.set(qn("w:eastAsia"), body_font)
        normal.font.size = Pt(plan.style.body_size_pt or 11)
        normal.font.color.rgb = _rgb(self.t.palette.text)
        fmt = normal.paragraph_format
        fmt.space_after = Pt(plan.style.paragraph_spacing_pt or 8)
        fmt.line_spacing = plan.style.line_spacing or 1.15
        for name, size_key, color in (
            ("Title", "title", self.t.palette.primary),
            ("Heading 1", "h1", self.t.palette.primary),
            ("Heading 2", "h2", self.t.palette.primary),
            ("Heading 3", "h3", self.t.palette.text),
        ):
            style = doc.styles[name]
            style.font.name = heading_font
            style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), heading_font)
            style.font.size = Pt(sizes[size_key])
            style.font.bold = name != "Title"
            style.font.color.rgb = _rgb(color)
            style.paragraph_format.space_before = Pt(18 if name == "Heading 1" else 12)
            style.paragraph_format.space_after = Pt(6)
            style.paragraph_format.keep_with_next = True
        for name in ("Subtitle", "Caption", "Quote"):
            if name in doc.styles:
                doc.styles[name].font.name = body_font
        if "Caption" in doc.styles:
            doc.styles["Caption"].font.color.rgb = _rgb(self.t.palette.text_muted)
        margins = Inches(plan.style.margins_in or 1.0)
        for section in doc.sections:
            section.orientation = WD_ORIENT.PORTRAIT
            section.left_margin = section.right_margin = margins
            section.top_margin = section.bottom_margin = margins

    def header_footer(self, doc, plan: DocumentPlan) -> None:
        section = doc.sections[0]
        section.different_first_page_header_footer = True
        if self.styled or not section.header.paragraphs[0].text.strip():
            hp = section.header.paragraphs[0]
            hp.text = plan.title
            hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            for r in hp.runs:
                r.font.size = Pt(9)
                r.font.color.rgb = _rgb(self.t.palette.text_muted)
        footer = section.footer
        if "PAGE" not in footer._element.xml:
            fp = footer.paragraphs[0]
            fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
            fp.add_run("Page ")
            _add_field(fp, "PAGE", "1")
            fp.add_run(" of ")
            _add_field(fp, "NUMPAGES", "1")
            for r in fp.runs:
                r.font.size = Pt(9)

    # ---------------------------------------------------------------- document parts

    def title_page(self, doc, plan: DocumentPlan, audience: str) -> None:
        for _ in range(6):
            doc.add_paragraph()
        doc.add_paragraph(plan.title, style="Title")
        if plan.subtitle:
            doc.add_paragraph(plan.subtitle, style="Subtitle" if "Subtitle" in doc.styles else None)
        meta = [
            m
            for m in (
                audience and f"Prepared for: {audience}",
                plan.author,
                datetime.now(UTC).strftime("%B %Y"),
            )
            if m
        ]
        p = doc.add_paragraph(" · ".join(meta))
        for r in p.runs:
            r.font.color.rgb = _rgb(self.t.palette.text_muted)
        p.add_run().add_break(WD_BREAK.PAGE)

    def toc(self, doc) -> None:
        heading = doc.add_paragraph("Contents", style="TOC Heading" if "TOC Heading" in doc.styles else None)
        if heading.style.name != "TOC Heading":
            for r in heading.runs:
                r.font.size, r.font.bold = Pt(16), True
        _add_field(
            doc.add_paragraph(),
            'TOC \\o "1-3" \\h \\z \\u',
            "Right-click and choose Update Field to build the table of contents.",
        )
        doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        settings = doc.settings.element
        if settings.find(qn("w:updateFields")) is None:
            upd = OxmlElement("w:updateFields")
            upd.set(qn("w:val"), "true")
            settings.append(upd)

    def section(self, doc, section: SectionPlan) -> None:
        doc.add_heading(section.heading, level=min(section.level, 3))
        for block in section.blocks:
            self.block(doc, block)
        for sub in section.subsections:
            self.section(doc, sub)

    def references(self, doc) -> int:
        entries = self.cite.reference_entries()
        if not entries:
            return 0
        doc.add_heading("References", level=1)
        for entry in entries:
            p = doc.add_paragraph(entry)
            p.paragraph_format.left_indent = Inches(0.35)
            p.paragraph_format.first_line_indent = Inches(-0.35)
            p.paragraph_format.space_after = Pt(4)
        return len(entries)

    # ---------------------------------------------------------------- blocks

    def _p(self, doc, text: str, claim_ids=(), style: str | None = None):
        return doc.add_paragraph(text + self.cite.marker(claim_ids), style=style)

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
            _shade(cell, self.t.palette.surface)
            cell.paragraphs[0].add_run(block.text + self.cite.marker(block.claim_ids)).bold = True
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
        header_text = readable_on(self.t.palette.primary)
        for i, col in enumerate(columns):
            cell = table.rows[0].cells[i]
            cell.text = ""
            run = cell.paragraphs[0].add_run(str(col))
            run.bold = True
            run.font.color.rgb = _rgb(header_text)
            _shade(cell, self.t.palette.primary)
        _repeat_header(table.rows[0])
        for r_i, row in enumerate(rows):
            cells = table.add_row().cells
            for c_i, value in enumerate(row):
                cells[c_i].text = str(value)
                if r_i % 2 == 1:
                    _shade(cells[c_i], self.t.palette.surface)
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
        for i, m in enumerate(block.metrics):
            top, bottom = table.cell(0, i), table.cell(1, i)
            for c in (top, bottom):
                _shade(c, self.t.palette.surface)
            run = top.paragraphs[0].add_run(m.value)
            run.bold, run.font.size = True, Pt(20)
            run.font.color.rgb = _rgb(self.t.palette.primary)
            label = m.label + (f" ({m.delta})" if m.delta else "") + self.cite.marker(m.claim_ids)
            bottom.paragraphs[0].add_run(label).font.size = Pt(9.5)
        doc.add_paragraph()


def render_document(
    plan: DocumentPlan,
    tokens: DesignTokens,
    out_path: Path,
    *,
    dossier: ResearchDossier | None = None,
    citation_style: CitationStyle = CitationStyle.numeric,
    audience: str = "",
    template: Path | None = None,
    asset_resolver=None,
) -> DocRenderResult:
    doc = Document(str(template)) if template else Document()
    if template:
        _clear_body(doc)
    fig_dir = out_path.parent / f".{out_path.stem}-figures"
    renderer = DocxRenderer(
        tokens,
        Citations(dossier, citation_style),
        styled=template is None,
        fig_dir=fig_dir,
        assets=asset_resolver,
    )
    renderer.setup_styles(doc, plan)
    doc.core_properties.title = plan.title[:255]
    doc.core_properties.author = plan.author or "DocForge"

    renderer.title_page(doc, plan, audience)
    if plan.front_matter.include_toc:
        renderer.toc(doc)
    if plan.front_matter.abstract:
        doc.add_heading("Abstract", level=1)
        doc.add_paragraph(plan.front_matter.abstract)
    if plan.front_matter.executive_summary:
        doc.add_heading("Executive summary", level=1)
        for block in plan.front_matter.executive_summary:
            renderer.block(doc, block)
    for section in plan.sections:
        renderer.section(doc, section)
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
