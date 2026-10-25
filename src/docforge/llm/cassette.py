"""Record/replay wrapper for reproducible LLM-dependent tests (NFR-1, TESTING §3)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from docforge.core.errors import CassetteMissing
from docforge.llm.base import LLMClient, LLMRequest, LLMResult, T, request_hash
from docforge.models.llm import Usage


class CassetteLLMClient(LLMClient):
    def __init__(
        self,
        directory: Path,
        mode: str,
        inner: LLMClient | None = None,
        *,
        model_for: Callable[[str], str],
    ) -> None:
        if mode not in ("record", "replay"):
            raise ValueError(f"cassette mode must be record or replay, not {mode!r}")
        if mode == "record" and inner is None:
            raise ValueError("record mode needs an inner client")
        self.directory = directory
        self.mode = mode
        self.inner = inner
        self._model_for = model_for

    def _path(self, req: LLMRequest) -> tuple[Path, str]:
        digest = request_hash(req, req.model or self._model_for(req.agent))
        return self.directory / req.agent / f"{digest}.json", digest

    async def complete(self, req: LLMRequest[T]) -> LLMResult[T]:
        path, digest = self._path(req)
        if self.mode == "replay":
            if not path.exists():
                raise CassetteMissing(
                    f"no cassette for agent '{req.agent}' hash {digest[:12]}; re-record with "
                    "LLM_CASSETTE_MODE=record",
                    details={"agent": req.agent, "hash": digest, "path": str(path)},
                )
            data = json.loads(path.read_text(encoding="utf-8"))
            parsed = (
                req.output_type.model_validate(data["parsed"]) if req.output_type and data["parsed"] else None
            )
            return LLMResult(
                parsed=parsed,
                text=data["text"],
                finish_reason=data["finish_reason"],
                provider=data["provider"],
                model=data["model"],
                usage=Usage.model_validate(data["usage"]),
                request_hash=digest,
                replayed=True,
            )

        assert self.inner is not None
        result = await self.inner.complete(req)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "agent": req.agent,
                    "parsed": result.parsed.model_dump(mode="json") if result.parsed is not None else None,
                    "text": result.text,
                    "finish_reason": result.finish_reason,
                    "provider": result.provider,
                    "model": result.model,
                    "usage": result.usage.model_dump(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return result

    async def aclose(self) -> None:
        if self.inner is not None:
            await self.inner.aclose()
