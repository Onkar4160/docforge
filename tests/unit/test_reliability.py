"""Model fallback on quota/retirement, 429 parsing, and background message jobs."""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from docforge.core.errors import LLMModelUnavailable, LLMRateLimited
from docforge.llm.fake import FakeChatProvider
from docforge.llm.providers.http import map_http_error
from docforge.models.intent import Interpretation, OutputFormat, OutputSpec, ResearchNeed
from tests.fixtures.decks import sample_deck
from tests.unit.test_llm import _gateway, _req

pytestmark = pytest.mark.anyio

DAILY_429 = {
    "error": {
        "code": 429,
        "message": "Quota exceeded",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}],
            },
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37784s"},
        ],
    }
}


def test_429_details_are_parsed():
    resp = httpx.Response(429, json=DAILY_429)
    with pytest.raises(LLMRateLimited) as info:
        map_http_error(resp, "gemini")
    assert info.value.daily and info.value.retry_after_s == 37784
    with pytest.raises(LLMModelUnavailable):
        map_http_error(httpx.Response(404, json={"error": {"message": "no longer available"}}), "gemini")


async def test_daily_quota_moves_to_next_model_and_is_remembered(tmp_path: Path):
    daily = LLMRateLimited("quota", details={"daily": True, "retry_after_s": 3600})
    fake = FakeChatProvider([daily, '{"value": 1}', '{"value": 2}'])
    gw = _gateway(tmp_path, {"gemini": fake}, llm_fallback_model="gemini-3.7-flash,gemini-3.5-flash")
    assert (await gw.complete(_req())).parsed.value == 1
    assert (await gw.complete(_req())).parsed.value == 2
    # first model tried once, then skipped on the next request
    assert [r.model for r in fake.requests] == ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.7-flash"]


async def test_retired_model_is_skipped(tmp_path: Path):
    fake = FakeChatProvider([LLMModelUnavailable("gone"), '{"value": 3}'])
    gw = _gateway(tmp_path, {"gemini": fake})
    result = await gw.complete(_req())
    assert result.parsed.value == 3 and result.fallback_used


async def test_all_models_out_of_quota_gives_one_clear_error(tmp_path: Path):
    daily = LLMRateLimited("quota", details={"daily": True})
    fake = FakeChatProvider([daily, daily])
    with pytest.raises(LLMRateLimited, match="every configured AI model") as info:
        await _gateway(tmp_path, {"gemini": fake}).complete(_req())
    assert info.value.details["quota"]


async def test_short_rate_limit_waits_and_retries(tmp_path: Path):
    waits: list[float] = []

    async def sleep(s: float) -> None:
        waits.append(s)

    fake = FakeChatProvider([LLMRateLimited("busy", details={"retry_after_s": 7}), '{"value": 4}'])
    gw = _gateway(tmp_path, {"gemini": fake})
    gw._sleep = sleep
    assert (await gw.complete(_req())).parsed.value == 4 and waits == [7]


def test_background_job_reports_progress_and_reply(auth_client: TestClient, fake_llm):
    fake_llm.add(
        "interpreter",
        Interpretation(
            kind="new_task",
            confidence=0.9,
            objective="EV deck",
            output_spec=OutputSpec(format=OutputFormat.pptx),
            research=ResearchNeed(depth="none"),
        ),
    )
    fake_llm.add("deck_planner", sample_deck())
    sid = auth_client.post("/api/sessions", json={}).json()["id"]
    res = auth_client.post(f"/api/sessions/{sid}/jobs", json={"content": "EV charging board deck"})
    assert res.status_code == 202
    job_id = res.json()["job_id"]
    deadline = time.time() + 60
    job = {}
    while time.time() < deadline:
        job = auth_client.get(f"/api/sessions/{sid}/jobs/{job_id}").json()
        if job["status"] != "running":
            break
        time.sleep(0.2)
    assert job["status"] == "done", job
    stages = [s["stage"] for s in job["steps"]]
    assert stages[0] == "understand" and "render" in stages
    artifact = job["result"]["artifact"]
    assert artifact["format"] == "pptx" and artifact["units"] >= 13 and artifact["preview_urls"]
    png = auth_client.get(artifact["preview_urls"][0])
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    # the session list shows the auto-titled chat; the reply keeps its download card after reload
    sessions = auth_client.get("/api/sessions").json()
    assert sessions[0]["title"] == "EV charging board deck"
    messages = auth_client.get(f"/api/sessions/{sid}").json()["messages"]
    assert messages[-1]["artifact_ref"]["download_url"] == artifact["download_url"]
