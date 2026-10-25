from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from docforge.models.artifact import ArtifactVersion
from docforge.models.evidence import Claim, ClaimStatus, EvidenceItem, ResearchDossier, Source, SourceKind
from docforge.models.intent import (
    ChangeOperation,
    ChangeRequest,
    ChangeScope,
    Interpretation,
    OutputFormat,
    OutputSpec,
    RequestKind,
    ScopeLevel,
    TargetKind,
    TargetRef,
)
from docforge.models.ir import (
    ArtifactIR,
    BulletItem,
    BulletsBlock,
    ChartBlock,
    ChartSeries,
    DeckPlan,
    DocumentPlan,
    SectionPlan,
    SheetPlan,
    SheetRole,
    SlideArchetype,
    SlidePlan,
    TableBlock,
    WorkbookPlan,
    block_claim_ids,
)
from docforge.models.quality import (
    CheckResult,
    CheckStatus,
    Dimension,
    Finding,
    FindingStatus,
    QualityReport,
    Severity,
    Verdict,
)
from docforge.models.template import Box


def _slide(sid: str, **kw) -> SlidePlan:
    return SlidePlan(id=sid, purpose="p", archetype=SlideArchetype.bullets, headline=f"Headline {sid}", **kw)


# ---------------------------------------------------------------- intent (FR-CONV-2/6)


def test_modify_interpretation_requires_change():
    with pytest.raises(ValidationError, match="change request"):
        Interpretation(kind=RequestKind.modify_artifact, confidence=0.9, objective="x")


def test_unit_scope_requires_targets():
    with pytest.raises(ValidationError, match="at least one target"):
        ChangeRequest(
            operation=ChangeOperation.rewrite, scope=ChangeScope(level=ScopeLevel.unit), instruction="rewrite"
        )


def test_interpretation_valid_modify():
    interp = Interpretation(
        kind=RequestKind.modify_artifact,
        confidence=0.85,
        objective="Refocus slide 4 on costs",
        change=ChangeRequest(
            operation=ChangeOperation.rewrite,
            scope=ChangeScope(
                level=ScopeLevel.unit, targets=[TargetRef(kind=TargetKind.slide, locator="slide 4")]
            ),
            instruction="focus on costs",
        ),
    )
    assert Interpretation.model_validate_json(interp.model_dump_json()) == interp


def test_output_spec_defaults():
    spec = OutputSpec(format=OutputFormat.pptx)
    assert spec.length.explicit is False
    assert spec.citation_style == "numeric"


def test_interpretation_schema_forbids_extra_properties():
    # Structured outputs require additionalProperties: false on every object.
    schema = Interpretation.model_json_schema()
    assert schema["additionalProperties"] is False
    assert all(
        d.get("additionalProperties") is False for d in schema["$defs"].values() if d.get("type") == "object"
    )


# ---------------------------------------------------------------- evidence (FR-RES-5/6/8)


def _dossier(**kw) -> ResearchDossier:
    return ResearchDossier(
        id="dos_1",
        task_id="tsk_1",
        sources=[Source(id="src_1", kind=SourceKind.web, url="https://example.org", title="Example")],
        evidence=[EvidenceItem(id="evd_1", source_id="src_1", kind="figure", statement="X is 5", value=5)],
        **kw,
    )


def test_supported_claim_needs_evidence():
    with pytest.raises(ValidationError, match="cites no evidence"):
        Claim(id="clm_1", text="X is 5", status=ClaimStatus.supported)


def test_assumption_claim_without_evidence_ok():
    assert Claim(id="clm_1", text="Growth continues", status=ClaimStatus.assumption).evidence_ids == []


def test_dossier_rejects_dangling_evidence_reference():
    with pytest.raises(ValidationError, match="unknown evidence"):
        _dossier(claims=[Claim(id="clm_1", text="t", evidence_ids=["evd_missing"], status="supported")])


def test_dossier_rejects_evidence_with_unknown_source():
    with pytest.raises(ValidationError, match="unknown sources"):
        ResearchDossier(
            id="d", task_id="t", evidence=[EvidenceItem(id="e", source_id="nope", kind="fact", statement="s")]
        )


def test_dossier_claim_lookup():
    d = _dossier(claims=[Claim(id="clm_1", text="X is 5", evidence_ids=["evd_1"], status="supported")])
    assert d.claim("clm_1").text == "X is 5"
    assert d.claim("missing") is None


# ---------------------------------------------------------------- IR (FR-PLAN-*)


def test_table_must_be_rectangular():
    with pytest.raises(ValidationError, match="do not match"):
        TableBlock(columns=["a", "b"], rows=[["1", "2"], ["3"]])


def test_chart_series_length_must_match_categories():
    with pytest.raises(ValidationError, match="length differs"):
        ChartBlock(chart_type="bar", categories=["a", "b"], series=[ChartSeries(name="s", values=[1.0])])


def test_deck_unit_ids_unique():
    with pytest.raises(ValidationError, match="duplicate unit ids"):
        DeckPlan(title="t", slides=[_slide("s01"), _slide("s01")])


