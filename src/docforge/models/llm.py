from __future__ import annotations

from datetime import datetime

from pydantic import Field

from docforge.models.base import DFModel, utcnow


class Usage(DFModel):
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class LLMCallRecord(DFModel):
    id: str
    agent: str
    provider: str
    model: str
    request_hash: str
    usage: Usage = Field(default_factory=Usage)
    finish_reason: str | None = None
    attempts: int = 1
    fallback_used: bool = False
    duration_ms: int = 0
    job_id: str | None = None
    replayed: bool = False
    created_at: datetime = Field(default_factory=utcnow)
