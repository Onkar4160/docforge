"""Intermediate representations: the source of truth for every artifact version (ADR-003, DATA_MODELS §6)."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from docforge.models.base import DFModel, VersionedDocument

# ---------------------------------------------------------------- content blocks


class _Block(DFModel):
    claim_ids: list[str] = Field(default_factory=list)


class ParagraphBlock(_Block):
    type: Literal["paragraph"] = "paragraph"
    text: str


class BulletItem(DFModel):
    text: str
    level: int = Field(0, ge=0, le=2)
    claim_ids: list[str] = Field(default_factory=list)


class BulletsBlock(_Block):
    type: Literal["bullets"] = "bullets"
    items: list[BulletItem]


class TableBlock(_Block):
    type: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]
    caption: str | None = None

    @model_validator(mode="after")
    def _rectangular(self) -> TableBlock:
        bad = [i for i, r in enumerate(self.rows) if len(r) != len(self.columns)]
        if bad:
            raise ValueError(f"table rows {bad} do not match {len(self.columns)} columns")
        return self


class ChartType(StrEnum):
    bar = "bar"
    column = "column"
    line = "line"
    pie = "pie"
    doughnut = "doughnut"
    area = "area"
    scatter = "scatter"
    stacked_bar = "stacked_bar"
    stacked_column = "stacked_column"


class ChartSeries(DFModel):
    name: str
    values: list[float]


class ChartBlock(_Block):
    type: Literal["chart"] = "chart"
    chart_type: ChartType
    title: str | None = None
    categories: list[str]
    series: list[ChartSeries]
    unit: str | None = None

    @model_validator(mode="after")
    def _series_match_categories(self) -> ChartBlock:
        bad = [s.name for s in self.series if len(s.values) != len(self.categories)]
        if bad:
            raise ValueError(f"chart series {bad} length differs from {len(self.categories)} categories")
        return self


class TimelineEvent(DFModel):
    label: str
    date: str | None = None
    description: str | None = None


class TimelineBlock(_Block):
    type: Literal["timeline"] = "timeline"
    events: list[TimelineEvent]


class ProcessStep(DFModel):
    title: str
    description: str | None = None


class ProcessBlock(_Block):
    type: Literal["process"] = "process"
    steps: list[ProcessStep]


class ComparisonColumn(DFModel):
    heading: str
    points: list[str]


class ComparisonBlock(_Block):
    type: Literal["comparison"] = "comparison"
    columns: list[ComparisonColumn]


class KPIMetric(DFModel):
    label: str
    value: str
    delta: str | None = None
    note: str | None = None
    claim_ids: list[str] = Field(default_factory=list)


class KPIBlock(_Block):
    type: Literal["kpi"] = "kpi"
    metrics: list[KPIMetric]


class QuoteBlock(_Block):
    type: Literal["quote"] = "quote"
    text: str
    attribution: str | None = None


class ImageBlock(_Block):
    type: Literal["image"] = "image"
    description: str = Field(description="Concrete, photographable subject used as the image search query")
    alt_text: str
    file_id: str | None = None
    # Filled by the image resolver, not by planners:
    asset_path: str | None = None
    credit: str | None = None
    source_url: str | None = None


class CalloutBlock(_Block):
    type: Literal["callout"] = "callout"
    text: str
    tone: Literal["info", "positive", "warning"] = "info"


Block = Annotated[
    ParagraphBlock
    | BulletsBlock
    | TableBlock
    | ChartBlock
    | TimelineBlock
    | ProcessBlock
    | ComparisonBlock
    | KPIBlock
    | QuoteBlock
    | ImageBlock
    | CalloutBlock,
    Field(discriminator="type"),
]


def block_claim_ids(block: DFModel) -> set[str]:
    """All claim IDs cited by a block, including nested items."""
    ids = set(getattr(block, "claim_ids", []))
    for nested in getattr(block, "items", []) or getattr(block, "metrics", []):
        ids.update(getattr(nested, "claim_ids", []))
    return ids


# ---------------------------------------------------------------- style


class HeadingSizes(DFModel):
    title: float | None = None
    h1: float | None = None
    h2: float | None = None
    h3: float | None = None


class StyleSpec(DFModel):
    """Format-agnostic overrides on top of template/design tokens; restyle edits touch only this."""

    heading_font: str | None = None
    body_font: str | None = None
    heading_sizes_pt: HeadingSizes = Field(default_factory=HeadingSizes)
    body_size_pt: float | None = None
    palette_overrides: dict[str, str] = Field(default_factory=dict)
    line_spacing: float | None = None
    paragraph_spacing_pt: float | None = None
    margins_in: float | None = None
    heading_alignment: Literal["left", "center", "right", "justify"] | None = None
    body_alignment: Literal["left", "center", "right", "justify"] | None = None
    page_orientation: Literal["portrait", "landscape"] | None = None

    @field_validator("palette_overrides", mode="before")
    @classmethod
    def _clean_palette_overrides(cls, v: dict[str, str]) -> dict[str, str]:
        if isinstance(v, dict):
            out = {}
            for k, val in v.items():
                if isinstance(val, str):
                    val = val.strip().removeprefix("#")
                    if len(val) == 3:
                        val = "".join(ch * 2 for ch in val)
                    out[k] = val.upper()
                else:
                    out[k] = val
            return out
        return v


# ---------------------------------------------------------------- deck


class SlideArchetype(StrEnum):
    title = "title"
    agenda = "agenda"
    section = "section"
    bullets = "bullets"
    two_column = "two_column"
    comparison = "comparison"
    timeline = "timeline"
    process = "process"
    chart = "chart"
    table = "table"
    kpi = "kpi"
    quote = "quote"
    image_text = "image_text"
    summary = "summary"
    closing = "closing"
    references = "references"


class SlidePlan(DFModel):
    id: str
    purpose: str
    archetype: SlideArchetype
    headline: str
    key_message: str = ""
    blocks: list[Block] = Field(default_factory=list)
    notes: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    layout_hint: str | None = None
    style: StyleSpec = Field(default_factory=StyleSpec)


class SlideDraft(DFModel):
    """LLM-authored slide content; the application assigns its stable slide ID."""

    purpose: str
    archetype: SlideArchetype
    headline: str
    key_message: str = ""
    blocks: list[Block] = Field(default_factory=list)
    notes: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    layout_hint: str | None = None


class SlideInsertionPlan(DFModel):
    slides: list[SlideDraft] = Field(min_length=1, max_length=10)


class SectionDraft(DFModel):
    heading: str
    level: int = Field(1, ge=1, le=3)
    purpose: str = ""
    blocks: list[Block] = Field(default_factory=list)
    subsections: list[SectionDraft] = Field(default_factory=list)


class SectionInsertionPlan(DFModel):
    sections: list[SectionDraft] = Field(min_length=1, max_length=10)


class _UnitDocument(VersionedDocument):
    def unit_ids(self) -> list[str]:
        return list(self.units().keys())

    def units(self) -> dict[str, DFModel]:  # pragma: no cover - overridden
        raise NotImplementedError

    @model_validator(mode="after")
    def _unique_unit_ids(self) -> _UnitDocument:
        ids = self._collect_ids()
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate unit ids: {dupes}")
        return self

    def _collect_ids(self) -> list[str]:  # pragma: no cover - overridden
        return []


class DeckPlan(_UnitDocument):
    format: Literal["pptx"] = "pptx"
    title: str
    subtitle: str | None = None
    audience: str = ""
    narrative: list[str] = Field(default_factory=list)
    design_hint: str | None = Field(None, description="Palette name for generated designs (no template).")
    slides: list[SlidePlan]
    style: StyleSpec = Field(default_factory=StyleSpec)

    def _collect_ids(self) -> list[str]:
        return [s.id for s in self.slides]

    def units(self) -> dict[str, DFModel]:
        return {s.id: s for s in self.slides}


# ---------------------------------------------------------------- document


class SectionPlan(DFModel):
    id: str
    heading: str
    level: int = Field(1, ge=1, le=3)
    purpose: str = ""
    blocks: list[Block] = Field(default_factory=list)
    subsections: list[SectionPlan] = Field(default_factory=list)
    style: StyleSpec = Field(default_factory=StyleSpec)

    def walk(self) -> list[SectionPlan]:
        out = [self]
        for sub in self.subsections:
            out.extend(sub.walk())
        return out


class FrontMatter(DFModel):
    executive_summary: list[Block] = Field(default_factory=list)
    abstract: str | None = None
    include_toc: bool = True


class DocumentPlan(_UnitDocument):
    format: Literal["docx"] = "docx"
    title: str
    subtitle: str | None = None
    author: str | None = None
    doc_type: Literal["report", "memo", "proposal", "paper", "brief", "manual"] = "report"
    front_matter: FrontMatter = Field(default_factory=FrontMatter)
    sections: list[SectionPlan]
    style: StyleSpec = Field(default_factory=StyleSpec)

    def all_sections(self) -> list[SectionPlan]:
        return [s for top in self.sections for s in top.walk()]

    def _collect_ids(self) -> list[str]:
        return [s.id for s in self.all_sections()]

    def units(self) -> dict[str, DFModel]:
        return {s.id: s for s in self.all_sections()}


# ---------------------------------------------------------------- workbook


class SheetRole(StrEnum):
    readme = "readme"
    assumptions = "assumptions"
    data = "data"
    calculations = "calculations"
    report = "report"
    sources = "sources"


class ColumnType(StrEnum):
    text = "text"
    int = "int"
    float = "float"
    currency = "currency"
    percent = "percent"
    date = "date"
    bool = "bool"


class ColumnSpec(DFModel):
    name: str
    dtype: ColumnType = ColumnType.text
    unit: str | None = None
    number_format: str | None = None
    formula_template: str | None = Field(
        None,
        description="Row formula with {row} placeholder, e.g. '=B{row}*C{row}'. Marks a calculated column.",
    )


CellValue = str | float | int | bool | None


class TableSpec(DFModel):
    name: str
    anchor: str = "A1"
    columns: list[ColumnSpec]
    rows: list[list[CellValue]] = Field(default_factory=list)
    source_dataset: str | None = Field(
        None,
        description="Dataset id whose rows fill this table (columns matched by name); rows then stay empty",
    )


class CellSpec(DFModel):
    ref: str
    value: CellValue = None
    formula: str | None = None
    number_format: str | None = None
    style_role: Literal["label", "input", "output", "header", "note"] | None = None


class SheetChartSpec(DFModel):
    chart_type: ChartType
    title: str
    data_ref: str = Field(description="Range with series values incl. header row, e.g. 'B1:C13'")
    categories_ref: str
    anchor: str = "H2"


class SheetPlan(DFModel):
    id: str
    name: str = Field(max_length=31)
    role: SheetRole
    tables: list[TableSpec] = Field(default_factory=list)
    cells: list[CellSpec] = Field(default_factory=list)
    charts: list[SheetChartSpec] = Field(default_factory=list)
    freeze: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    description: str = Field("", description="One line shown in the README sheet")


class NamedRange(DFModel):
    name: str
    sheet_id: str
    ref: str


class ExpectedValue(DFModel):
    sheet_id: str
    cell: str
    expected: float
    tolerance: float = 1e-6
    rationale: str = ""


class WorkbookPlan(_UnitDocument):
    format: Literal["xlsx"] = "xlsx"
    title: str
    sheets: list[SheetPlan]
    named_ranges: list[NamedRange] = Field(default_factory=list)
    checks: list[ExpectedValue] = Field(default_factory=list)
    style: StyleSpec = Field(default_factory=StyleSpec)

    @model_validator(mode="after")
    def _unique_sheet_names(self) -> WorkbookPlan:
        names = [s.name.lower() for s in self.sheets]
        if len(names) != len(set(names)):
            raise ValueError("sheet names must be unique (case-insensitive)")
        return self

    def _collect_ids(self) -> list[str]:
        return [s.id for s in self.sheets]

    def units(self) -> dict[str, DFModel]:
        return {s.id: s for s in self.sheets}


ArtifactIR = Annotated[DeckPlan | DocumentPlan | WorkbookPlan, Field(discriminator="format")]
