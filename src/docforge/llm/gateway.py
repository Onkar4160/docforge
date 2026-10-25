"""Provider-neutral LLM gateway (ADR-004).

Responsibilities, in order: resolve ``provider:model`` specs, retry transient failures with backoff,
enforce structured output (schema in prompt, optional native schema, validate, repair), and fall back
to ``LLM_FALLBACK_MODEL`` when the primary model cannot produce a valid answer.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from docforge.core.config import Settings
from docforge.core.errors import (
    LLMError,
    LLMModelUnavailable,
    LLMOutputInvalid,
    LLMRateLimited,
    LLMRefused,
    LLMSchemaRejected,
    LLMTransient,
)
from docforge.core.logging import get_logger
from docforge.llm.base import ChatMessage, LLMClient, LLMRequest, LLMResult, T, request_hash
from docforge.llm.jsonout import parse_structured, repair_prompt, schema_instructions
from docforge.llm.providers.base import ChatProvider, ProviderRequest, ProviderResponse
from docforge.models.llm import Usage

log = get_logger(__name__)

Sleep = Callable[[float], Awaitable[None]]


def split_spec(spec: str, default_provider: str) -> tuple[str, str]:
    """Split a model spec: ``openai_compat:llama3.1`` names its provider, a bare name uses the default."""
    provider, sep, model = spec.partition(":")
    if sep and provider in {"gemini", "openai_compat", "fake"}:
        return provider, model
    return default_provider, spec


class LLMGateway(LLMClient):
    def __init__(
        self,
        settings: Settings,
        providers: dict[str, ChatProvider],
        *,
        sleep: Sleep = asyncio.sleep,
        backoff_base_s: float = 1.0,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self._sleep = sleep
        self._backoff = backoff_base_s
        self._native_schema_off: set[str] = set()
        # model spec -> monotonic time until which it is skipped (retired, or out of quota).
        self._unavailable: dict[str, float] = {}
        self._clock = time.monotonic

    def _provider(self, name: str) -> ChatProvider:
        try:
            return self.providers[name]
        except KeyError as exc:
            raise LLMError(f"LLM provider '{name}' is not configured") from exc

    def _model_chain(self, req: LLMRequest) -> list[str]:
        primary = req.model or self.settings.model_for(req.agent)
        chain = [primary, self.settings.llm_primary_model, *self.settings.fallback_models]
        unique = list(dict.fromkeys(chain))
        return unique[: req.max_models] if req.max_models else unique

    def _mark_unavailable(self, spec: str, seconds: float, why: str) -> None:
        self._unavailable[spec] = self._clock() + seconds
        log.warning("model=%s skipped for %.0f min (%s)", spec, seconds / 60, why)

    async def complete(self, req: LLMRequest[T]) -> LLMResult[T]:
        chain = self._model_chain(req)
        last_error: LLMError | None = None
        for index, spec in enumerate(chain):
            if self._unavailable.get(spec, 0) > self._clock():
                continue
            provider_name, model = split_spec(spec, self.settings.llm_provider)
            try:
                result = await self._complete_on(self._provider(provider_name), model, req)
            except LLMModelUnavailable as exc:
                self._mark_unavailable(spec, 24 * 3600, "retired or unknown model")
                last_error = exc
                continue
            except LLMRateLimited as exc:
                # Retries already waited out short limits; a long or daily limit means move on.
                self._mark_unavailable(spec, exc.retry_after_s or 3600, "quota exhausted")
                last_error = exc
                continue
            except LLMError as exc:
                last_error = exc
                if index + 1 < len(chain):
                    log.warning("agent=%s model=%s failed (%s); trying fallback", req.agent, spec, exc.code)
                continue
            result.fallback_used = index > 0
            return result
        if last_error is None or isinstance(last_error, LLMRateLimited | LLMModelUnavailable):
            raise LLMRateLimited(
                "every configured AI model is out of quota or unavailable right now",
                details={"models": chain, "quota": True},
            )
        raise last_error

    async def _complete_on(self, provider: ChatProvider, model: str, req: LLMRequest[T]) -> LLMResult[T]:
        system = req.system
        if req.output_type is not None:
            system = (
                f"{system}\n\n{schema_instructions(req.output_type)}"
                if system
                else schema_instructions(req.output_type)
            )
        messages = list(req.messages)
        usage = Usage()
        attempts = 0
        started = time.perf_counter()

        repair_attempts = (
            self.settings.llm_repair_attempts
            if req.repair_attempts is None
            else req.repair_attempts
        )
        for repair_round in range(repair_attempts + 1):
            preq = ProviderRequest(
                model=model,
                system=system,
                messages=messages,
                temperature=self.settings.llm_temperature if req.temperature is None else req.temperature,
                max_tokens=req.max_tokens or self.settings.llm_max_output_tokens,
                json_mode=req.output_type is not None,
                json_schema=self._native_schema(provider, req),
            )
            resp, tries = await self._generate_with_retries(provider, preq, req)
            attempts += tries
            usage = usage + resp.usage

            if resp.finish_reason == "length":
                raise LLMOutputInvalid(
                    f"{req.agent}: output truncated at max tokens",
                    details={"agent": req.agent, "model": model},
                )
            parsed = None
            if req.output_type is not None:
                try:
                    parsed = parse_structured(resp.text, req.output_type)
                except ValueError as exc:
                    if repair_round >= self.settings.llm_repair_attempts:
                        raise LLMOutputInvalid(
                            f"{req.agent}: invalid structured output after repair: {exc}",
                            details={"agent": req.agent, "model": model},
                        ) from exc
                    log.info("agent=%s model=%s invalid output, repairing: %s", req.agent, model, exc)
                    messages = [
                        *messages,
                        ChatMessage("assistant", resp.text),
                        ChatMessage("user", repair_prompt(str(exc))),
                    ]
                    continue
            log.info(
                "llm agent=%s provider=%s model=%s in=%d out=%d attempts=%d ms=%d",
                req.agent,
                provider.name,
                model,
                usage.input_tokens,
                usage.output_tokens,
                attempts,
                int((time.perf_counter() - started) * 1000),
            )
            return LLMResult(
                parsed=parsed,
                text=resp.text,
                finish_reason=resp.finish_reason,
                provider=provider.name,
                model=resp.model,
                usage=usage,
                request_hash=request_hash(req, f"{provider.name}:{model}"),
                attempts=attempts,
            )
        raise AssertionError("unreachable")  # pragma: no cover

    def _native_schema(self, provider: ChatProvider, req: LLMRequest) -> dict | None:
        if (
            req.output_type is None
            or not self.settings.llm_native_schema
            or not provider.supports_native_schema
            or provider.name in self._native_schema_off
        ):
            return None
        return req.output_type.model_json_schema()

    async def _generate_with_retries(
        self, provider: ChatProvider, preq: ProviderRequest, req: LLMRequest
    ) -> tuple[ProviderResponse, int]:
        retries = self.settings.llm_max_retries if req.max_retries is None else req.max_retries
        for attempt in range(retries + 1):
            try:
                call = provider.generate(preq)
                if req.timeout_s is not None:
                    return await asyncio.wait_for(call, timeout=req.timeout_s), attempt + 1
                return await call, attempt + 1
            except TimeoutError as exc:
                if attempt >= retries:
                    raise LLMTransient(f"{provider.name}: request timed out") from exc
                delay = self._backoff * (2**attempt)
                log.warning("provider=%s timed out; retry in %.1fs", provider.name, delay)
                await self._sleep(delay)
            except LLMSchemaRejected:
                # Remember for this process and retry immediately with prompt-only schema.
                self._native_schema_off.add(provider.name)
                preq.json_schema = None
                log.warning("provider=%s rejected native schema; using prompt-only schema", provider.name)
            except LLMRefused:
                raise
            except LLMRateLimited as exc:
                wait = exc.retry_after_s
                if exc.daily or attempt >= retries or (wait is not None and wait > 45):
                    raise
                delay = wait if wait is not None else self._backoff * (2**attempt) * 4
                log.warning("provider=%s rate limited; retry in %.1fs", provider.name, delay)
                await self._sleep(delay)
            except LLMTransient as exc:
                if attempt >= retries:
                    raise
                delay = self._backoff * (2**attempt)
                log.warning(
                    "provider=%s transient error (%s); retry in %.1fs", provider.name, exc.code, delay
                )
                await self._sleep(delay)
        # Only reachable when the final allowed attempt was a schema rejection.
        return await provider.generate(preq), retries + 2

    async def aclose(self) -> None:
        for provider in self.providers.values():
            await provider.aclose()
