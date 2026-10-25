"""Vector stores behind one interface (ADR-014): Pinecone (REST) or a local SQLite-backed store."""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import sessionmaker

from docforge.core.errors import StorageError
from docforge.storage.db import Record

PINECONE_CONTROL_URL = "https://api.pinecone.io"
_UPSERT_BATCH = 100


@dataclass
class VectorRecord:
    id: str
    values: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class VectorMatch:
    id: str
    score: float
    metadata: dict[str, Any]


class VectorStore(ABC):
    name: str

    @abstractmethod
    async def upsert(self, namespace: str, records: list[VectorRecord]) -> int: ...

    @abstractmethod
    async def query(
        self, namespace: str, vector: list[float], top_k: int = 8, filter: dict[str, Any] | None = None
    ) -> list[VectorMatch]: ...

    @abstractmethod
    async def delete(self, namespace: str, ids: list[str] | None = None) -> None:
        """Delete given ids, or the whole namespace when ``ids`` is None."""

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        pass


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _matches_filter(metadata: dict[str, Any], flt: dict[str, Any] | None) -> bool:
    """Supports equality and ``{"$eq"|"$in": ...}`` — the subset the app uses on both backends."""
    if not flt:
        return True
    for key, cond in flt.items():
        value = metadata.get(key)
        if isinstance(cond, dict):
            if "$eq" in cond and value != cond["$eq"]:
                return False
            if "$in" in cond and value not in cond["$in"]:
                return False
        elif value != cond:
            return False
    return True


class _StoredVector(BaseModel):
    values: list[float]
    metadata: dict[str, Any] = {}


class LocalVectorStore(VectorStore):
    """Exact cosine search over vectors kept in the app database. Fine for thousands of chunks."""

    name = "local"
    _kind = "vector"

    def __init__(self, sessions: sessionmaker) -> None:
        self._sessions = sessions

    @staticmethod
    def _key(namespace: str, vid: str) -> str:
        return f"{namespace}::{vid}"

    async def upsert(self, namespace: str, records: list[VectorRecord]) -> int:
        with self._sessions.begin() as s:
            for r in records:
                key = self._key(namespace, r.id)
                data = _StoredVector(values=r.values, metadata=r.metadata).model_dump()
                row = s.get(Record, (self._kind, key))
                if row is None:
                    s.add(Record(kind=self._kind, id=key, parent_id=namespace, data=data))
                else:
                    row.data = data
        return len(records)

    async def query(
        self, namespace: str, vector: list[float], top_k: int = 8, filter: dict[str, Any] | None = None
    ) -> list[VectorMatch]:
        with self._sessions() as s:
            rows = s.scalars(
                select(Record).where(Record.kind == self._kind, Record.parent_id == namespace)
            ).all()
            scored = []
            for row in rows:
                stored = _StoredVector.model_validate(row.data)
                if _matches_filter(stored.metadata, filter):
                    vid = row.id.split("::", 1)[1]
                    scored.append(VectorMatch(vid, _cosine(vector, stored.values), stored.metadata))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored[:top_k]

    async def delete(self, namespace: str, ids: list[str] | None = None) -> None:
        with self._sessions.begin() as s:
            stmt = delete(Record).where(Record.kind == self._kind, Record.parent_id == namespace)
            if ids is not None:
                stmt = stmt.where(Record.id.in_([self._key(namespace, i) for i in ids]))
            s.execute(stmt)


class PineconeVectorStore(VectorStore):
    """Pinecone data plane over REST. The index host is discovered once via the control plane."""

    name = "pinecone"

    def __init__(
        self,
        api_key: str,
        index: str,
        *,
        api_version: str,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
        host: str | None = None,
    ) -> None:
        self._headers = {
            "Api-Key": api_key,
            "X-Pinecone-Api-Version": api_version,
            "Content-Type": "application/json",
        }
        self._index = index
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._host = host

    async def _request(self, method: str, url: str, json: dict | None = None) -> dict:
        try:
            resp = await self._client.request(method, url, json=json, headers=self._headers)
        except httpx.HTTPError as exc:
            raise StorageError(f"pinecone request failed: {exc.__class__.__name__}") from exc
        if resp.status_code == 401:
            raise StorageError("pinecone rejected the API key (PINECONE_API_KEY)")
        if resp.status_code == 404 and url.startswith(PINECONE_CONTROL_URL):
            raise StorageError(f"pinecone index '{self._index}' not found (PINECONE_INDEX)")
        if not resp.is_success:
            raise StorageError(f"pinecone error {resp.status_code}: {resp.text[:200]}")
        return resp.json() if resp.content else {}

    async def host(self) -> str:
        if self._host is None:
            info = await self._request("GET", f"{PINECONE_CONTROL_URL}/indexes/{self._index}")
            host = info.get("host")
            if not host:
                raise StorageError("pinecone describe-index returned no host")
            self._host = host if host.startswith("http") else f"https://{host}"
        return self._host

    async def upsert(self, namespace: str, records: list[VectorRecord]) -> int:
        base = await self.host()
        total = 0
        for start in range(0, len(records), _UPSERT_BATCH):
            batch = records[start : start + _UPSERT_BATCH]
            body = {
                "namespace": namespace,
                "vectors": [{"id": r.id, "values": r.values, "metadata": r.metadata} for r in batch],
            }
            data = await self._request("POST", f"{base}/vectors/upsert", json=body)
            total += int(data.get("upsertedCount", len(batch)))
        return total

    async def query(
        self, namespace: str, vector: list[float], top_k: int = 8, filter: dict[str, Any] | None = None
    ) -> list[VectorMatch]:
        body: dict[str, Any] = {
            "namespace": namespace,
            "vector": vector,
            "topK": top_k,
            "includeMetadata": True,
        }
        if filter:
            body["filter"] = filter
        data = await self._request("POST", f"{await self.host()}/query", json=body)
        return [
            VectorMatch(m["id"], float(m.get("score", 0.0)), m.get("metadata") or {})
            for m in data.get("matches", [])
        ]

    async def delete(self, namespace: str, ids: list[str] | None = None) -> None:
        body: dict[str, Any] = {"namespace": namespace}
        if ids is None:
            body["deleteAll"] = True
        else:
            body["ids"] = ids
        await self._request("POST", f"{await self.host()}/vectors/delete", json=body)

    async def aclose(self) -> None:
        await self._client.aclose()
