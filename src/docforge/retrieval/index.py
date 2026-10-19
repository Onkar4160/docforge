"""Chunk, embed and search user sources (FR-RES-4). Backend-agnostic over embedder + vector store."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from docforge.llm.providers.base import EmbeddingProvider
from docforge.retrieval.vectorstore import VectorRecord, VectorStore

_PARA = re.compile(r"\n\s*\n")


def chunk_text(text: str, *, max_chars: int = 1500, overlap: int = 200) -> list[str]:
    """Paragraph-aware chunks of at most ``max_chars`` with character overlap between chunks."""
    paragraphs = [p.strip() for p in _PARA.split(text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        while len(para) > max_chars:  # hard-split oversized paragraphs
            head, para = para[:max_chars], para[max_chars - overlap :]
            if current:
                chunks.append(current)
                current = ""
            chunks.append(head)
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            current = f"{tail}\n\n{para}" if tail else para
    if current:
        chunks.append(current)
    return chunks


@dataclass
class RetrievedChunk:
    chunk_id: str
    source_id: str
    text: str
    score: float
    locator: str


class KnowledgeIndex:
    def __init__(self, embedder: EmbeddingProvider, store: VectorStore) -> None:
        self.embedder = embedder
        self.store = store

    async def index_document(self, namespace: str, source_id: str, text: str, *, title: str = "") -> int:
        chunks = chunk_text(text)
        if not chunks:
            return 0
        vectors = await self.embedder.embed(chunks, task="document")
        records = [
            VectorRecord(
                id=f"{source_id}-{i:04d}-{hashlib.sha1(c.encode()).hexdigest()[:8]}",
                values=v,
                metadata={"source_id": source_id, "chunk": i, "title": title, "text": c[:3500]},
            )
            for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
        ]
        return await self.store.upsert(namespace, records)

    async def search(
        self, namespace: str, query: str, *, top_k: int = 6, source_ids: list[str] | None = None
    ) -> list[RetrievedChunk]:
        [vector] = await self.embedder.embed([query], task="query")
        flt = {"source_id": {"$in": source_ids}} if source_ids else None
        matches = await self.store.query(namespace, vector, top_k=top_k, filter=flt)
        return [
            RetrievedChunk(
                chunk_id=m.id,
                source_id=str(m.metadata.get("source_id", "")),
                text=str(m.metadata.get("text", "")),
                score=m.score,
                locator=f"chunk {m.metadata.get('chunk', '?')}",
            )
            for m in matches
        ]
