"""Unit tests for targeted editing, target resolution, and Scope Guard (FR-EDIT-1..4)."""

from __future__ import annotations

import pytest

from docforge.agents.doc_writer import assemble
from docforge.agents.editor import (
    SlideEditorAgent,
    SlideEditorInput,
)
from docforge.llm import FakeLLMClient
from docforge.models.intent import (
    StyleChange,
)
from docforge.models.ir import (
    DocumentPlan,
    SlidePlan,
)
from docforge.orchestrator.patch import (
    ScopeViolationError,
    apply_remove_unit,
    apply_restyle,
    apply_section_edit,
    apply_sheet_edit,
    apply_slide_edit,
)
from docforge.orchestrator.targets import resolve_targets
from tests.fixtures.decks import sample_deck
from tests.fixtures.documents import outline, written
from tests.fixtures.workbooks import saas_model

pytestmark = pytest.mark.anyio


def sample_document() -> DocumentPlan:
    return assemble(outline(), written())


def test_target_resolver_by_index_and_ordinal():
    deck = sample_deck()  # 13 slides
    res1 = resolve_targets(deck, None, "change slide 3 to focus on battery tech")
    assert not res1.clarification_needed
    assert len(res1.targets) == 1
    assert res1.targets[0].unit_id == deck.slides[2].id

    res2 = resolve_targets(deck, None, "update the fourth slide")
    assert not res2.clarification_needed
    assert res2.targets[0].unit_id == deck.slides[3].id

    res3 = resolve_targets(deck, None, "change the last slide")
    assert res3.targets[0].unit_id == deck.slides[-1].id

    res4 = resolve_targets(deck, None, "update slide #1")
    assert res4.targets[0].unit_id == deck.slides[0].id


def test_target_resolver_by_headline_or_keyword():
    deck = sample_deck()
    # Find a slide with known headline word
    target_slide = deck.slides[4]
    res = resolve_targets(deck, None, f"on the '{target_slide.headline}', make bullets shorter")
    assert res.targets and res.targets[0].unit_id == target_slide.id


def test_target_resolver_document_sections():
    doc = sample_document()
    all_secs = doc.all_sections()
    res = resolve_targets(doc, None, "change section 2 to mention Europe")
    assert res.targets and res.targets[0].unit_id == all_secs[1].id


def test_target_resolver_workbook_sheets():
    wb = saas_model()
    res = resolve_targets(wb, None, "update the Assumptions sheet")
    assert res.targets and res.targets[0].unit_id == "a"


def test_target_resolver_ambiguous_prompts_clarification():
    deck = sample_deck()
    res = resolve_targets(deck, None, "make it better and change the points")
    assert res.clarification_needed
    assert "Which slide" in res.clarification_question


def test_apply_slide_edit_preserves_untouched_slides():
    deck = sample_deck()
    original_slides = [s.model_copy(deep=True) for s in deck.slides]

    # Modify slide 2
    target_id = deck.slides[1].id
    edited = deck.slides[1].model_copy(
        update={"headline": "Updated Battery Technology", "key_message": "New 2026 specs"}
    )
    new_deck, patch = apply_slide_edit(deck, edited, instruction="update headline", base_version=1)

    assert patch.affected_unit_ids == [target_id]
    assert new_deck.slides[1].headline == "Updated Battery Technology"

    # Verify all other 12 slides are 100% identical
    for i, s in enumerate(new_deck.slides):
        if i != 1:
            assert s == original_slides[i]


def test_apply_slide_edit_rejects_missing_target():
    deck = sample_deck()
    fake_slide = SlidePlan(id="non_existent", purpose="p", archetype="bullets", headline="h")
    with pytest.raises(ScopeViolationError):
        apply_slide_edit(deck, fake_slide)


def test_apply_section_edit_preserves_other_sections():
    doc = sample_document()
    target_sec = doc.sections[0]
    edited = target_sec.model_copy(update={"heading": "New Executive Overview"})
    new_doc, patch = apply_section_edit(doc, edited, instruction="rename heading", base_version=1)

    assert patch.affected_unit_ids == [target_sec.id]
    assert new_doc.sections[0].heading == "New Executive Overview"
    assert new_doc.sections[1:] == doc.sections[1:]


def test_apply_sheet_edit_preserves_other_sheets():
    wb = saas_model()
    target_sheet = wb.sheets[0]
    edited = target_sheet.model_copy(update={"description": "Updated assumptions"})
    new_wb, patch = apply_sheet_edit(wb, edited, instruction="update desc", base_version=1)

    assert patch.affected_unit_ids == [target_sheet.id]
    assert new_wb.sheets[0].description == "Updated assumptions"
    assert new_wb.sheets[1:] == wb.sheets[1:]


def test_apply_remove_unit():
    deck = sample_deck()
    remove_id = deck.slides[2].id
    new_deck, patch = apply_remove_unit(deck, remove_id, instruction="delete slide 3", base_version=1)

    assert len(new_deck.slides) == len(deck.slides) - 1
    assert remove_id not in [s.id for s in new_deck.slides]


def test_apply_restyle():
    deck = sample_deck()
    changes = [StyleChange(property="heading_font", value="Georgia")]
    new_deck, patch = apply_restyle(deck, changes, instruction="change font to Georgia", base_version=1)

    assert new_deck.style.heading_font == "Georgia"
    assert new_deck.slides == deck.slides  # content completely untouched


async def test_slide_editor_agent():
    deck = sample_deck()
    slide = deck.slides[1]
    updated_slide = slide.model_copy(update={"headline": "Edited by Agent"})
    fake = FakeLLMClient({"slide_editor": updated_slide})

    agent = SlideEditorAgent(fake)
    result = await agent.run(
        SlideEditorInput(
            slide=slide,
            instruction="change headline",
            outline=[(s.id, s.headline) for s in deck.slides],
        )
    )
    assert result.headline == "Edited by Agent"
    assert result.id == slide.id
