"""Shared helpers for building findings and check results (QUALITY §2, DATA_MODELS §9)."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from contextlib import contextmanager

from docforge.core.ids import new_id
from docforge.models.quality import CheckResult, CheckStatus, Dimension, Finding, Severity

PLACEHOLDER_PATTERNS = re.compile(
    r"lorem ipsum|click to (add|edit)|\bTBD\b|\[insert[^\]]*\]|\bx{3,}\b|\bTODO\b"
    r"|placeholder text|your text here",
    re.IGNORECASE,
)


class CheckRun:
    """Collects results and findings for one validation pass."""

    def __init__(self) -> None:
        self.checks: list[CheckResult] = []
        self.findings: list[Finding] = []

    def finding(
        self,
        check_id: str,
        dimension: Dimension,
        severity: Severity,
        message: str,
        *,
        unit_id: str | None = None,
        element: str | None = None,
        **details,
    ) -> Finding:
        f = Finding(
            id=new_id("finding"),
            check_id=check_id,
            dimension=dimension,
            severity=severity,
            message=message,
            unit_id=unit_id,
            element=element,
            details=details,
        )
        self.findings.append(f)
        return f

    def skipped(self, check_id: str, tier: int, reason: str) -> None:
        self.checks.append(
            CheckResult(check_id=check_id, tier=tier, status=CheckStatus.skipped, reason=reason)
        )

    @contextmanager
    def check(self, check_id: str, tier: int):
        before = len(self.findings)
        started = time.perf_counter()
        try:
            yield
        except Exception as exc:  # a broken check must not hide others; it is reported as an error
            self.checks.append(
                CheckResult(
                    check_id=check_id,
                    tier=tier,
                    status=CheckStatus.error,
                    reason=f"{exc.__class__.__name__}: {exc}"[:300],
                )
            )
            return
        failed = any(f.check_id == check_id for f in self.findings[before:])
        self.checks.append(
            CheckResult(
                check_id=check_id,
                tier=tier,
                status=CheckStatus.failed if failed else CheckStatus.passed,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
        )


def similar(a: str, b: str) -> float:
    from difflib import SequenceMatcher

    norm: Callable[[str], str] = lambda s: re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()  # noqa: E731
    return SequenceMatcher(None, norm(a), norm(b)).ratio()
