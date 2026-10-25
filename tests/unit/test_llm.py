from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from docforge.core.errors import (
    CassetteMissing,
    LLMError,
    LLMOutputInvalid,
    LLMRateLimited,
    LLMRefused,
    LLMSchemaRejected,
    LLMTransient,
)
from docforge.llm import (
    CassetteLLMClient,
    ChatMessage,
    FakeLLMClient,
    LLMGateway,
    LLMRequest,
    build_chat_providers,
    build_embedder,
    build_llm_client,
)
from docforge.llm.base import request_hash
from docforge.llm.fake import FakeChatProvider
from docforge.llm.gateway import split_spec
from docforge.llm.jsonout import extract_json, parse_structured
from docforge.llm.providers import (
    GeminiChatProvider,
    GeminiEmbeddingProvider,
    HashingEmbeddingProvider,
    OpenAICompatChatProvider,
    OpenAICompatEmbeddingProvider,
    ProviderRequest,
    ProviderResponse,
)
from docforge.models.llm import Usage
from tests.conftest import make_settings

pytestmark = pytest.mark.anyio


class Answer(BaseModel):
    value: int


def _req(**kw) -> LLMRequest:
    base = dict(agent="tester", system="sys", messages=[ChatMessage("user", "q")], output_type=Answer)
    base.update(kw)
    return LLMRequest(**base)


async def _no_sleep(_: float) -> None:
    return None


def _gateway(tmp_path: Path, providers: dict, **settings_kw) -> LLMGateway:
    s = make_settings(tmp_path, llm_provider="gemini", **settings_kw)
    return LLMGateway(s, providers, sleep=_no_sleep)


# ---------------------------------------------------------------- helpers


def test_split_spec():
    assert split_spec("gemini-3.8-flash", "gemini") == ("gemini", "gemini-3.8-flash")
    assert split_spec("openai_compat:llama3.1:8b", "gemini") == ("openai_compat", "llama3.1:8b")
    assert split_spec("qwen2.5:7b", "openai_compat") == ("openai_compat", "qwen2.5:7b")


def test_request_hash_stable_and_sensitive():
    a = request_hash(_req(), "gemini:m")
    assert a == request_hash(_req(), "gemini:m")
    assert a != request_hash(_req(system="other"), "gemini:m")
    assert a != request_hash(_req(), "gemini:n")
    assert a != request_hash(_req(output_type=None), "gemini:m")


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('```json\n{"value": 1}\n```') == {"value": 1}
    assert extract_json('Sure! Here it is: {"value": 2} hope that helps') == {"value": 2}
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_parse_structured_reports_schema_errors():
    with pytest.raises(ValueError, match="value"):
        parse_structured('{"value": "x"}', Answer)


# ---------------------------------------------------------------- gateway


async def test_gateway_structured_success_puts_schema_in_prompt(tmp_path: Path):
    fake = FakeChatProvider(['{"value": 3}'])
    result = await _gateway(tmp_path, {"gemini": fake}).complete(_req())
    assert result.parsed == Answer(value=3)
    sent = fake.requests[0]
    assert sent.json_mode is True and sent.json_schema is None
    assert "<json_schema>" in sent.system and sent.system.startswith("sys")
    assert sent.model == "gemini-3.8-flash"


async def test_gateway_repairs_invalid_json_once(tmp_path: Path):
    fake = FakeChatProvider(["not json", '{"value": 4}'])
    result = await _gateway(tmp_path, {"gemini": fake}).complete(_req())
    assert result.parsed.value == 4
    repair_turn = fake.requests[1].messages
    assert [m.role for m in repair_turn] == ["user", "assistant", "user"]
    assert "could not be used" in repair_turn[-1].content


async def test_gateway_falls_back_to_fallback_model(tmp_path: Path):
    fake = FakeChatProvider(["bad", "still bad", '{"value": 5}'])
    result = await _gateway(tmp_path, {"gemini": fake}).complete(_req())
    assert result.parsed.value == 5 and result.fallback_used
    assert [r.model for r in fake.requests] == ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.7-flash"]


async def test_gateway_raises_after_all_models_fail(tmp_path: Path):
    fake = FakeChatProvider(["bad"] * 4)
    with pytest.raises(LLMOutputInvalid):
        await _gateway(tmp_path, {"gemini": fake}).complete(_req())


async def test_gateway_retries_transient_errors(tmp_path: Path):
    fake = FakeChatProvider([LLMRateLimited("slow down"), LLMTransient("503"), '{"value": 6}'])
    result = await _gateway(tmp_path, {"gemini": fake}).complete(_req())
    assert result.parsed.value == 6 and result.attempts == 3 and not result.fallback_used


async def test_gateway_gives_up_after_max_retries_then_uses_fallback(tmp_path: Path):
    fake = FakeChatProvider([LLMTransient("x")] * 2 + ['{"value": 7}'])
    gw = _gateway(tmp_path, {"gemini": fake}, llm_max_retries=1)
    result = await gw.complete(_req())
    assert result.fallback_used and result.parsed.value == 7


