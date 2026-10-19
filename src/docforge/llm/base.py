"""Provider-neutral LLM contracts (ADR-004). Agents depend only on ``LLMClient``."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

from docforge.models.llm import Usage

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class LLMRequest(Generic[T]):
    agent: str
    system: str
    messages: list[ChatMessage]
    output_type: type[T] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    model: str | None = None


@dataclass
class LLMResult(Generic[T]):
    parsed: T | None
    text: str
    finish_reason: str | None
    provider: str
    model: str
    usage: Usage
    request_hash: str
    attempts: int = 1
    fallback_used: bool = False
    replayed: bool = False
    warnings: list[str] = field(default_factory=list)


def request_hash(req: LLMRequest, model: str) -> str:
    """Stable hash of everything that determines the answer; keys cassettes (TESTING §3)."""
    payload = {
        "model": model,
        "system": req.system,
        "messages": [[m.role, m.content] for m in req.messages],
        "output": req.output_type.model_json_schema() if req.output_type else None,
        "temperature": req.temperature,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LLMClient(ABC):
    @abstractmethod
    async def complete(self, req: LLMRequest[T]) -> LLMResult[T]:
        """Run one request and return the final, validated result."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        pass
