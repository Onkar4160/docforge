"""Scripted test doubles (TESTING §3): a whole-client fake and a provider-level fake."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from docforge.core.errors import LLMError
from docforge.llm.base import LLMClient, LLMRequest, LLMResult, T, request_hash
from docforge.llm.providers.base import ChatProvider, ProviderRequest, ProviderResponse
from docforge.models.llm import Usage

Responder = BaseModel | str | Callable[[LLMRequest], BaseModel | str]


class FakeLLMClient(LLMClient):
    """Returns queued responses per agent name and records every request.

    A response may be a Pydantic object (structured output), a string (text output) or a callable
    receiving the request. The last queued response for an agent is reused once the queue drains.
    """

    def __init__(self, responses: dict[str, Responder | list[Responder]] | None = None) -> None:
        self._queues: dict[str, deque[Responder]] = defaultdict(deque)
        self.requests: list[LLMRequest] = []
        for agent, value in (responses or {}).items():
            self.add(agent, *(value if isinstance(value, list) else [value]))

    def add(self, agent: str, *responses: Responder) -> None:
        self._queues[agent].extend(responses)

    def calls_for(self, agent: str) -> list[LLMRequest]:
        return [r for r in self.requests if r.agent == agent]

    async def complete(self, req: LLMRequest[T]) -> LLMResult[T]:
        self.requests.append(req)
        queue = self._queues.get(req.agent)
        if not queue:
            raise LLMError(f"FakeLLMClient has no response for agent '{req.agent}'")
        responder = queue.popleft() if len(queue) > 1 else queue[0]
        value: Any = (
            responder(req) if callable(responder) and not isinstance(responder, BaseModel) else responder
        )
        if isinstance(value, BaseModel):
            text = value.model_dump_json()
            parsed = value if req.output_type is None else req.output_type.model_validate(value.model_dump())
        else:
            text = str(value)
            parsed = req.output_type.model_validate_json(text) if req.output_type is not None else None
        return LLMResult(
            parsed=parsed,
            text=text,
            finish_reason="stop",
            provider="fake",
            model="fake",
            usage=Usage(),
            request_hash=request_hash(req, "fake:fake"),
        )


class FakeChatProvider(ChatProvider):
    """Provider-level fake for exercising the gateway: replies are strings or exceptions, in order."""

    name = "fake"
    supports_native_schema = True

    def __init__(self, replies: list[str | Exception | ProviderResponse]) -> None:
        self.replies = deque(replies)
        self.requests: list[ProviderRequest] = []

    async def generate(self, req: ProviderRequest) -> ProviderResponse:
        self.requests.append(ProviderRequest(**{**req.__dict__, "messages": list(req.messages)}))
        if not self.replies:
            raise LLMError("FakeChatProvider ran out of replies")
        reply = self.replies.popleft()
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, ProviderResponse):
            return reply
        return ProviderResponse(
            text=reply, finish_reason="stop", usage=Usage(input_tokens=1, output_tokens=1), model=req.model
        )
