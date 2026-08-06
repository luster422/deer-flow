from __future__ import annotations

from typing import Protocol

from deerflow.knowledge.config import RetrievalConfig
from deerflow.knowledge.ports import EmbeddingProvider, RetrievalIndex
from deerflow.knowledge.types import SearchHit, SearchQuery

_knowledge_manager: KnowledgeManager | None = None


class BindingRepository(Protocol):
    async def resolve_bindings(self, *, user_id: str, agent_id: str | None, thread_id: str | None) -> list[str]: ...

    async def list_searchable_document_ids(
        self,
        *,
        user_id: str,
        knowledge_base_ids: list[str],
        document_ids: list[str] | None = None,
    ) -> list[str]: ...


class KnowledgeManager:
    """Harness-level retrieval use case shared by HTTP and agent tools."""

    def __init__(
        self,
        *,
        index: RetrievalIndex,
        embedding: EmbeddingProvider,
        repository: BindingRepository | None = None,
        retrieval: RetrievalConfig | None = None,
    ) -> None:
        self._index = index
        self._embedding = embedding
        self._repository = repository
        self._retrieval = retrieval or RetrievalConfig()

    async def resolve_knowledge_base_ids(self, *, user_id: str, thread_id: str | None, agent_id: str | None) -> list[str]:
        if self._repository is None:
            return []
        return await self._repository.resolve_bindings(user_id=user_id, agent_id=agent_id, thread_id=thread_id)

    async def search(
        self,
        *,
        user_id: str,
        text: str,
        knowledge_base_ids: list[str],
        top_k: int | None = None,
        document_ids: list[str] | None = None,
        vector_candidate_k: int | None = None,
        text_candidate_k: int | None = None,
        rrf_k: int | None = None,
        mmr_lambda: float | None = None,
    ) -> list[SearchHit]:
        if not text.strip() or not knowledge_base_ids:
            return []
        if self._repository is not None:
            document_ids = await self._repository.list_searchable_document_ids(
                user_id=user_id,
                knowledge_base_ids=knowledge_base_ids,
                document_ids=document_ids,
            )
            if not document_ids:
                return []
        query_embedding = await self._embedding.embed_query(text)
        return await self._index.search(
            SearchQuery(
                user_id=user_id,
                knowledge_base_ids=tuple(knowledge_base_ids),
                document_ids=tuple(document_ids) if document_ids is not None else None,
                text=text,
                embedding=query_embedding,
                top_k=top_k or self._retrieval.top_k,
                vector_candidate_k=(vector_candidate_k or self._retrieval.vector_candidate_k),
                text_candidate_k=(text_candidate_k or self._retrieval.text_candidate_k),
                rrf_k=rrf_k or self._retrieval.rrf_k,
                mmr_lambda=(mmr_lambda if mmr_lambda is not None else self._retrieval.mmr_lambda),
            )
        )

    async def search_bound(
        self,
        *,
        user_id: str,
        text: str,
        thread_id: str | None,
        agent_id: str | None,
        top_k: int | None = None,
        document_ids: list[str] | None = None,
    ) -> list[SearchHit]:
        knowledge_base_ids = await self.resolve_knowledge_base_ids(user_id=user_id, thread_id=thread_id, agent_id=agent_id)
        return await self.search(
            user_id=user_id,
            text=text,
            knowledge_base_ids=knowledge_base_ids,
            top_k=top_k,
            document_ids=document_ids,
        )


def set_knowledge_manager(manager: KnowledgeManager | None) -> None:
    global _knowledge_manager
    _knowledge_manager = manager


def get_knowledge_manager() -> KnowledgeManager | None:
    return _knowledge_manager
