"""LLM access for agents. Backends are chosen by configuration only (ADR-004)."""

from docforge.core.config import Settings
from docforge.llm.base import ChatMessage, LLMClient, LLMRequest, LLMResult
from docforge.llm.cassette import CassetteLLMClient
from docforge.llm.fake import FakeLLMClient
from docforge.llm.gateway import LLMGateway, split_spec
from docforge.llm.providers import (
    ChatProvider,
    EmbeddingProvider,
    GeminiChatProvider,
    GeminiEmbeddingProvider,
    HashingEmbeddingProvider,
    OpenAICompatChatProvider,
    OpenAICompatEmbeddingProvider,
)


def _needed_providers(settings: Settings) -> set[str]:
    specs = [settings.llm_primary_model, *settings.fallback_models, *settings.llm_agent_model.values()]
    return {split_spec(s, settings.llm_provider)[0] for s in specs if s}


def build_chat_providers(settings: Settings) -> dict[str, ChatProvider]:
    """Instantiate only the backends the configured model specs refer to."""
    providers: dict[str, ChatProvider] = {}
    for name in _needed_providers(settings):
        if name == "gemini":
            providers[name] = GeminiChatProvider(settings.gemini_api_key, timeout=settings.llm_timeout_s)
        elif name == "openai_compat":
            providers[name] = OpenAICompatChatProvider(
                settings.openai_compat_base_url,
                settings.openai_compat_api_key,
                timeout=settings.llm_timeout_s,
            )
    return providers


def build_llm_client(settings: Settings) -> LLMClient:
    """Gateway over configured providers, optionally wrapped for cassette record/replay."""
    inner: LLMClient | None
    if settings.llm_provider == "fake":
        inner = FakeLLMClient()
    elif settings.llm_cassette_mode == "replay":
        inner = None  # replay never touches the network
    else:
        inner = LLMGateway(settings, build_chat_providers(settings))

    if settings.llm_cassette_mode == "off":
        assert inner is not None
        return inner
    return CassetteLLMClient(
        settings.resolved_cassette_dir, settings.llm_cassette_mode, inner, model_for=settings.model_for
    )


def build_embedder(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "gemini" and settings.gemini_api_key:
        return GeminiEmbeddingProvider(
            settings.gemini_api_key,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout=settings.llm_timeout_s,
        )
    if settings.embedding_provider == "openai_compat":
        return OpenAICompatEmbeddingProvider(
            settings.openai_compat_base_url,
            settings.openai_compat_api_key,
            model=settings.embedding_model,
            timeout=settings.llm_timeout_s,
        )
    # Offline / keyless: deterministic hashing embeddings keep retrieval functional.
    return HashingEmbeddingProvider(settings.embedding_dimensions)


__all__ = [
    "CassetteLLMClient",
    "ChatMessage",
    "FakeLLMClient",
    "LLMClient",
    "LLMGateway",
    "LLMRequest",
    "LLMResult",
    "build_chat_providers",
    "build_embedder",
    "build_llm_client",
]
