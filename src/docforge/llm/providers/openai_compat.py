"""Adapter for any OpenAI-compatible ``/chat/completions`` server.

Covers self-hosted and third-party backends alike (Ollama, vLLM, LM Studio, llama.cpp server,
OpenRouter, OpenAI), so the platform never depends on a single vendor.
"""

from __future__ import annotations

import httpx

from docforge.core.errors import LLMError, LLMRefused
from docforge.llm.providers.base import (
    ChatProvider,
    EmbeddingProvider,
    EmbedTask,
    FinishReason,
    ProviderRequest,
    ProviderResponse,
    l2_normalize,
)
from docforge.llm.providers.http import post_json
from docforge.models.llm import Usage

_FINISH: dict[str | None, FinishReason] = {
    "stop": "stop",
    "length": "length",
    "content_filter": "blocked",
    None: "stop",
}


class _OpenAICompatBase:
    def __init__(
        self, base_url: str, api_key: str | None, *, timeout: float, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Content-Type": "application/json"}
        if api_key:
            self._headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()


class OpenAICompatChatProvider(_OpenAICompatBase, ChatProvider):
    name = "openai_compat"
    supports_native_schema = True

    async def generate(self, req: ProviderRequest) -> ProviderResponse:
        messages = [{"role": "system", "content": req.system}] if req.system else []
        messages += [{"role": m.role, "content": m.content} for m in req.messages]
        body: dict = {
            "model": req.model,
            "messages": messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if req.json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": req.json_schema, "strict": False},
            }
        elif req.json_mode:
            body["response_format"] = {"type": "json_object"}

        data = await post_json(
            self._client,
            f"{self._base}/chat/completions",
            provider=self.name,
            json=body,
            headers=self._headers,
            schema_sent=req.json_schema is not None,
        )
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("openai_compat returned no choices")
        choice = choices[0]
        finish = _FINISH.get(choice.get("finish_reason"), "other")
        if finish == "blocked":
            raise LLMRefused("provider content filter blocked the response", category="content_filter")
        usage = data.get("usage") or {}
        return ProviderResponse(
            text=(choice.get("message") or {}).get("content") or "",
            finish_reason=finish,
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0) or 0,
                output_tokens=usage.get("completion_tokens", 0) or 0,
            ),
            model=data.get("model", req.model),
        )


class OpenAICompatEmbeddingProvider(_OpenAICompatBase, EmbeddingProvider):
    name = "openai_compat"

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        model: str,
        timeout: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url, api_key, timeout=timeout, client=client)
        self.model = model

    async def embed(self, texts: list[str], task: EmbedTask = "document") -> list[list[float]]:
        data = await post_json(
            self._client,
            f"{self._base}/embeddings",
            provider=self.name,
            json={"model": self.model, "input": texts},
            headers=self._headers,
        )
        rows = sorted(data.get("data") or [], key=lambda r: r.get("index", 0))
        if len(rows) != len(texts):
            raise LLMError("embedding count does not match inputs")
        return [l2_normalize(r["embedding"]) for r in rows]
