"""Adapter contracts that every model backend implements. Backends see plain text in, text out."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

from docforge.llm.base import ChatMessage
from docforge.models.llm import Usage

FinishReason = Literal["stop", "length", "blocked", "other"]
EmbedTask = Literal["document", "query"]


@dataclass
class ProviderRequest:
    model: str
    system: str
    messages: list[ChatMessage]
    temperature: float
    max_tokens: int
    json_mode: bool = False
    json_schema: dict[str, Any] | None = None


@dataclass
class ProviderResponse:
    text: str
    finish_reason: FinishReason
    usage: Usage
    model: str


class ChatProvider(ABC):
    name: str
    supports_native_schema: bool = False

    @abstractmethod
    async def generate(self, req: ProviderRequest) -> ProviderResponse: ...

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        pass


class EmbeddingProvider(ABC):
    name: str

    @abstractmethod
    async def embed(self, texts: list[str], task: EmbedTask = "document") -> list[list[float]]: ...

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        pass


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return [v / norm for v in vector] if norm else vector
