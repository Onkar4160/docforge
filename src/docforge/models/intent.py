"""Request interpretation contracts (DATA_MODELS §3). These are also the InterpreterAgent's output schema."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from docforge.models.base import DFModel


class OutputFormat(StrEnum):
    pptx = "pptx"
    docx = "docx"
    xlsx = "xlsx"


class LengthUnit(StrEnum):
    slides = "slides"
    pages = "pages"
    words = "words"
    sheets = "sheets"
    auto = "auto"


class LengthSpec(DFModel):
    unit: LengthUnit = LengthUnit.auto
    target: int | None = None
    min: int | None = None
    max: int | None = None
    explicit: bool = Field(False, description="True only when the user stated the length.")


class DetailLevel(StrEnum):
    brief = "brief"
    standard = "standard"
    detailed = "detailed"


class CitationStyle(StrEnum):
    numeric = "numeric"
    apa = "apa"
    harvard = "harvard"
    none = "none"


class OutputSpec(DFModel):
    format: OutputFormat
    purpose: str = ""
    audience: str = "general professional audience"
    tone: str = "professional"
    language: str = "en"
    detail_level: DetailLevel = DetailLevel.standard
    length: LengthSpec = Field(default_factory=LengthSpec)
    citation_style: CitationStyle = CitationStyle.numeric
    style_notes: list[str] = Field(default_factory=list)


class RequestKind(StrEnum):
    new_task = "new_task"
    continue_task = "continue_task"
    modify_artifact = "modify_artifact"
    regenerate = "regenerate"
    change_objective = "change_objective"
    clarification_answer = "clarification_answer"
    question = "question"


class ConfirmationDecision(StrEnum):
    approve = "approve"
    decline = "decline"
    unclear = "unclear"


class ChangeOperation(StrEnum):
    restyle = "restyle"
    rewrite = "rewrite"
    add = "add"
    remove = "remove"
    reorder = "reorder"
    expand = "expand"
    condense = "condense"
    replace_data = "replace_data"
    regenerate = "regenerate"
    convert_format = "convert_format"


class ScopeLevel(StrEnum):
    artifact = "artifact"
    unit = "unit"
    element = "element"
    style = "style"


class TargetKind(StrEnum):
    slide = "slide"
    section = "section"
    sheet = "sheet"
    element = "element"
    table = "table"
    chart = "chart"
    paragraph = "paragraph"
    style = "style"


class TargetRef(DFModel):
    kind: TargetKind
    locator: str = Field(description="The reference as the user expressed it, e.g. 'slide 4'.")
    resolved_unit_id: str | None = None


class ChangeScope(DFModel):
    level: ScopeLevel
    targets: list[TargetRef] = Field(default_factory=list)


class StyleChange(DFModel):
    property: str = Field(description="StyleSpec field, e.g. 'heading_sizes_pt.h1' or 'body_font'.")
    value: str = Field(description="New value as text, e.g. '20' or 'Georgia'.")


class StylePlan(DFModel):
    changes: list[StyleChange] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    unsupported_requests: list[str] = Field(default_factory=list)


class SlidePlacementMode(StrEnum):
    start = "start"
    end = "end"
    before = "before"
    after = "after"
    between = "between"


class SlidePlacement(DFModel):
    mode: SlidePlacementMode
    anchor: TargetRef | None = None
    before: TargetRef | None = None
    after: TargetRef | None = None

    @model_validator(mode="after")
    def _anchors_match_mode(self) -> SlidePlacement:
        if self.mode in (SlidePlacementMode.before, SlidePlacementMode.after) and self.anchor is None:
            raise ValueError("before/after placement requires an anchor")
        if self.mode == SlidePlacementMode.between and (self.before is None or self.after is None):
            raise ValueError("between placement requires both before and after anchors")
        if self.mode in (SlidePlacementMode.start, SlidePlacementMode.end) and any(
            (self.anchor, self.before, self.after)
        ):
            raise ValueError("start/end placement cannot include slide anchors")
        return self


class ChangeRequest(DFModel):
    operation: ChangeOperation
    scope: ChangeScope
    instruction: str
    style_changes: list[StyleChange] = Field(default_factory=list)
    placement: SlidePlacement | None = None

    @model_validator(mode="after")
    def _unit_scope_has_targets(self) -> ChangeRequest:
        if self.scope.level in (ScopeLevel.unit, ScopeLevel.element) and not self.scope.targets:
            raise ValueError("unit/element scoped changes need at least one target")
        return self


class ResearchDepth(StrEnum):
    none = "none"
    light = "light"
    standard = "standard"
    deep = "deep"


class ResearchNeed(DFModel):
    depth: ResearchDepth = ResearchDepth.none
    rationale: str = ""


class ClarificationQuestion(DFModel):
    question: str
    options: list[str] = Field(default_factory=list)


class Interpretation(DFModel):
    kind: RequestKind
    confidence: float = Field(ge=0.0, le=1.0)
    objective: str
    output_spec: OutputSpec | None = None
    change: ChangeRequest | None = None
    research: ResearchNeed = Field(default_factory=ResearchNeed)
    clarification_questions: list[ClarificationQuestion] = Field(default_factory=list)
    confirmation: ConfirmationDecision | None = None
    assumptions: list[str] = Field(default_factory=list)
    referenced_file_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _modify_needs_change(self) -> Interpretation:
        if self.kind == RequestKind.modify_artifact and self.change is None:
            raise ValueError("modify_artifact interpretations must include a change request")
        return self
