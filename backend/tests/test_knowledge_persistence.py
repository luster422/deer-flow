from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401
from deerflow.persistence.base import Base
from deerflow.persistence.knowledge import KnowledgeRepository


@pytest_asyncio.fixture
async def knowledge_repository(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'knowledge.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = KnowledgeRepository(async_sessionmaker(engine, expire_on_commit=False))
    try:
        yield repository
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_knowledge_base_crud_is_owner_scoped(knowledge_repository: KnowledgeRepository) -> None:
    created = await knowledge_repository.create_knowledge_base(
        knowledge_base_id="kb-1",
        user_id="user-1",
        name="Engineering",
        description="Internal engineering docs",
    )

    assert created["id"] == "kb-1"
    assert created["document_count"] == 0
    assert await knowledge_repository.get_knowledge_base("kb-1", user_id="user-2") is None
    assert await knowledge_repository.list_knowledge_bases(user_id="user-2") == []
    assert [item["id"] for item in await knowledge_repository.list_knowledge_bases(user_id="user-1")] == ["kb-1"]

    updated = await knowledge_repository.update_knowledge_base("kb-1", user_id="user-1", name="Platform")
    assert updated is not None
    assert updated["name"] == "Platform"
    assert await knowledge_repository.update_knowledge_base("kb-1", user_id="user-2", name="Leaked") is None


@pytest.mark.asyncio
async def test_document_and_job_lifecycle_is_idempotent_and_leased(knowledge_repository: KnowledgeRepository) -> None:
    await knowledge_repository.create_knowledge_base(knowledge_base_id="kb-1", user_id="user-1", name="Docs")
    document = await knowledge_repository.create_document(
        document_id="doc-1",
        knowledge_base_id="kb-1",
        user_id="user-1",
        filename="guide.md",
        media_type="text/markdown",
        size_bytes=12,
        content_sha256="abc123",
        source_path="kb-1/doc-1/source/guide.md",
    )
    duplicate = await knowledge_repository.get_document_by_hash(
        knowledge_base_id="kb-1",
        user_id="user-1",
        content_sha256="abc123",
    )
    assert duplicate == document
    assert await knowledge_repository.get_document("doc-1", user_id="user-2") is None

    await knowledge_repository.create_ingestion_job(
        job_id="job-1",
        document_id="doc-1",
        user_id="user-1",
        operation="index",
        max_attempts=3,
    )
    now = datetime.now(UTC)
    claimed = await knowledge_repository.claim_ingestion_jobs(now=now, lease_owner="worker-a", lease_seconds=60, limit=10)
    assert [job["id"] for job in claimed] == ["job-1"]
    assert claimed[0]["status"] == "running"
    assert claimed[0]["attempts"] == 1
    assert await knowledge_repository.claim_ingestion_jobs(now=now + timedelta(seconds=30), lease_owner="worker-b", lease_seconds=60, limit=10) == []

    reclaimed = await knowledge_repository.claim_ingestion_jobs(now=now + timedelta(seconds=61), lease_owner="worker-b", lease_seconds=60, limit=10)
    assert [job["id"] for job in reclaimed] == ["job-1"]
    assert reclaimed[0]["attempts"] == 2

    await knowledge_repository.complete_ingestion_job("job-1", lease_owner="worker-b")
    assert (await knowledge_repository.get_ingestion_job("job-1", user_id="user-1"))["status"] == "succeeded"


@pytest.mark.asyncio
async def test_binding_scope_preserves_explicit_empty_replace(knowledge_repository: KnowledgeRepository) -> None:
    await knowledge_repository.create_knowledge_base(knowledge_base_id="kb-agent", user_id="user-1", name="Agent default")
    await knowledge_repository.create_knowledge_base(knowledge_base_id="kb-thread", user_id="user-1", name="Thread extra")
    await knowledge_repository.set_bindings(
        user_id="user-1",
        scope_type="agent",
        scope_id="researcher",
        strategy="replace",
        knowledge_base_ids=["kb-agent"],
    )

    inherited = await knowledge_repository.resolve_bindings(user_id="user-1", agent_id="researcher", thread_id="thread-1")
    assert inherited == ["kb-agent"]

    await knowledge_repository.set_bindings(
        user_id="user-1",
        scope_type="thread",
        scope_id="thread-1",
        strategy="replace",
        knowledge_base_ids=[],
    )
    thread_scope = await knowledge_repository.get_bindings(user_id="user-1", scope_type="thread", scope_id="thread-1")
    assert thread_scope == {"strategy": "replace", "knowledge_base_ids": []}
    assert await knowledge_repository.resolve_bindings(user_id="user-1", agent_id="researcher", thread_id="thread-1") == []

    await knowledge_repository.set_bindings(
        user_id="user-1",
        scope_type="thread",
        scope_id="thread-1",
        strategy="union",
        knowledge_base_ids=["kb-thread"],
    )
    assert await knowledge_repository.resolve_bindings(user_id="user-1", agent_id="researcher", thread_id="thread-1") == ["kb-agent", "kb-thread"]


@pytest.mark.asyncio
async def test_set_bindings_rejects_knowledge_base_owned_by_another_user(knowledge_repository: KnowledgeRepository) -> None:
    await knowledge_repository.create_knowledge_base(knowledge_base_id="kb-private", user_id="user-2", name="Private")

    with pytest.raises(ValueError, match="not owned"):
        await knowledge_repository.set_bindings(
            user_id="user-1",
            scope_type="thread",
            scope_id="thread-1",
            strategy="replace",
            knowledge_base_ids=["kb-private"],
        )


@pytest.mark.asyncio
async def test_searchable_documents_require_ready_document_and_active_base(
    knowledge_repository: KnowledgeRepository,
) -> None:
    await knowledge_repository.create_knowledge_base(knowledge_base_id="kb-active", user_id="user-1", name="Active")
    await knowledge_repository.create_knowledge_base(knowledge_base_id="kb-deleting", user_id="user-1", name="Deleting")
    for document_id, knowledge_base_id in [
        ("doc-ready", "kb-active"),
        ("doc-queued", "kb-active"),
        ("doc-stale", "kb-deleting"),
    ]:
        await knowledge_repository.create_document(
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            user_id="user-1",
            filename=f"{document_id}.md",
            media_type="text/markdown",
            size_bytes=4,
            content_sha256=document_id,
            source_path=f"{knowledge_base_id}/{document_id}.md",
        )
    await knowledge_repository.update_document("doc-ready", user_id="user-1", status="ready")
    await knowledge_repository.update_document("doc-stale", user_id="user-1", status="ready")
    await knowledge_repository.update_knowledge_base("kb-deleting", user_id="user-1", status="deleting")

    assert await knowledge_repository.list_searchable_document_ids(
        user_id="user-1",
        knowledge_base_ids=["kb-active", "kb-deleting"],
    ) == ["doc-ready"]
    assert await knowledge_repository.list_searchable_document_ids(user_id="user-2", knowledge_base_ids=["kb-active"]) == []
