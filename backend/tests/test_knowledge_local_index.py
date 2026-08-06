from __future__ import annotations

from pathlib import Path

import pytest

from deerflow.knowledge.retrieval.local import DimensionMismatchError, LocalHybridIndex
from deerflow.knowledge.types import IndexedChunk, SearchQuery


def _chunk(
    chunk_id: str,
    *,
    user_id: str,
    knowledge_base_id: str,
    document_id: str,
    content: str,
    embedding: list[float],
    chunk_index: int = 0,
) -> IndexedChunk:
    return IndexedChunk(
        id=chunk_id,
        user_id=user_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        version=1,
        chunk_index=chunk_index,
        content=content,
        embedding=embedding,
        metadata={"filename": f"{document_id}.md"},
        token_count=len(content.split()),
    )


@pytest.mark.asyncio
async def test_local_index_combines_text_and_vector_recall(tmp_path: Path) -> None:
    index = LocalHybridIndex(tmp_path / "knowledge.sqlite", embedding_model="fake-v1")
    await index.upsert(
        [
            _chunk(
                "chunk-alpha",
                user_id="user-1",
                knowledge_base_id="kb-1",
                document_id="doc-alpha",
                content="alpha deployment handbook",
                embedding=[1.0, 0.0, 0.0],
            ),
            _chunk(
                "chunk-semantic",
                user_id="user-1",
                knowledge_base_id="kb-1",
                document_id="doc-semantic",
                content="release procedure and rollback",
                embedding=[0.95, 0.05, 0.0],
            ),
            _chunk(
                "chunk-other",
                user_id="user-1",
                knowledge_base_id="kb-2",
                document_id="doc-other",
                content="alpha from another knowledge base",
                embedding=[1.0, 0.0, 0.0],
            ),
        ]
    )

    hits = await index.search(
        SearchQuery(
            user_id="user-1",
            knowledge_base_ids=("kb-1",),
            text="alpha",
            embedding=[1.0, 0.0, 0.0],
            top_k=2,
            vector_candidate_k=5,
            text_candidate_k=5,
        )
    )

    assert [hit.id for hit in hits] == ["chunk-alpha", "chunk-semantic"]
    assert hits[0].text_score is not None
    assert hits[0].vector_score == pytest.approx(1.0)
    assert hits[0].score > 0


@pytest.mark.asyncio
async def test_local_index_enforces_user_and_document_filters(tmp_path: Path) -> None:
    index = LocalHybridIndex(tmp_path / "knowledge.sqlite", embedding_model="fake-v1")
    await index.upsert(
        [
            _chunk("u1-a", user_id="user-1", knowledge_base_id="kb-1", document_id="doc-a", content="shared secret alpha", embedding=[1.0, 0.0]),
            _chunk("u1-b", user_id="user-1", knowledge_base_id="kb-1", document_id="doc-b", content="shared secret beta", embedding=[0.9, 0.1]),
            _chunk("u2-a", user_id="user-2", knowledge_base_id="kb-1", document_id="doc-a", content="shared secret private", embedding=[1.0, 0.0]),
        ]
    )

    hits = await index.search(
        SearchQuery(
            user_id="user-1",
            knowledge_base_ids=("kb-1",),
            document_ids=("doc-b",),
            text="shared secret",
            embedding=[1.0, 0.0],
            top_k=5,
        )
    )

    assert [hit.id for hit in hits] == ["u1-b"]


@pytest.mark.asyncio
async def test_local_index_delete_document_is_owner_scoped(tmp_path: Path) -> None:
    index = LocalHybridIndex(tmp_path / "knowledge.sqlite", embedding_model="fake-v1")
    await index.upsert(
        [
            _chunk("u1", user_id="user-1", knowledge_base_id="kb-1", document_id="doc-1", content="alpha", embedding=[1.0, 0.0]),
            _chunk("u2", user_id="user-2", knowledge_base_id="kb-1", document_id="doc-1", content="alpha", embedding=[1.0, 0.0]),
        ]
    )

    await index.delete_document(user_id="user-1", document_id="doc-1")

    user_1_hits = await index.search(SearchQuery(user_id="user-1", knowledge_base_ids=("kb-1",), text="alpha", embedding=[1.0, 0.0]))
    user_2_hits = await index.search(SearchQuery(user_id="user-2", knowledge_base_ids=("kb-1",), text="alpha", embedding=[1.0, 0.0]))
    assert user_1_hits == []
    assert [hit.id for hit in user_2_hits] == ["u2"]


@pytest.mark.asyncio
async def test_local_index_rejects_embedding_dimension_drift(tmp_path: Path) -> None:
    index = LocalHybridIndex(tmp_path / "knowledge.sqlite", embedding_model="fake-v1")
    await index.upsert([_chunk("first", user_id="user-1", knowledge_base_id="kb-1", document_id="doc-1", content="alpha", embedding=[1.0, 0.0])])

    with pytest.raises(DimensionMismatchError):
        await index.upsert([_chunk("second", user_id="user-1", knowledge_base_id="kb-1", document_id="doc-2", content="beta", embedding=[1.0, 0.0, 0.0])])

    with pytest.raises(DimensionMismatchError):
        await index.search(SearchQuery(user_id="user-1", knowledge_base_ids=("kb-1",), text="alpha", embedding=[1.0, 0.0, 0.0]))


@pytest.mark.asyncio
async def test_local_index_reports_manifest_status(tmp_path: Path) -> None:
    index = LocalHybridIndex(tmp_path / "knowledge.sqlite", embedding_model="fake-v1")
    await index.upsert([_chunk("first", user_id="user-1", knowledge_base_id="kb-1", document_id="doc-1", content="alpha", embedding=[1.0, 0.0])])

    status = await index.status()

    assert status.ready is True
    assert status.embedding_model == "fake-v1"
    assert status.embedding_dimension == 2
    assert status.chunk_count == 1
