"""Stale template caches, the shorten-and-rebuild round, and the planner's template hints."""

from __future__ import annotations

from pathlib import Path

import pytest

from docforge.models.conversation import FileRole, Message, Role, Session, UploadedFile
from docforge.models.intent import Interpretation, LengthSpec, OutputFormat, OutputSpec, ResearchNeed
from docforge.models.ir import BulletItem, BulletsBlock
from docforge.models.quality import Dimension, Finding, QualityReport, Severity
from docforge.models.template import TemplateDesignAnalysis
from docforge.orchestrator.generate import GenerationService, fit_problems, template_summary
from docforge.template.pptx_analyzer import ANALYZER_VERSION, analyze_pptx
from tests.fixtures.decks import sample_deck
from tests.unit.test_clone_templates import canva_like

pytestmark = pytest.mark.anyio


def _interp(**kw) -> Interpretation:
    return Interpretation(
        kind="new_task",
        confidence=0.9,
        objective="EV deck",
        output_spec=OutputSpec(format=OutputFormat.pptx, **kw),
        research=ResearchNeed(depth="none"),
    )


def test_fit_problems_one_instruction_per_slide():
    findings = [
        Finding(
            id="f1",
            check_id="pptx.text_overflow",
            dimension=Dimension.layout,
            severity=Severity.critical,
            message="text in 'content:body' overflows",
            unit_id="s03",
        ),
        Finding(
            id="f2",
            check_id="pptx.font_floor",
            dimension=Dimension.typography,
            severity=Severity.major,
            message="'content:body' uses 12pt",
            unit_id="s03-2",
        ),
        Finding(
            id="f3",
            check_id="a11y.contrast",
            dimension=Dimension.accessibility,
            severity=Severity.major,
            message="contrast",
            unit_id="s04",
        ),
    ]
    report = QualityReport(id="r", artifact_id="a", version=1, findings=findings).finalize()
    problems = fit_problems(report)
    assert len(problems) == 1 and problems[0].startswith("Slide s03: text does not fit")


async def test_overflowing_fixed_length_deck_is_shortened_once(container, fake_llm):  # FR-PPTX-5
    long = sample_deck()
    bullets = long.slides[-2]
    bullets.blocks = [BulletsBlock(items=[BulletItem(text="considerable " * 30) for _ in range(6)])]
    fake_llm.add("interpreter", _interp(length=LengthSpec(unit="slides", target=13, explicit=True)))
    fake_llm.add("deck_planner", long, sample_deck())
    container.repos.sessions.put(Session(id="ses_1", owner="demo"))
    msg = container.repos.messages.put(Message(id="m1", session_id="ses_1", role=Role.user, content="deck"))
    reply = await GenerationService(container).handle_message(container.repos.sessions.require("ses_1"), msg)
    calls = fake_llm.calls_for("deck_planner")
    assert len(calls) == 2 and "text does not fit" in calls[1].messages[-1].content
    assert reply.report.summary.unresolved == 0


async def test_stale_cached_template_analysis_is_recomputed(container, fake_llm, tmp_path: Path):  # FR-TPL-8
    template = canva_like(tmp_path / "canva.pptx")
    ref = container.blobs.put_file(template)
    stale = analyze_pptx(template).model_copy(update={"analyzer_version": 0})
    stale.pptx.design_mode = "layouts"
    container.repos.templates.put(stale)
    container.repos.sessions.put(Session(id="ses_1", owner="demo"))
    container.repos.files.put(
        UploadedFile(
            id="fil_t",
            session_id="ses_1",
            filename="canva.pptx",
            media_type="x",
            size=ref.size,
            sha256=ref.sha256,
            role=FileRole.template,
            blob_path=ref.path,
        )
    )
    fake_llm.add("interpreter", _interp())
    fake_llm.add(
        "template_analyzer",
        TemplateDesignAnalysis(
            summary="Preserve the observed sample-slide artwork and use its content layouts."
        ),
    )
    fake_llm.add("deck_planner", sample_deck())
    msg = container.repos.messages.put(Message(id="m1", session_id="ses_1", role=Role.user, content="deck"))
    reply = await GenerationService(container).handle_message(container.repos.sessions.require("ses_1"), msg)
    cached = container.repos.templates.get(ref.sha256)
    assert cached.analyzer_version == ANALYZER_VERSION and cached.pptx.design_mode == "slides"
    assert "Designed on your template “canva.pptx”" in reply.message.content
    prompt = fake_llm.calls_for("deck_planner")[0].messages[0].content
    assert "content designs" in prompt and "at most 4 bullets" in prompt
    assert len(fake_llm.calls_for("template_analyzer")) == 1


def test_template_summary_for_designed_slides(tmp_path: Path):
    m = analyze_pptx(canva_like(tmp_path / "c.pptx"))
    text = template_summary(m, "c.pptx")
    assert "3 content designs" in text and "Montserrat" in text
