"""Deterministic, offline feature-hashing embeddings.

Lower quality than a neural model, but needs no network or key: used for tests, offline mode and
as a last-resort fallback so retrieval still works.
"""

from __future__ import annotations

import hashlib
import re

from docforge.llm.providers.base import EmbeddingProvider, EmbedTask, l2_normalize

_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbeddingProvider(EmbeddingProvider):
    name = "hash"

    def __init__(self, dimensions: int = 768) -> None:
        self.dimensions = dimensions

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        tokens = _TOKEN.findall(text.lower())
        grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:], strict=False)]
        for gram in grams:
            digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[idx] += sign
        return l2_normalize(vec)

    async def embed(self, texts: list[str], task: EmbedTask = "document") -> list[list[float]]:
        return [self._vector(t) for t in texts]
