from __future__ import annotations

import io
from pathlib import Path

import pytest
from pptx import Presentation

from docforge.design.system import tokens_from_theme
from docforge.models.conversation import FileRole, Message, Role, Session, UploadedFile
from docforge.models.intent import Interpretation, OutputFormat, OutputSpec, ResearchNeed
from docforge.models.template import ElementRole, LayoutArchetype
from docforge.orchestrator.generate import GenerationService
from docforge.template.pptx_analyzer import analyze_pptx
from docforge.validate.deck import build_deck
from tests.fixtures.decks import sample_deck
from tests.fixtures.templates import SAMPLE_BULLET, SAMPLE_TITLE, corporate_pptx

pytestmark = pytest.mark.anyio


@pytest.fixture
def template(tmp_path: Path) -> Path:
    return corporate_pptx(tmp_path / "corporate.pptx")


def test_analyzer_reads_theme_layouts_and_roles(template: Path):  # FR-TPL-2/3/4
    m = analyze_pptx(template)
    assert m.theme.colors["accent1"] == "C0392B" and m.theme.colors["accent2"] == "2C3E50"
    assert (m.theme.major_font, m.theme.minor_font) == ("Georgia", "Verdana")
    assert m.pptx.slide_width == 9144000 and m.pptx.slide_height == 6858000
    by_name = {lay.name: lay.archetype for lay in m.pptx.layouts}
    assert by_name["Title Slide"] == LayoutArchetype.title
    assert by_name["Title and Content"] == LayoutArchetype.content
    assert by_name["Section Header"] == LayoutArchetype.section
    assert by_name["Title Only"] == LayoutArchetype.title_only
    assert by_name["Comparison"] == LayoutArchetype.comparison
    assert by_name["Blank"] == LayoutArchetype.blank
    assert len(m.pptx.sample_slides) == 3
    roles = {(e.name, e.role) for inv in m.pptx.sample_slides for e in inv.elements}
    assert ("Company Logo", ElementRole.branding) in roles
    assert any(role == ElementRole.sample_content for name, role in roles if name.startswith("Title"))


def test_tokens_follow_theme(template: Path):
    tokens = tokens_from_theme(analyze_pptx(template).theme, "topic")
    assert tokens.source == "template" and tokens.palette.primary == "C0392B"
    assert (tokens.fonts.heading, tokens.fonts.body) == ("Georgia", "Verdana")


def test_render_on_template_keeps_identity_and_drops_samples(template: Path, tmp_path: Path):  # FR-PPTX-2/7
    manifest = analyze_pptx(template)
    deck = sample_deck()
    tokens = tokens_from_theme(manifest.theme, deck.title)
    build = build_deck(
        deck,
        tokens,
        tmp_path / "out",
        spec=None,
        dossier=None,
        max_iterations=3,
        libreoffice=None,
        template=template,
        manifest=manifest,
    )
    unresolved = [f.message for f in build.report.findings if f.status != "corrected"]
    assert unresolved == [], unresolved
    checks = {c.check_id: c.status for c in build.report.checks}
    assert (
        checks["pptx.template_fonts"]
        == checks["pptx.sample_residue"]
        == checks["pptx.branding_retained"]
        == "passed"
    )

    prs = Presentation(str(build.path))
    assert len(prs.slides) == len(build.deck.slides)  # 13 new slides, the 3 samples are gone
    assert prs.slide_width == 9144000  # 4:3 template size kept
    layouts = [s.slide_layout.name for s in prs.slides]
    assert layouts[0] == "Title Slide" and layouts[2] == "Section Header" and "Title Only" in layouts
    text = " ".join(sh.text_frame.text for s in prs.slides for sh in s.shapes if sh.has_text_frame)
    assert SAMPLE_TITLE not in text and SAMPLE_BULLET not in text
    title_ph = prs.slides[3].shapes.title
    assert (
        title_ph is not None and title_ph.name == "content:headline"
    )  # headline in the layout's placeholder
    assert all(any(sh.name.startswith("branding:") for sh in s.shapes) for s in prs.slides)
    assert not any(
        ph.has_text_frame and not ph.text_frame.text.strip() for s in prs.slides for ph in s.placeholders
    )


def test_template_with_wide_slides(tmp_path: Path):
    template = corporate_pptx(tmp_path / "wide.pptx", widescreen=True)
    manifest = analyze_pptx(template)
    deck = sample_deck()
    build = build_deck(
        deck,
        tokens_from_theme(manifest.theme, "x"),
        tmp_path / "w",
        spec=None,
        dossier=None,
        max_iterations=3,
        libreoffice=None,
        template=template,
        manifest=manifest,
    )
    assert Presentation(str(build.path)).slide_width == manifest.pptx.slide_width
    assert [f.message for f in build.report.findings if f.status != "corrected"] == []


async def test_generation_uses_uploaded_template_and_caches_manifest(container, fake_llm, template: Path):
    ref = container.blobs.put_file(template)
    container.repos.sessions.put(Session(id="ses_1", owner="demo"))
    container.repos.files.put(
        UploadedFile(
            id="fil_t",
            session_id="ses_1",
            filename="corporate.pptx",
            media_type="x",
            size=ref.size,
            sha256=ref.sha256,
            role=FileRole.template,
            blob_path=ref.path,
        )
    )
    fake_llm.add(
        "interpreter",
        Interpretation(
            kind="new_task",
            confidence=0.9,
            objective="EV deck",
            output_spec=OutputSpec(format=OutputFormat.pptx),
            research=ResearchNeed(depth="none"),
        ),
    )
    fake_llm.add("deck_planner", sample_deck())
    session = container.repos.sessions.require("ses_1")
    msg = container.repos.messages.put(Message(id="m1", session_id="ses_1", role=Role.user, content="deck"))
    reply = await GenerationService(container).handle_message(session, msg)

    assert "Built on your template “corporate.pptx”" in reply.message.content
    assert "Template 'corporate.pptx'" in fake_llm.calls_for("deck_planner")[0].messages[0].content
    assert container.repos.templates.get(ref.sha256) is not None
    prs = Presentation(io.BytesIO(container.blobs.read_bytes(reply.version.blob_path)))
    assert prs.slides[0].slide_layout.name == "Title Slide"
    assert reply.version.design_tokens.source == "template"
