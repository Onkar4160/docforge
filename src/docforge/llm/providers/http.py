"""Shared HTTP error mapping for REST model backends."""

from __future__ import annotations

import re

import httpx

from docforge.core.errors import (
    LLMError,
    LLMModelUnavailable,
    LLMRateLimited,
    LLMSchemaRejected,
    LLMTransient,
)

_DELAY = re.compile(r"^(\d+(?:\.\d+)?)s$")


def _quota_details(resp: httpx.Response) -> dict:
    """Retry delay and whether the exhausted quota is a daily one (Google RPC error details)."""
    out: dict = {}
    header = resp.headers.get("retry-after")
    if header and header.isdigit():
        out["retry_after_s"] = float(header)
    try:
        details = (resp.json().get("error") or {}).get("details") or []
    except (ValueError, AttributeError):
        return out
    for d in details:
        kind = d.get("@type", "")
        if kind.endswith("RetryInfo"):
            m = _DELAY.match(str(d.get("retryDelay", "")))
            if m:
                out["retry_after_s"] = float(m.group(1))
        elif kind.endswith("QuotaFailure"):
            ids = " ".join(v.get("quotaId", "") for v in d.get("violations") or [])
            out["daily"] = "PerDay" in ids
    return out


def map_http_error(resp: httpx.Response, provider: str, *, schema_sent: bool = False) -> None:
    if resp.is_success:
        return
    snippet = resp.text[:300]
    details = {"provider": provider, "status": resp.status_code}
    if resp.status_code == 429:
        raise LLMRateLimited(f"{provider}: rate limited", details={**details, **_quota_details(resp)})
    if resp.status_code == 404:
        raise LLMModelUnavailable(f"{provider}: model not available", details=details)
    if resp.status_code >= 500 or resp.status_code == 408:
        raise LLMTransient(f"{provider}: server error {resp.status_code}", details=details)
    if resp.status_code == 401:
        raise LLMError(f"{provider}: authentication failed; check the API key", details=details)
    if resp.status_code == 403:
        msg = resp.text
        try:
            err_data = resp.json()
            if isinstance(err_data, dict) and "error" in err_data:
                msg = err_data["error"].get("message", msg)
        except Exception:
            pass
        if "billing" in msg.lower() or "free tier" in msg.lower():
            raise LLMError(f"{provider}: billing required ({msg})", details={**details, "message": msg})
        raise LLMError(
            f"{provider}: authentication failed or access forbidden; check the API key ({msg})",
            details={**details, "message": msg},
        )
    if resp.status_code == 400 and schema_sent:
        raise LLMSchemaRejected(f"{provider}: native schema rejected: {snippet}", details=details)
    raise LLMError(f"{provider}: request failed ({resp.status_code}): {snippet}", details=details)


async def post_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    provider: str,
    json: dict,
    headers: dict[str, str] | None = None,
    schema_sent: bool = False,
) -> dict:
    try:
        resp = await client.post(url, json=json, headers=headers)
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise LLMTransient(f"{provider}: connection failed: {exc.__class__.__name__}") from exc
    map_http_error(resp, provider, schema_sent=schema_sent)
    try:
        return resp.json()
    except ValueError as exc:
        raise LLMTransient(f"{provider}: non-JSON response") from exc
