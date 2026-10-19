"""Quality report contracts (DATA_MODELS §9, QUALITY §3)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from docforge.models.base import DFModel, VersionedDocument


class Dimension(StrEnum):
    content = "content"
    evidence = "evidence"
    structure = "structure"
    layout = "layout"
    typography = "typography"
    data = "data"
    template = "template"
    accessibility = "accessibility"
    validity = "validity"


class Severity(StrEnum):
    info = "info"
    minor = "minor"
    major = "major"
    critical = "critical"


class FindingStatus(StrEnum):
    detected = "detected"
    corrected = "corrected"
    unresolved = "unresolved"


class Finding(DFModel):
    id: str
    check_id: str
    dimension: Dimension
    severity: Severity
    message: str
    unit_id: str | None = None
    element: str | None = None
    details: dict = Field(default_factory=dict)
    status: FindingStatus = FindingStatus.detected
    repair_action: str | None = None


class CheckStatus(StrEnum):
    passed = "passed"
    failed = "failed"
    skipped = "skipped"
    error = "error"


class CheckResult(DFModel):
    check_id: str
    tier: int = Field(1, ge=1, le=5)
    status: CheckStatus
    reason: str | None = None
    duration_ms: int = 0


class Verdict(StrEnum):
    passed = "pass"
    pass_with_warnings = "pass_with_warnings"
    failed = "fail"


class QualitySummary(DFModel):
    detected: int = 0
    corrected: int = 0
    unresolved: int = 0
    skipped: int = 0


class QualityReport(VersionedDocument):
    id: str
    artifact_id: str
    version: int
    iterations: int = 0
    checks: list[CheckResult] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    summary: QualitySummary = Field(default_factory=QualitySummary)
    verdict: Verdict = Verdict.passed

    def finalize(self) -> QualityReport:
        """Recompute summary and verdict from findings/checks (rules in QUALITY §3)."""
        unresolved = [f for f in self.findings if f.status != FindingStatus.corrected]
        skipped = [c for c in self.checks if c.status == CheckStatus.skipped]
        self.summary = QualitySummary(
            detected=len(self.findings),
            corrected=sum(f.status == FindingStatus.corrected for f in self.findings),
            unresolved=len(unresolved),
            skipped=len(skipped),
        )
        if any(f.severity == Severity.critical for f in unresolved):
            self.verdict = Verdict.failed
        elif (
            any(f.severity in (Severity.major, Severity.minor) for f in unresolved)
            or skipped
            or any(c.status == CheckStatus.error for c in self.checks)
        ):
            self.verdict = Verdict.pass_with_warnings
        else:
            self.verdict = Verdict.passed
        return self
