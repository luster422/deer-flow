from __future__ import annotations

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import deerflow.persistence.models  # noqa: F401
from app.gateway.routers import knowledge_bases
from app.knowledge.storage import KnowledgeFileStorage
from deerflow.knowledge.manager import KnowledgeManager
from deerflow.knowledge.retrieval.local import LocalHybridIndex
from deerflow.persistence.base import Base
from deerflow.persistence.knowledge import KnowledgeRepository
from deerflow.runtime.user_context import reset_current_user, set_current_user


class FakeEmbeddingProvider:
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, float(index)] for index, _text in enumerate(texts)]

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


@pytest_asyncio.fixture
async def router_context(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'router.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    repository = KnowledgeRepository(async_sessionmaker(engine, expire_on_commit=False))
    storage = KnowledgeFileStorage(tmp_path / "files")
    manager = KnowledgeManager(
        index=LocalHybridIndex(tmp_path / "index.db", embedding_model="fake-v1"),
        embedding=FakeEmbeddingProvider(),
        repository=repository,
    )
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                knowledge_repository=repository,
                knowledge_storage=storage,
                knowledge_manager=manager,
                knowledge_ingestion_service=object(),
            )
        ),
        state=SimpleNamespace(),
        cookies={},
        _deerflow_test_bypass_auth=True,
    )
    try:
        yield request, repository
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_create_list_and_owner_hidden_get(router_context) -> None:
    request, _repository = router_context
    token = set_current_user(SimpleNamespace(id="user-1"))
    try:
        created = await knowledge_bases.create_knowledge_base(
            request=request,
            body=knowledge_bases.KnowledgeBaseCreateRequest(name="Engineering", description="Runbooks"),
        )
        listed = await knowledge_bases.list_knowledge_bases(request=request)
        assert listed["knowledge_bases"][0]["id"] == created["id"]
    finally:
        reset_current_user(token)

    other = set_current_user(SimpleNamespace(id="user-2"))
    try:
        with pytest.raises(HTTPException) as exc_info:
            await knowledge_bases.get_knowledge_base(created["id"], request=request)
        assert exc_info.value.status_code == 404
    finally:
        reset_current_user(other)


@pytest.mark.asyncio
async def test_upload_returns_document_and_queued_job(router_context) -> None:
    request, repository = router_context
    token = set_current_user(SimpleNamespace(id="user-1"))
    try:
        knowledge_base = await knowledge_bases.create_knowledge_base(request=request, body=knowledge_bases.KnowledgeBaseCreateRequest(name="Docs"))
        response = await knowledge_bases.upload_knowledge_document(
            knowledge_base["id"],
            request=request,
            file=UploadFile(filename="guide.md", file=BytesIO(b"# Guide\n\nAlpha deployment."), headers={"content-type": "text/markdown"}),
        )
        assert response["document"]["status"] == "queued"
        assert response["job"]["status"] == "queued"
        assert await repository.get_document(response["document"]["id"], user_id="user-1") is not None
        content = await knowledge_bases.get_knowledge_document_content(
            knowledge_base["id"],
            response["document"]["id"],
            request=request,
            chunk_id="chunk-1",
        )
        assert content.body == b"# Guide\n\nAlpha deployment."
        assert content.headers["x-knowledge-chunk-id"] == "chunk-1"
    finally:
        reset_current_user(token)


@pytest.mark.asyncio
async def test_thread_binding_endpoint_preserves_empty_replace(router_context) -> None:
    request, _repository = router_context
    token = set_current_user(SimpleNamespace(id="user-1"))
    try:
        result = await knowledge_bases.update_thread_bindings(
            "thread-1",
            request=request,
            body=knowledge_bases.KnowledgeBindingUpdateRequest(strategy="replace", knowledge_base_ids=[]),
        )
        assert result == {"strategy": "replace", "knowledge_base_ids": []}
        assert await knowledge_bases.get_thread_bindings("thread-1", request=request) == result
    finally:
        reset_current_user(token)


@pytest.mark.asyncio
async def test_repeated_document_delete_does_not_enqueue_another_job(router_context) -> None:
    request, _repository = router_context
    token = set_current_user(SimpleNamespace(id="user-1"))
    try:
        knowledge_base = await knowledge_bases.create_knowledge_base(
            request=request,
            body=knowledge_bases.KnowledgeBaseCreateRequest(name="Docs"),
        )
        uploaded = await knowledge_bases.upload_knowledge_document(
            knowledge_base["id"],
            request=request,
            file=UploadFile(
                filename="guide.md",
                file=BytesIO(b"# Guide"),
                headers={"content-type": "text/markdown"},
            ),
        )

        first = await knowledge_bases.delete_knowledge_document(knowledge_base["id"], uploaded["document"]["id"], request=request)
        second = await knowledge_bases.delete_knowledge_document(knowledge_base["id"], uploaded["document"]["id"], request=request)

        assert first["job"] is not None
        assert second["document"]["id"] == first["document"]["id"]
        assert second["document"]["status"] == "deleting"
        assert second["job"] is None
    finally:
        reset_current_user(token)


def test_create_request_rejects_blank_name() -> None:
    with pytest.raises(ValidationError):
        knowledge_bases.KnowledgeBaseCreateRequest(name="   ")


def test_update_request_normalizes_name_and_rejects_blank_name() -> None:
    assert knowledge_bases.KnowledgeBaseUpdateRequest(name="  Engineering  ").name == "Engineering"
    with pytest.raises(ValidationError):
        knowledge_bases.KnowledgeBaseUpdateRequest(name="   ")