async def test_gateway_native_schema_disabled_after_rejection(tmp_path: Path):
    fake = FakeChatProvider([LLMSchemaRejected("no"), '{"value": 8}', '{"value": 9}'])
    gw = _gateway(tmp_path, {"gemini": fake}, llm_native_schema=True)
    assert (await gw.complete(_req())).parsed.value == 8
    assert fake.requests[0].json_schema is not None and fake.requests[1].json_schema is None
    await gw.complete(_req())
    assert fake.requests[2].json_schema is None  # remembered for the process


async def test_gateway_truncation_is_not_repaired(tmp_path: Path):
    truncated = ProviderResponse(text='{"val', finish_reason="length", usage=Usage(), model="m")
    fake = FakeChatProvider([truncated, truncated])
    with pytest.raises(LLMOutputInvalid, match="truncated"):
        await _gateway(tmp_path, {"gemini": fake}, llm_fallback_model=None).complete(_req())
    assert len(fake.requests) == 1


async def test_gateway_text_mode_and_provider_prefix(tmp_path: Path):
    local = FakeChatProvider(["hello"])
    local.name = "openai_compat"
    gw = _gateway(tmp_path, {"openai_compat": local}, llm_primary_model="openai_compat:llama3.1")
    result = await gw.complete(_req(output_type=None))
    assert result.text == "hello" and result.parsed is None
    assert local.requests[0].model == "llama3.1" and local.requests[0].json_mode is False


async def test_gateway_unknown_provider(tmp_path: Path):
    with pytest.raises(LLMError, match="not configured"):
        await _gateway(tmp_path, {}, llm_fallback_model=None).complete(_req())


def test_build_chat_providers_only_what_specs_need(tmp_path: Path):
    s = make_settings(tmp_path, llm_provider="gemini", llm_fallback_model="openai_compat:qwen2.5")
    assert set(build_chat_providers(s)) == {"gemini", "openai_compat"}
    s2 = make_settings(
        tmp_path, llm_provider="openai_compat", llm_primary_model="llama3.1", llm_fallback_model=None
    )
    assert set(build_chat_providers(s2)) == {"openai_compat"}


def test_factory_and_embedder_selection(tmp_path: Path):
    assert isinstance(build_llm_client(make_settings(tmp_path)), FakeLLMClient)
    assert isinstance(build_llm_client(make_settings(tmp_path, llm_provider="gemini")), LLMGateway)
    replay = build_llm_client(make_settings(tmp_path, llm_provider="gemini", llm_cassette_mode="replay"))
    assert isinstance(replay, CassetteLLMClient) and replay.inner is None
    assert isinstance(build_embedder(make_settings(tmp_path)), HashingEmbeddingProvider)
    # Gemini embeddings requested but no key: degrade to offline hashing instead of failing at boot.
    assert isinstance(
        build_embedder(make_settings(tmp_path, embedding_provider="gemini")), HashingEmbeddingProvider
    )
    keyed = make_settings(tmp_path, embedding_provider="gemini", gemini_api_key="k")
    assert isinstance(build_embedder(keyed), GeminiEmbeddingProvider)


# ---------------------------------------------------------------- fake client + cassette (NFR-1)


async def test_fake_client_structured_and_records():
    fake = FakeLLMClient({"tester": [Answer(value=1), Answer(value=2)]})
    assert (await fake.complete(_req())).parsed == Answer(value=1)
    assert (await fake.complete(_req())).parsed == Answer(value=2)
    assert (await fake.complete(_req())).parsed == Answer(value=2)
    assert len(fake.calls_for("tester")) == 3
    with pytest.raises(LLMError, match="no response"):
        await fake.complete(_req(agent="other"))


async def test_cassette_record_then_replay(tmp_path: Path):
    s = make_settings(tmp_path)
    rec = CassetteLLMClient(
        tmp_path / "cas", "record", FakeLLMClient({"tester": Answer(value=42)}), model_for=s.model_for
    )
    await rec.complete(_req())
    files = list((tmp_path / "cas" / "tester").glob("*.json"))
    assert len(files) == 1 and json.loads(files[0].read_text())["parsed"] == {"value": 42}
    rep = CassetteLLMClient(tmp_path / "cas", "replay", model_for=s.model_for)
    result = await rep.complete(_req())
    assert result.parsed == Answer(value=42) and result.replayed
    with pytest.raises(CassetteMissing, match="tester"):
        await rep.complete(_req(system="changed"))


# ---------------------------------------------------------------- REST adapters on a mock transport


