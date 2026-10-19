"""Composition root: wires settings, storage, LLM, search and retrieval once per process."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, text
from sqlalchemy.orm import sessionmaker

from docforge.core.config import Settings
from docforge.llm import LLMClient, build_embedder, build_llm_client
from docforge.llm.providers.base import EmbeddingProvider
from docforge.media.images import ImageProvider, build_image_provider
from docforge.research.academic import build_academic_providers
from docforge.research.search import SearchProvider, build_search_provider
from docforge.retrieval.index import KnowledgeIndex
from docforge.retrieval.vectorstore import LocalVectorStore, PineconeVectorStore, VectorStore
from docforge.storage import BlobStore, Repositories, init_db, make_engine


def build_vector_store(settings: Settings, sessions: sessionmaker) -> VectorStore:
    if settings.resolved_vector_store == "pinecone" and settings.pinecone_api_key:
        return PineconeVectorStore(
            settings.pinecone_api_key, settings.pinecone_index, api_version=settings.pinecone_api_version
        )
    return LocalVectorStore(sessions)


@dataclass
class Container:
    settings: Settings
    engine: Engine
    repos: Repositories
    blobs: BlobStore
    llm: LLMClient
    search: SearchProvider
    academic: list[SearchProvider]
    embedder: EmbeddingProvider
    vectors: VectorStore
    knowledge: KnowledgeIndex
    images: ImageProvider | None = None

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        llm: LLMClient | None = None,
        search: SearchProvider | None = None,
        academic: list[SearchProvider] | None = None,
        embedder: EmbeddingProvider | None = None,
        vectors: VectorStore | None = None,
        images: ImageProvider | None = None,
    ) -> Container:
        settings.ensure_dirs()
        engine = make_engine(settings.database_url)
        sessions = init_db(engine)
        embedder = embedder or build_embedder(settings)
        vectors = vectors or build_vector_store(settings, sessions)
        return cls(
            settings=settings,
            engine=engine,
            repos=Repositories(sessions),
            blobs=BlobStore(settings.blob_dir),
            llm=llm or build_llm_client(settings),
            search=search or build_search_provider(settings),
            academic=build_academic_providers(settings) if academic is None else academic,
            embedder=embedder,
            vectors=vectors,
            knowledge=KnowledgeIndex(embedder, vectors),
            images=images if images is not None else build_image_provider(settings),
        )

    def db_ok(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def aclose(self) -> None:
        for closable in (self.llm, self.search, *self.academic, self.embedder, self.vectors):
            await closable.aclose()
        if self.images is not None:
            await self.images.aclose()
        self.engine.dispose()
