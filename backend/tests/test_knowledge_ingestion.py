from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401
from app.knowledge.ingestion import KnowledgeIngestionService
from app.knowledge.storage import KnowledgeFileStorage
from deerflow.knowledge.chunking.markdown import MarkdownChunker
from deerflow.knowledge.config import ChunkingConfig
from deerflow.knowledge.manager import KnowledgeManager
from deerflow.knowledge.parsing.markitdown import MarkItDownParser
from deerflow.knowledge.retrieval.local import LocalHybridIndex
from deerflow.persistence.base import Base
from deerflow.persistence.knowledge import KnowledgeRepository


class FakeEmbeddingProvider:
    @staticmethod
    def _embed(text: str) -> list[float]:
        lowered = text.lower()
        return [float(lowered.count("alpha")), float(lowered.count("billing")), 1.0]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


@pytest_asyncio.fixture
async def ingestion_dependencies(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'metadata.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = KnowledgeRepository(async_sessionmaker(engine, expire_on_commit=False))
    storage = KnowledgeFileStorage(tmp_path / "files")
    index = LocalHybridIndex(tmp_path / "index.sqlite", embedding_model="fake-v1")
    embedder = FakeEmbeddingProvider()
    manager = KnowledgeManager(index=index, embedding=embedder, repository=repository)
    service = KnowledgeIngestionService(
        repository=repository,
        storage=storage,
        parser=MarkItDownParser(),
        chunker=MarkdownChunker(ChunkingConfig(target_tokens=20, overlap_tokens=3, max_tokens=30), token_counter=lambda text: len(text.split())),
        embedding=embedder,
        index=index,
    )
    try:
        yield repository, storage, manager, service
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingestion_job_indexes_document_and_manager_searches_it(ingestion_dependencies) -> None:
    repository, storage, manager, service = ingestion_dependencies
    await repository.create_knowledge_base(knowledge_base_id="kb-1", user_id="user-1", name="Handbook")
    relative_path, size_bytes, digest = await storage.write_source(
        user_id="user-1",
        knowledge_base_id="kb-1",
        document_id="doc-1",
        filename="handbook.md",
        content=b"# Handbook\n\nAlpha deployment uses the blue environment.\n\n## Billing\n\nRefunds take five days.",
    )
    await repository.create_document(
        document_id="doc-1",
        knowledge_base_id="kb-1",
        user_id="user-1",
        filename="handbook.md",
        media_type="text/markdown",
        size_bytes=size_bytes,
        content_sha256=digest,
        source_path=relative_path,
    )
    await repository.create_ingestion_job(job_id="job-1", document_id="doc-1", user_id="user-1", operation="index", max_attempts=3)
    job = (await repository.claim_ingestion_jobs(now=datetime.now(UTC), lease_owner="worker-1", lease_seconds=60, limit=1))[0]

    await service.process_claimed_job(job, lease_owner="worker-1")

    document = await repository.get_document("doc-1", user_id="user-1")
    assert document is not None
    assert document["status"] == "ready"
    assert document["chunk_count"] >= 1
    assert (await repository.get_ingestion_job("job-1", user_id="user-1"))["status"] == "succeeded"

    hits = await manager.search(user_id="user-1", text="alpha deployment", knowledge_base_ids=["kb-1"], top_k=3)
    assert hits
    assert hits[0].document_id == "doc-1"
    assert "Alpha deployment" in hits[0].content


@pytest.mark.asyncio
async def test_manager_resolves_thread_bindings_without_accepting_arbitrary_ids(ingestion_dependencies) -> None:
    repository, _storage, manager, _service = ingestion_dependencies
    await repository.create_knowledge_base(knowledge_base_id="kb-1", user_id="user-1", name="Allowed")
    await repository.set_bindings(user_id="user-1", scope_type="thread", scope_id="thread-1", strategy="replace", knowledge_base_ids=["kb-1"])

    assert await manager.resolve_knowledge_base_ids(user_id="user-1", thread_id="thread-1", agent_id=None) == ["kb-1"]
    assert await manager.resolve_knowledge_base_ids(user_id="user-2", thread_id="thread-1", agent_id=None) == []


@pytest.mark.asyncio
async def test_manager_stops_returning_a_document_as_soon_as_deletion_starts(
    ingestion_dependencies,
) -> None:
    repository, storage, manager, service = ingestion_dependencies
    await repository.create_knowledge_base(knowledge_base_id="kb-1", user_id="user-1", name="Docs")
    relative_path, size_bytes, digest = await storage.write_source(
        user_id="user-1",
        knowledge_base_id="kb-1",
        document_id="doc-1",
        filename="guide.md",
        content=b"Alpha deletion policy.",
    )
    await repository.create_document(
        document_id="doc-1",
        knowledge_base_id="kb-1",
        user_id="user-1",
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=size_bytes,
        content_sha256=digest,
        source_path=relative_path,
    )
    await repository.create_ingestion_job(
        job_id="job-index",
        document_id="doc-1",
        user_id="user-1",
        operation="index",
        max_attempts=3,
    )
    job = (
        await repository.claim_ingestion_jobs(
            now=datetime.now(UTC),
            lease_owner="worker-1",
            lease_seconds=60,
            limit=1,
        )
    )[0]
    await service.process_claimed_job(job, lease_owner="worker-1")
    assert await manager.search(
        user_id="user-1",
        text="alpha deletion",
        knowledge_base_ids=["kb-1"],
    )

    await repository.update_document("doc-1", user_id="user-1", status="deleting")

    assert (
        await manager.search(
            user_id="user-1",
            text="alpha deletion",
            knowledge_base_ids=["kb-1"],
        )
        == []
    )


@pytest.mark.asyncio
async def test_failed_deletion_job_is_retried(ingestion_dependencies, monkeypatch) -> None:
    repository, storage, _manager, service = ingestion_dependencies
    await repository.create_knowledge_base(knowledge_base_id="kb-1", user_id="user-1", name="Docs")
    relative_path, size_bytes, digest = await storage.write_source(
        user_id="user-1",
        knowledge_base_id="kb-1",
        document_id="doc-1",
        filename="guide.md",
        content=b"Alpha",
    )
    await repository.create_document(
        document_id="doc-1",
        knowledge_base_id="kb-1",
        user_id="user-1",
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=size_bytes,
        content_sha256=digest,
        source_path=relative_path,
    )
    await repository.update_document("doc-1", user_id="user-1", status="deleting")
    await repository.create_ingestion_job(
        job_id="job-delete",
        document_id="doc-1",
        user_id="user-1",
        operation="delete",
        max_attempts=3,
    )

    async def fail_delete(*, user_id: str, document_id: str) -> None:
        raise RuntimeError(f"index unavailable for {user_id}/{document_id}")

    monkeypatch.setattr(service._index, "delete_document", fail_delete)
    job = (
        await repository.claim_ingestion_jobs(
            now=datetime.now(UTC),
            lease_owner="worker-1",
            lease_seconds=60,
            limit=1,
        )
    )[0]

    await service.process_claimed_job(job, lease_owner="worker-1")

    failed = await repository.get_ingestion_job("job-delete", user_id="user-1")
    assert failed is not None
    assert failed["status"] == "queued"
    assert failed["next_attempt_at"] is not None


@pytest.mark.asyncio
async def test_storage_rejects_unsafe_server_identifiers(tmp_path: Path) -> None:
    storage = KnowledgeFileStorage(tmp_path)

    with pytest.raises(ValueError):
        await storage.write_source(
            user_id="user-1",
            knowledge_base_id="../kb",
            document_id="doc-1",
            filename="safe.md",
            content=b"text",
        )


@pytest.mark.asyncio
async def test_storage_normalizes_external_user_ids(tmp_path: Path) -> None:
    storage = KnowledgeFileStorage(tmp_path)

    relative_path, _size, _digest = await storage.write_source(
        user_id="alice@example.com",
        knowledge_base_id="kb-1",
        document_id="doc-1",
        filename="guide.md",
        content=b"text",
    )

    assert storage.resolve_source(user_id="alice@example.com", relative_path=relative_path).read_text() == "text"
