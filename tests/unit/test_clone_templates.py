"""Templates whose design lives on the sample slides (Canva-style): clone mode (ADR-019)."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.util import Inches, Pt

from docforge.design.system import tokens_from_template
from docforge.layout.backdrop import color_under
from docforge.render.pptx.clone import assign_bases
from docforge.render.pptx.composer import effective_archetype
from docforge.template.pptx_analyzer import analyze_pptx
from docforge.validate.deck import build_deck
from tests.fixtures.decks import sample_deck

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _png(color, size=(320, 180)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def canva_like(path: Path) -> Path:
    """Blank layouts; every sample slide carries a full-bleed background picture, a cream panel, a leaf
    picture, a title box and Lorem ipsum body text, like a Canva export."""
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(20), Inches(11.25)
    blank = prs.slide_layouts[6]
    bg, leaf = _png((200, 225, 210)), _png((70, 120, 60), (60, 60))

    def text(slide, x, y, w, h, value, size, bold=False):
        box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        run = box.text_frame.paragraphs[0].add_run()
        run.text, run.font.size, run.font.bold, run.font.name = value, Pt(size), bold, "Montserrat"
        run.font.color.rgb = __import__("pptx.dml.color", fromlist=["RGBColor"]).RGBColor(0x1E, 0x2E, 0x1D)
        return box

    for i, (title, body) in enumerate(
        [
            ("Presentation", "Presented by Someone"),
            ("Introduction", "Lorem ipsum " * 30),
            ("Overview", "Lorem ipsum dolor " * 20),
            ("Results", "Lorem ipsum sit " * 25),
            ("Thank You", "Presented by Someone"),
        ]
    ):
        s = prs.slides.add_slide(blank)
        s.shapes.add_picture(io.BytesIO(bg), 0, 0, prs.slide_width, prs.slide_height).name = "Background"
        if 0 < i < 4:
            panel = s.shapes.add_shape(1, Inches(3), Inches(3.5), Inches(14), Inches(6.5))
            panel.fill.solid()
            panel.fill.fore_color.rgb = __import__("pptx.dml.color", fromlist=["RGBColor"]).RGBColor(
                0xF4, 0xDD, 0xC0
            )
            panel.line.fill.background()
            panel.name = "Panel"
        s.shapes.add_picture(io.BytesIO(leaf), Inches(17), Inches(8), Inches(2.5), Inches(2.5)).name = "Leaf"
        text(s, 5, 0.8, 10, 2, title, 88 if i in (0, 4) else 72, bold=True)
        if i in (0, 4):
            text(s, 6, 3.2, 8, 0.8, body, 24)
        else:
            text(s, 4, 4.2, 12, 3, body, 20)
    prs.save(str(path))
    return path


@pytest.fixture
def template(tmp_path: Path) -> Path:
    return canva_like(tmp_path / "canva.pptx")


def test_design_on_slides_is_detected(template: Path):
    m = analyze_pptx(template)
    info = m.pptx
    assert info.design_mode == "slides"
    kinds = [b.kind for b in info.slide_bases]
    assert kinds == ["cover", "content", "content", "content", "closing"]
    content = info.slide_bases[1]
    assert content.region is not None and content.region_color == "F4DDC0"  # the cream panel
    assert (
        info.slide_fonts == {"heading": "Montserrat", "body": "Montserrat"}
        and info.slide_text_color == "1E2E1D"
    )


def test_bases_rotate_and_match_roles(template: Path):
    m = analyze_pptx(template)
    deck = sample_deck()
    bases = assign_bases([effective_archetype(s) for s in deck.slides], m)
    assert bases[0].kind == "cover" and bases[-1].kind in ("closing", "cover")
    indices = [b.index for b in bases]
    assert all(a != b for a, b in zip(indices, indices[1:], strict=False) if a not in (0, 4))


def test_clone_render_keeps_artwork_and_drops_sample_text(template: Path, tmp_path: Path):
    m = analyze_pptx(template)
    build = build_deck(
        sample_deck(),
        tokens_from_template(m, "ev"),
        tmp_path / "out",
        spec=None,
        dossier=None,
        max_iterations=3,
        libreoffice=None,
        template=template,
        manifest=m,
    )
    assert [f.message for f in build.report.findings if f.status != "corrected"] == []
    prs = Presentation(str(build.path))
    assert len(prs.slides) == len(build.deck.slides)  # the 5 sample slides are gone
    text = " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    assert "Lorem ipsum" not in text and "Presented by Someone" not in text
    for slide in prs.slides:
        names = [sh.name for sh in slide.shapes]
        assert "Background" in names and "Leaf" in names  # template artwork copied onto every slide
    cover = prs.slides[0]
    title = next(sh for sh in cover.shapes if sh.name == "content:title")
    run = title.text_frame.paragraphs[0].runs[0]
    assert run.font.name == "Montserrat" and str(run.font.color.rgb) == "1E2E1D"  # template styling kept
    pic_rels = [r for r in cover.part.rels.values() if r.reltype.endswith("/image")]
    assert pic_rels  # images re-linked on the clone, not pointing at removed slides


def test_color_under_sees_pictures_and_panels(template: Path):
    prs = Presentation(str(template))
    slide = prs.slides[1]
    E = 914400
    assert color_under(slide, (int(10 * E), int(6 * E), E, E)) == "F4DDC0"  # on the panel
    assert color_under(slide, (int(0.5 * E), int(0.5 * E), E, E)) == "C8E1D2"  # background picture
    assert etree is not None and _A
