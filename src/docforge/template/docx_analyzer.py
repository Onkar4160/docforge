"""Deterministic DOCX template inspection into the shared TemplateManifest."""

from __future__ import annotations

import hashlib
from pathlib import Path

from docx import Document

from docforge.models.intent import OutputFormat
from docforge.models.template import (
    DocxTemplateInfo,
    FontSpec,
    PropertySource,
    SectionInfo,
    StyleInfo,
    TemplateManifest,
    ThemeSpec,
)

ANALYZER_VERSION = 2


def _font(style) -> FontSpec | None:
    font = getattr(style, "font", None)
    if font is None:
        return None
    base_style = getattr(style, "base_style", None)
    base = getattr(base_style, "font", None) if base_style is not None else None
    values = {}
    sources = {}
    for name in ("name", "size", "bold"):
        value = getattr(font, name)
        inherited = getattr(base, name) if base is not None else None
        values[name] = value if value is not None else inherited
        sources[name] = (
            PropertySource.explicit
            if value is not None
            else PropertySource.inherited
            if inherited is not None
            else PropertySource.unknown
        )
    color = None
    color_source = PropertySource.unknown
    if font.color is not None:
        if font.color.rgb is not None:
            color = str(font.color.rgb).upper()
            color_source = PropertySource.explicit
        elif font.color.theme_color is not None:
            color = f"theme:{font.color.theme_color.name.lower().replace('_', '')}"
            color_source = PropertySource.explicit
    if color is None and base is not None and base.color is not None:
        if base.color.rgb is not None:
            color = str(base.color.rgb).upper()
            color_source = PropertySource.inherited
        elif base.color.theme_color is not None:
            color = f"theme:{base.color.theme_color.name.lower().replace('_', '')}"
            color_source = PropertySource.inherited
    if not any(value is not None for value in values.values()) and color is None:
        return None
    return FontSpec(
        name=values["name"],
        size_pt=values["size"].pt if values["size"] is not None else None,
        bold=values["bold"],
        color=color,
        name_source=sources["name"],
        size_source=sources["size"],
        bold_source=sources["bold"],
        color_source=color_source,
    )


def analyze_docx(path: Path, *, template_id: str | None = None) -> TemplateManifest:
    data = path.read_bytes()
    doc = Document(str(path))
    used = {paragraph.style.style_id for paragraph in doc.paragraphs if paragraph.style is not None}
    used.update(table.style.style_id for table in doc.tables if table.style is not None)
    styles = [
        StyleInfo(
            name=style.name,
            style_id=style.style_id,
            type=style.type.__str__(),
            based_on=getattr(getattr(style, "base_style", None), "style_id", None),
            font=_font(style),
            in_use=style.style_id in used,
        )
        for style in doc.styles
    ]
    sections = []
    for section in doc.sections:
        header = "\n".join(p.text for p in section.header.paragraphs if p.text)
        footer = "\n".join(p.text for p in section.footer.paragraphs if p.text)
        sections.append(
            SectionInfo(
                page_width=int(section.page_width),
                page_height=int(section.page_height),
                orientation=section.orientation.name.lower(),
                margins={
                    "top": int(section.top_margin),
                    "bottom": int(section.bottom_margin),
                    "left": int(section.left_margin),
                    "right": int(section.right_margin),
                },
                header_text=header,
                footer_text=footer,
                has_page_number="PAGE" in section.header._element.xml
                or "PAGE" in section.footer._element.xml,
            )
        )
    by_name = {style.name.lower(): style.name for style in doc.styles}
    role_map = {
        role: by_name[name]
        for role, name in (
            ("title", "title"),
            ("h1", "heading 1"),
            ("h2", "heading 2"),
            ("h3", "heading 3"),
            ("body", "normal"),
            ("caption", "caption"),
        )
        if name in by_name
    }
    normal = next((style for style in styles if style.name.lower() == "normal"), None)
    heading = next((style for style in styles if style.name.lower() == "heading 1"), None)
    return TemplateManifest(
        id=template_id or f"tpl_{hashlib.sha256(data).hexdigest()[:12]}",
        format=OutputFormat.docx,
        file_sha256=hashlib.sha256(data).hexdigest(),
        theme=ThemeSpec(
            major_font=heading.font.name if heading and heading.font else None,
            minor_font=normal.font.name if normal and normal.font else None,
        ),
        docx=DocxTemplateInfo(
            styles=styles,
            sections=sections,
            has_toc="TOC" in doc.element.body.xml,
            paragraph_count=len(doc.paragraphs),
            table_count=len(doc.tables),
            role_style_map=role_map,
        ),
        analyzer_version=ANALYZER_VERSION,
    )