def _mock(responses: list[tuple[int, dict]], seen: list[httpx.Request]) -> httpx.AsyncClient:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        status, body = queue.pop(0)
        return httpx.Response(status, json=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _preq(**kw) -> ProviderRequest:
    base = dict(
        model="gemini-3.8-flash",
        system="be brief",
        messages=[ChatMessage("user", "hi"), ChatMessage("assistant", "yo"), ChatMessage("user", "again")],
        temperature=0.2,
        max_tokens=100,
    )
    base.update(kw)
    return ProviderRequest(**base)


async def test_gemini_request_shape_and_parsing():
    seen: list[httpx.Request] = []
    reply = {
        "candidates": [
            {
                "content": {"parts": [{"text": "thinking...", "thought": True}, {"text": '{"value": 1}'}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, "thoughtsTokenCount": 2},
        "modelVersion": "gemini-3.8-flash",
    }
    p = GeminiChatProvider("k", timeout=5, client=_mock([(200, reply)], seen))
    resp = await p.generate(_preq(json_mode=True, json_schema={"type": "object"}))
    assert resp.text == '{"value": 1}' and resp.finish_reason == "stop"
    assert resp.usage.input_tokens == 7 and resp.usage.output_tokens == 5

    req = seen[0]
    assert req.url.path.endswith("/models/gemini-3.8-flash:generateContent")
    assert req.headers["x-goog-api-key"] == "k"
    body = json.loads(req.content)
    assert body["systemInstruction"]["parts"][0]["text"] == "be brief"
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["responseJsonSchema"] == {"type": "object"}
    assert body["generationConfig"]["maxOutputTokens"] == 100


async def test_gemini_error_mapping():
    cases = [
        ((429, {}), LLMRateLimited),
        ((503, {}), LLMTransient),
        ((400, {"error": "bad schema"}), LLMSchemaRejected),
        ((200, {"promptFeedback": {"blockReason": "SAFETY"}}), LLMRefused),
        ((200, {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}), LLMRefused),
    ]
    for response, error in cases:
        p = GeminiChatProvider("k", timeout=5, client=_mock([response], []))
        with pytest.raises(error):
            await p.generate(_preq(json_schema={"type": "object"}))


async def test_gemini_requires_key_on_use_not_construction():
    p = GeminiChatProvider(None, timeout=5, client=_mock([], []))
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        await p.generate(_preq())


async def test_gemini_max_tokens_maps_to_length():
    reply = {"candidates": [{"content": {"parts": [{"text": "{"}]}, "finishReason": "MAX_TOKENS"}]}
    p = GeminiChatProvider("k", timeout=5, client=_mock([(200, reply)], []))
    assert (await p.generate(_preq())).finish_reason == "length"


async def test_gemini_embeddings_batch_and_normalise():
    seen: list[httpx.Request] = []
    p = GeminiEmbeddingProvider(
        "k",
        model="gemini-embedding-001",
        dimensions=2,
        timeout=5,
        client=_mock([(200, {"embeddings": [{"values": [3, 4]}, {"values": [0, 2]}]})], seen),
    )
    vectors = await p.embed(["a", "b"], task="query")
    assert vectors == [[0.6, 0.8], [0.0, 1.0]]
    body = json.loads(seen[0].content)
    assert seen[0].url.path.endswith("/models/gemini-embedding-001:batchEmbedContents")
    assert body["requests"][0]["embedContentConfig"] == {
        "taskType": "RETRIEVAL_QUERY",
        "outputDimensionality": 2,
    }


async def test_openai_compat_request_shape():
    seen: list[httpx.Request] = []
    reply = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1},
        "model": "llama3.1",
    }
    p = OpenAICompatChatProvider(
        "http://localhost:11434/v1", None, timeout=5, client=_mock([(200, reply)], seen)
    )
    resp = await p.generate(_preq(model="llama3.1", json_mode=True))
    assert resp.text == "ok" and resp.usage.input_tokens == 4
    body = json.loads(seen[0].content)
    assert str(seen[0].url) == "http://localhost:11434/v1/chat/completions"
    assert "authorization" not in seen[0].headers
    assert body["messages"][0] == {"role": "system", "content": "be brief"}
    assert body["response_format"] == {"type": "json_object"}


async def test_openai_compat_auth_header_and_content_filter():
    seen: list[httpx.Request] = []
    reply = {"choices": [{"message": {"content": ""}, "finish_reason": "content_filter"}]}
    p = OpenAICompatChatProvider(
        "https://example.org/v1", "sk-x", timeout=5, client=_mock([(200, reply)], seen)
    )
    with pytest.raises(LLMRefused):
        await p.generate(_preq())
    assert seen[0].headers["authorization"] == "Bearer sk-x"


async def test_openai_compat_embeddings_ordered():
    reply = {"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [2, 0]}]}
    p = OpenAICompatEmbeddingProvider(
        "http://h/v1", None, model="nomic", timeout=5, client=_mock([(200, reply)], [])
    )
    assert await p.embed(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]


async def test_hashing_embeddings_deterministic_and_similar():
    e = HashingEmbeddingProvider(256)
    a, b, c = await e.embed(["solar panel costs fall", "solar panel costs are falling", "medieval poetry"])
    assert a == (await e.embed(["solar panel costs fall"]))[0]

    def dot(x, y):
        return sum(i * j for i, j in zip(x, y, strict=True))

    assert dot(a, b) > dot(a, c)
