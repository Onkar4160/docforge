"""Research and evidence contracts (DATA_MODELS §4, ADR-006)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from docforge.models.base import DFModel, VersionedDocument, utcnow
from docforge.models.intent import ResearchDepth


class ResearchQuestion(DFModel):
    id: str
    question: str
    priority: int = Field(2, ge=1, le=3, description="1 = essential, 3 = nice to have")
    rationale: str = ""
    query_hints: list[str] = Field(default_factory=list)
    channels: list[Literal["web", "academic", "news"]] = Field(
        default_factory=lambda: ["web"], description="Where to look: web pages, scholarly literature, news"
    )


class ResearchPlan(DFModel):
    depth: ResearchDepth
    questions: list[ResearchQuestion] = Field(default_factory=list)


class SourceKind(StrEnum):
    web = "web"
    user_file = "user_file"
    dataset = "dataset"


class Authority(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class Source(DFModel):
    id: str
    kind: SourceKind
    url: str | None = None
    file_id: str | None = None
    title: str
    publisher: str | None = None
    author: str | None = None
    published_at: str | None = Field(None, description="ISO date or year as published; may be partial.")
    retrieved_at: datetime = Field(default_factory=utcnow)
    authority: Authority = Authority.medium
    authority_rationale: str = ""
    relevance: float = Field(0.5, ge=0.0, le=1.0)
    content_sha256: str | None = None
    excerpt: str = ""
    doi: str | None = None
    venue: str | None = None
    citations: int | None = None


class EvidenceKind(StrEnum):
    fact = "fact"
    figure = "figure"
    finding = "finding"
    quote = "quote"
    definition = "definition"
    opinion = "opinion"


class EvidenceItem(DFModel):
    id: str
    source_id: str
    kind: EvidenceKind
    statement: str
    value: float | None = None
    unit: str | None = None
    as_of: str | None = None
    locator: str = ""
    question_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(0.7, ge=0.0, le=1.0)


class ClaimStatus(StrEnum):
    supported = "supported"
    partially_supported = "partially_supported"
    unsupported = "unsupported"
    assumption = "assumption"
    interpretation = "interpretation"
    estimate = "estimate"


class Claim(DFModel):
    id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    status: ClaimStatus
    note: str | None = None

    @model_validator(mode="after")
    def _supported_needs_evidence(self) -> Claim:
        if self.status in (ClaimStatus.supported, ClaimStatus.partially_supported) and not self.evidence_ids:
            raise ValueError(f"claim {self.id} is {self.status} but cites no evidence")
        return self


class Conflict(DFModel):
    topic: str
    evidence_ids: list[str]
    description: str


class Gap(DFModel):
    question_id: str | None = None
    description: str


class Coverage(DFModel):
    answered: int = 0
    partial: int = 0
    unanswered: int = 0


class ResearchDossier(VersionedDocument):
    id: str
    task_id: str
    plan: ResearchPlan | None = None
    sources: list[Source] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)
    coverage: Coverage = Field(default_factory=Coverage)
    performed: bool = False
    skipped_reason: str | None = None
    notes: list[str] = Field(default_factory=list, description="Provider failures and other caveats")

    @model_validator(mode="after")
    def _references_resolve(self) -> ResearchDossier:
        source_ids = {s.id for s in self.sources}
        evidence_ids = {e.id for e in self.evidence}
        dangling = [e.id for e in self.evidence if e.source_id not in source_ids]
        if dangling:
            raise ValueError(f"evidence references unknown sources: {dangling}")
        for claim in self.claims:
            missing = set(claim.evidence_ids) - evidence_ids
            if missing:
                raise ValueError(f"claim {claim.id} references unknown evidence: {sorted(missing)}")
        return self

    def claim(self, claim_id: str) -> Claim | None:
        return next((c for c in self.claims if c.id == claim_id), None)
