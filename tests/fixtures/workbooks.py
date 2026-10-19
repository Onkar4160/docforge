"""WorkbookPlan fixture: assumptions with named ranges, a formula-driven model, a report with a chart."""

from __future__ import annotations

from docforge.models.ir import (
    CellSpec,
    ColumnSpec,
    ExpectedValue,
    NamedRange,
    SheetChartSpec,
    SheetPlan,
    TableSpec,
    WorkbookPlan,
)


def saas_model(*, broken: bool = False) -> WorkbookPlan:
    growth_formula = "=B{row}*(1+growth)" if not broken else "=B{row}*(1+no_such_name)"
    return WorkbookPlan(
        title="SaaS revenue model",
        sheets=[
            SheetPlan(
                id="a",
                name="Assumptions",
                role="assumptions",
                description="Inputs you can change",
                cells=[
                    CellSpec(ref="A1", value="Assumption", style_role="header"),
                    CellSpec(ref="B1", value="Value", style_role="header"),
                    CellSpec(ref="A2", value="Starting MRR", style_role="label"),
                    CellSpec(ref="B2", value=10000, number_format='"$"#,##0', style_role="input"),
                    CellSpec(ref="A3", value="Monthly growth", style_role="label"),
                    CellSpec(ref="B3", value=0.05, number_format="0.0%", style_role="input"),
                ],
                freeze="A2",
            ),
            SheetPlan(
                id="b",
                name="Revenue model",
                role="calculations",
                description="Monthly projection",
                tables=[
                    TableSpec(
                        name="Projection",
                        anchor="A1",
                        columns=[
                            ColumnSpec(name="Month", dtype="int"),
                            ColumnSpec(name="MRR", dtype="currency", unit="$"),
                            ColumnSpec(
                                name="Next MRR", dtype="currency", unit="$", formula_template=growth_formula
                            ),
                        ],
                        rows=[[1, 10000, None], [2, 10500, None], [3, 11025, None]],
                    ),
                ],
                cells=[
                    CellSpec(ref="E1", value="Total MRR", style_role="label"),
                    CellSpec(ref="E2", formula="=SUM(B2:B4)", number_format='"$"#,##0', style_role="output"),
                ],
                charts=[
                    SheetChartSpec(
                        chart_type="column",
                        title="MRR by month",
                        data_ref="B1:B4",
                        categories_ref="A2:A4",
                        anchor="G2",
                    )
                ],
            ),
            SheetPlan(
                id="c",
                name="Report",
                role="report",
                description="Headline KPIs",
                cells=[
                    CellSpec(ref="A1", value="Total MRR (3 months)", style_role="label"),
                    CellSpec(
                        ref="B1", formula="='Revenue model'!E2", number_format='"$"#,##0', style_role="output"
                    ),
                    CellSpec(ref="A2", value="Growth assumption", style_role="label"),
                    CellSpec(ref="B2", formula="=growth", number_format="0.0%", style_role="output"),
                ],
            ),
        ],
        named_ranges=[
            NamedRange(name="growth", sheet_id="a", ref="B3"),
            NamedRange(name="start_mrr", sheet_id="a", ref="B2"),
        ],
        checks=[ExpectedValue(sheet_id="c", cell="B1", expected=31525, rationale="10000+10500+11025")],
    )