def test_document_nested_unit_ids_unique():
    with pytest.raises(ValidationError, match="duplicate unit ids"):
        DocumentPlan(
            title="t",
            sections=[
                SectionPlan(id="a", heading="A", subsections=[SectionPlan(id="a", heading="A1", level=2)])
            ],
        )


def test_document_units_include_subsections():
    doc = DocumentPlan(
        title="t",
        sections=[SectionPlan(id="a", heading="A", subsections=[SectionPlan(id="b", heading="B", level=2)])],
    )
    assert doc.unit_ids() == ["a", "b"]


def test_workbook_sheet_names_unique_case_insensitive():
    with pytest.raises(ValidationError, match="unique"):
        WorkbookPlan(
            title="t",
            sheets=[
                SheetPlan(id="a", name="Data", role=SheetRole.data),
                SheetPlan(id="b", name="data", role="report"),
            ],
        )


def test_sheet_name_max_length():
    with pytest.raises(ValidationError):
        SheetPlan(id="a", name="x" * 32, role=SheetRole.data)


def test_ir_discriminated_union_roundtrip():
    deck = DeckPlan(
        title="EV charging",
        slides=[_slide("s01", blocks=[BulletsBlock(items=[BulletItem(text="a", claim_ids=["clm_1"])])])],
    )
    adapter = TypeAdapter(ArtifactIR)
    restored = adapter.validate_json(deck.model_dump_json())
    assert isinstance(restored, DeckPlan)
    assert isinstance(restored.slides[0].blocks[0], BulletsBlock)


def test_block_claim_ids_include_nested_items():
    block = BulletsBlock(
        claim_ids=["c0"], items=[BulletItem(text="a", claim_ids=["c1"]), BulletItem(text="b")]
    )
    assert block_claim_ids(block) == {"c0", "c1"}


def test_artifact_version_roundtrip_keeps_ir_type():
    v = ArtifactVersion(
        artifact_id="art_1",
        version=1,
        ir=WorkbookPlan(title="w", sheets=[SheetPlan(id="a", name="A", role="data")]),
    )
    restored = ArtifactVersion.model_validate_json(v.model_dump_json())
    assert isinstance(restored.ir, WorkbookPlan)
    assert restored.key == "art_1:v1"


# ---------------------------------------------------------------- quality (FR-VAL-3)


def _finding(sev: Severity, status: FindingStatus = FindingStatus.detected) -> Finding:
    return Finding(id="f", check_id="c", dimension=Dimension.layout, severity=sev, message="m", status=status)


def test_quality_verdict_fail_on_unresolved_critical():
    r = QualityReport(id="q", artifact_id="a", version=1, findings=[_finding(Severity.critical)]).finalize()
    assert r.verdict == Verdict.failed
    assert r.summary.unresolved == 1


def test_quality_verdict_pass_when_critical_corrected():
    r = QualityReport(
        id="q", artifact_id="a", version=1, findings=[_finding(Severity.critical, FindingStatus.corrected)]
    ).finalize()
    assert r.verdict == Verdict.passed
    assert r.summary.corrected == 1


def test_quality_verdict_warns_on_skipped_checks():
    r = QualityReport(
        id="q",
        artifact_id="a",
        version=1,
        checks=[
            CheckResult(
                check_id="common.convert", tier=4, status=CheckStatus.skipped, reason="no LibreOffice"
            )
        ],
    ).finalize()
    assert r.verdict == Verdict.pass_with_warnings
    assert r.summary.skipped == 1


# ---------------------------------------------------------------- geometry


def test_box_intersection_and_inside():
    a, b = Box(x=0, y=0, w=10, h=10), Box(x=5, y=5, w=10, h=10)
    assert a.intersection_area(b) == 25
    assert Box(x=0, y=0, w=1, h=1).intersection_area(Box(x=2, y=2, w=1, h=1)) == 0
    assert Box(x=1, y=1, w=2, h=2).inside(a)
    assert not b.inside(a)


# ---------------------------------------------------------------- design & colors


def test_palette_and_stylespec_color_normalization():
    from docforge.models.design import Palette
    from docforge.models.ir import StyleSpec
    from docforge.render.docx.renderer import _rgb
    from docforge.render.pptx.canvas import rgb

    p = Palette(
        primary="#000000",
        secondary="#1f4e79",
        background="#fff",
        accents=["#ff0000", "#00ff00"],
    )
    assert p.primary == "000000"
    assert p.secondary == "1F4E79"
    assert p.background == "FFFFFF"
    assert p.accents == ["FF0000", "00FF00"]

    spec = StyleSpec(palette_overrides={"text": "#000000", "primary": "#1A365D", "surface": "#abc"})
    assert spec.palette_overrides == {"text": "000000", "primary": "1A365D", "surface": "AABBCC"}

    c1 = rgb("#000000")
    c2 = rgb("000000")
    assert (c1[0], c1[1], c1[2]) == (0, 0, 0)
    assert (c2[0], c2[1], c2[2]) == (0, 0, 0)

    dc = _rgb("#1A365D")
    assert (dc[0], dc[1], dc[2]) == (0x1A, 0x36, 0x5D)
