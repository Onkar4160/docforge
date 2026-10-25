"""Outline + written sections for document tests (two sections, one with subsections)."""

from __future__ import annotations

from docforge.agents.doc_writer import (
    DocumentOutline,
    OutlineSection,
    OutlineSubsection,
    WrittenSection,
    WrittenSubsection,
)
from docforge.models.ir import (
    BulletItem,
    BulletsBlock,
    CalloutBlock,
    ChartBlock,
    ChartSeries,
    ComparisonBlock,
    ComparisonColumn,
    KPIBlock,
    KPIMetric,
    ParagraphBlock,
    ProcessBlock,
    ProcessStep,
    QuoteBlock,
    TableBlock,
    TimelineBlock,
    TimelineEvent,
)

PROSE = (
    "Microplastic particles are now detected in most municipal water supplies that have been tested, "
    "although concentrations vary by orders of magnitude between studies because sampling and detection "
    "methods are not yet standardised. "
)


def outline() -> DocumentOutline:
    return DocumentOutline(
        title="Microplastics in Drinking Water",
        subtitle="Evidence, risks and policy options",
        audience="Regional water authority board",
        executive_summary=[
            "Microplastics are widespread in drinking water.",
            "Health risks remain uncertain.",
            "Standardised monitoring should come first.",
        ],
        sections=[
            OutlineSection(
                heading="What the evidence shows",
                purpose="State of knowledge",
                target_words=600,
                key_points=["prevalence", "methods"],
            ),
            OutlineSection(
                heading="Options for the authority",
                purpose="Recommendations",
                target_words=900,
                subsections=[
                    OutlineSubsection(heading="Monitoring", target_words=400),
                    OutlineSubsection(heading="Treatment", target_words=400),
                ],
            ),
        ],
    )


def written(cite: list[str] | None = None) -> list[WrittenSection]:
    cite = cite or []
    first = WrittenSection(
        blocks=[
            ParagraphBlock(text=PROSE * 2, claim_ids=cite[:1]),
            ChartBlock(
                chart_type="column",
                title="Particles per litre by study",
                categories=["A", "B", "C"],
                series=[ChartSeries(name="Particles", values=[4.0, 12.0, 0.8])],
                unit="particles/L",
                claim_ids=cite[:1],
            ),
            TableBlock(
                columns=["Method", "Size limit"],
                rows=[["FTIR", "20 µm"], ["Raman", "1 µm"]],
                caption="Detection methods",
                claim_ids=cite[1:2],
            ),
            QuoteBlock(
                text="Data are insufficient to draw firm conclusions.", attribution="WHO", claim_ids=cite[1:2]
            ),
            KPIBlock(metrics=[KPIMetric(label="Samples positive", value="81%", claim_ids=cite[:1])]),
        ]
    )
    second = WrittenSection(
        blocks=[ParagraphBlock(text=PROSE)],
        subsections=[
            WrittenSubsection(
                heading="Monitoring",
                blocks=[
                    BulletsBlock(
                        items=[
                            BulletItem(text="Adopt a standard method"),
                            BulletItem(text="Sample quarterly"),
                        ]
                    ),
                    TimelineBlock(
                        events=[
                            TimelineEvent(date="2027", label="Pilot"),
                            TimelineEvent(date="2028", label="Rollout"),
                        ]
                    ),
                ],
            ),
            WrittenSubsection(
                heading="Treatment",
                blocks=[
                    ProcessBlock(
                        steps=[
                            ProcessStep(title="Assess", description="baseline"),
                            ProcessStep(title="Upgrade"),
                        ]
                    ),
                    ComparisonBlock(
                        columns=[
                            ComparisonColumn(heading="Membranes", points=["High removal"]),
                            ComparisonColumn(heading="Sand filters", points=["Low cost", "Moderate"]),
                        ]
                    ),
                    CalloutBlock(text="Monitoring before major capital spending."),
                ],
            ),
        ],
    )
    return [first, second]
