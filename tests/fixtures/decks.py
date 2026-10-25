"""Hand-written DeckPlan covering every archetype (TESTING §4, fixtures/ir)."""

from __future__ import annotations

from docforge.models.ir import (
    BulletItem,
    BulletsBlock,
    ChartBlock,
    ChartSeries,
    ComparisonBlock,
    ComparisonColumn,
    DeckPlan,
    KPIBlock,
    KPIMetric,
    ProcessBlock,
    ProcessStep,
    QuoteBlock,
    SlidePlan,
    TableBlock,
    TimelineBlock,
    TimelineEvent,
)


def _b(*items: str) -> BulletsBlock:
    return BulletsBlock(items=[BulletItem(text=t) for t in items])


def sample_deck() -> DeckPlan:
    return DeckPlan(
        title="European EV Charging Market 2026",
        subtitle="Where the next decade of growth will come from",
        audience="Board of Directors · Q4 review",
        narrative=["Market is scaling", "Fast charging leads", "Grid is the constraint", "Act on three bets"],
        design_hint="ocean_depth",
        slides=[
            SlidePlan(
                id="s01",
                purpose="open",
                archetype="title",
                headline="European EV Charging Market 2026",
                key_message="Where the next decade of growth will come from",
            ),
            SlidePlan(
                id="s02",
                purpose="agenda",
                archetype="agenda",
                headline="What we will cover",
                blocks=[
                    _b(
                        "Market size and growth",
                        "Where fast charging wins",
                        "Grid constraints",
                        "Recommendations",
                    )
                ],
            ),
            SlidePlan(
                id="s03",
                purpose="section",
                archetype="section",
                headline="Market size and growth",
                key_message="The installed base doubles by 2028",
            ),
            SlidePlan(
                id="s04",
                purpose="growth",
                archetype="chart",
                headline="Public charge points will double by 2028",
                key_message="Growth is led by Germany, France and the Netherlands",
                blocks=[
                    ChartBlock(
                        chart_type="column",
                        title="Public charge points (thousands)",
                        categories=["2024", "2025", "2026", "2027", "2028"],
                        series=[ChartSeries(name="Charge points", values=[630, 780, 950, 1120, 1300])],
                    ),
                    _b("Fast chargers grow fastest", "Highway corridors funded by AFIR"),
                ],
            ),
            SlidePlan(
                id="s05",
                purpose="kpis",
                archetype="kpi",
                headline="Three numbers frame the opportunity",
                blocks=[
                    KPIBlock(
                        metrics=[
                            KPIMetric(label="Market size 2026", value="€9.4bn", delta="+21% YoY"),
                            KPIMetric(label="Fast-charge share", value="38%", delta="+6 pts"),
                            KPIMetric(
                                label="Avg. utilisation",
                                value="14%",
                                delta="-2 pts",
                                note="Below breakeven of 18%",
                            ),
                        ]
                    )
                ],
            ),
            SlidePlan(
                id="s06",
                purpose="compare",
                archetype="comparison",
                headline="Fast charging beats AC on returns",
                key_message="Higher capex, but utilisation drives payback",
                blocks=[
                    ComparisonBlock(
                        columns=[
                            ComparisonColumn(
                                heading="DC fast charging",
                                points=["Payback 4–6 years", "Premium pricing", "Highway and urban hubs"],
                            ),
                            ComparisonColumn(
                                heading="AC destination",
                                points=["Payback 7–9 years", "Low pricing power", "Retail and workplace"],
                            ),
                        ]
                    )
                ],
            ),
            SlidePlan(
                id="s07",
                purpose="history",
                archetype="timeline",
                headline="Regulation sets the pace",
                blocks=[
                    TimelineBlock(
                        events=[
                            TimelineEvent(
                                date="2023", label="AFIR adopted", description="Binding targets per country"
                            ),
                            TimelineEvent(
                                date="2025", label="150 kW every 60 km", description="Core TEN-T network"
                            ),
                            TimelineEvent(
                                date="2027", label="Ad-hoc payment", description="Card payment mandatory"
                            ),
                            TimelineEvent(
                                date="2030", label="Full coverage", description="Comprehensive network"
                            ),
                        ]
                    )
                ],
            ),
            SlidePlan(
                id="s08",
                purpose="how",
                archetype="process",
                headline="How we would enter a new market",
                blocks=[
                    ProcessBlock(
                        steps=[
                            ProcessStep(
                                title="Site screening", description="Traffic, grid capacity, permits"
                            ),
                            ProcessStep(title="Partnering", description="Retail landlords and utilities"),
                            ProcessStep(title="Build", description="Modular 300 kW hubs"),
                            ProcessStep(title="Operate", description="Dynamic pricing and uptime SLAs"),
                        ]
                    )
                ],
            ),
            SlidePlan(
                id="s09",
                purpose="detail",
                archetype="table",
                headline="Germany leads on every metric",
                blocks=[
                    TableBlock(
                        columns=["Country", "Charge points", "Fast share", "Growth"],
                        rows=[
                            ["Germany", "160k", "22%", "+24%"],
                            ["France", "150k", "18%", "+28%"],
                            ["Netherlands", "180k", "6%", "+15%"],
                            ["Italy", "60k", "14%", "+35%"],
                        ],
                        caption="Source: illustrative figures for testing",
                    )
                ],
            ),
            SlidePlan(
                id="s10",
                purpose="risk",
                archetype="bullets",
                headline="Grid connection is the binding constraint",
                key_message="Secure grid capacity before sites",
                blocks=[
                    _b(
                        "Connection queues of 18–36 months in key regions",
                        "Transformer shortages raise costs by 15–25%",
                        "Battery-buffered sites cut grid demand by up to 40%",
                    )
                ],
            ),
            SlidePlan(
                id="s11",
                purpose="voice",
                archetype="quote",
                headline="Customer research, 2026",
                blocks=[
                    QuoteBlock(
                        text="I choose the route by where I can charge fast and reliably.",
                        attribution="Fleet manager, Munich",
                    )
                ],
            ),
            SlidePlan(
                id="s12",
                purpose="summary",
                archetype="summary",
                headline="Three bets for 2027",
                blocks=[
                    _b(
                        "Lead with DC hubs on corridors",
                        "Lock in grid capacity early",
                        "Partner with retail landlords",
                    )
                ],
            ),
            SlidePlan(
                id="s13",
                purpose="close",
                archetype="closing",
                headline="Decision requested today",
                key_message="Approve €120m for phase one",
                blocks=[_b("Board approval of phase one budget", "Mandate to negotiate grid reservations")],
            ),
        ],
    )
