"""Google Gemini REST adapter (``generativelanguage.googleapis.com``) using plain HTTP."""

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

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
_BATCH_LIMIT = 100

_FINISH = {"STOP": "stop", "MAX_TOKENS": "length"}
_BLOCKED = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "LANGUAGE"}


def _finish(reason: str | None) -> FinishReason:
    if reason in _FINISH:
        return _FINISH[reason]  # type: ignore[return-value]
    if reason in _BLOCKED:
        return "blocked"
    return "stop" if reason is None else "other"


class _GeminiBase:
    def __init__(
        self,
        api_key: str | None,
        *,
        timeout: float,
        client: httpx.AsyncClient | None = None,
        base_url: str = GEMINI_BASE_URL,
    ) -> None:
        # A missing key fails on first use, not at startup, so the app can boot for offline work.
        self._headers = {"x-goog-api-key": api_key or "", "Content-Type": "application/json"}
        self._has_key = bool(api_key)
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._base = base_url.rstrip("/")

    def _require_key(self) -> None:
        if not self._has_key:
            raise LLMError("GEMINI_API_KEY is not set")

    async def aclose(self) -> None:
        await self._client.aclose()


class GeminiChatProvider(_GeminiBase, ChatProvider):
    name = "gemini"
    supports_native_schema = True

    async def generate(self, req: ProviderRequest) -> ProviderResponse:
        self._require_key()
        config: dict = {"temperature": req.temperature, "maxOutputTokens": req.max_tokens}
        if req.json_mode:
            config["responseMimeType"] = "application/json"
        if req.json_schema is not None:
            config["responseJsonSchema"] = req.json_schema
        body = {
            "contents": [
                {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
                for m in req.messages
            ],
            "generationConfig": config,
        }
        if req.system:
            body["systemInstruction"] = {"parts": [{"text": req.system}]}

        data = await post_json(
            self._client,
            f"{self._base}/models/{req.model}:generateContent",
            provider=self.name,
            json=body,
            headers=self._headers,
            schema_sent=req.json_schema is not None,
        )
        block = (data.get("promptFeedback") or {}).get("blockReason")
        if block:
            raise LLMRefused(f"gemini blocked the prompt ({block})", category=block)
        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMRefused("gemini returned no candidates", category=None)
        cand = candidates[0]
        finish = _finish(cand.get("finishReason"))
        if finish == "blocked":
            raise LLMRefused(f"gemini stopped: {cand.get('finishReason')}", category=cand.get("finishReason"))
        # Thought-summary parts (``thought: true``) are not part of the answer.
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        meta = data.get("usageMetadata") or {}
        usage = Usage(
            input_tokens=meta.get("promptTokenCount", 0) or 0,
            output_tokens=(meta.get("candidatesTokenCount", 0) or 0)
            + (meta.get("thoughtsTokenCount", 0) or 0),
        )
        return ProviderResponse(
            text=text, finish_reason=finish, usage=usage, model=data.get("modelVersion", req.model)
        )


class GeminiEmbeddingProvider(_GeminiBase, EmbeddingProvider):
    name = "gemini"

    def __init__(
        self,
        api_key: str | None,
        *,
        model: str,
        dimensions: int | None,
        timeout: float,
        client: httpx.AsyncClient | None = None,
        base_url: str = GEMINI_BASE_URL,
    ) -> None:
        super().__init__(api_key, timeout=timeout, client=client, base_url=base_url)
        self.model = model
        self.dimensions = dimensions

    async def embed(self, texts: list[str], task: EmbedTask = "document") -> list[list[float]]:
        self._require_key()
        task_type = "RETRIEVAL_DOCUMENT" if task == "document" else "RETRIEVAL_QUERY"
        config: dict = {"taskType": task_type}
        if self.dimensions:
            config["outputDimensionality"] = self.dimensions
        out: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_LIMIT):
            chunk = texts[start : start + _BATCH_LIMIT]
            body = {
                "requests": [
                    {
                        "model": f"models/{self.model}",
                        "content": {"parts": [{"text": t}]},
                        "embedContentConfig": config,
                    }
                    for t in chunk
                ]
            }
            data = await post_json(
                self._client,
                f"{self._base}/models/{self.model}:batchEmbedContents",
                provider=self.name,
                json=body,
                headers=self._headers,
            )
            embeddings = data.get("embeddings") or []
            if len(embeddings) != len(chunk):
                raise LLMError("gemini returned a different number of embeddings than inputs")
            # Truncated dimensions are not unit length; normalise so cosine and dot product agree.
            out.extend(l2_normalize(e.get("values") or []) for e in embeddings)
        return out
