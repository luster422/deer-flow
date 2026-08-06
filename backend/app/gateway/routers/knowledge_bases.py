from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, field_validator

from app.gateway.authz import require_permission
from deerflow.runtime.user_context import get_effective_user_id

router = APIRouter(prefix="/api", tags=["knowledge-bases"])

MAX_KNOWLEDGE_FILE_SIZE = 50 * 1024 * 1024


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class KnowledgeBaseUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    document_ids: list[str] | None = None


class KnowledgeBindingUpdateRequest(BaseModel):
    strategy: Literal["inherit", "union", "replace"] = "inherit"
    knowledge_base_ids: list[str] = Field(default_factory=list)


def _state(request: Request, name: str):
    value = getattr(request.app.state, name, None)
    if value is None:
        raise HTTPException(status_code=503, detail="Knowledge bases are disabled or unavailable")
    return value


def _repo(request: Request):
    return _state(request, "knowledge_repository")


def _ensure_enabled(request: Request) -> None:
    _state(request, "knowledge_ingestion_service")


def _user_id() -> str:
    return get_effective_user_id()


def _max_attempts(request: Request) -> int:
    config = getattr(request.app.state, "knowledge_config", None)
    return int(getattr(getattr(config, "ingestion", None), "max_attempts", 3))


@router.get("/knowledge-bases")
@require_permission("knowledge_bases", "read")
async def list_knowledge_bases(request: Request):
    _ensure_enabled(request)
    return {"knowledge_bases": await _repo(request).list_knowledge_bases(user_id=_user_id())}


@router.post("/knowledge-bases", status_code=status.HTTP_201_CREATED)
@require_permission("knowledge_bases", "write")
async def create_knowledge_base(request: Request, body: KnowledgeBaseCreateRequest):
    _ensure_enabled(request)
    return await _repo(request).create_knowledge_base(
        knowledge_base_id=f"kb-{uuid.uuid4().hex}",
        user_id=_user_id(),
        name=body.name.strip(),
        description=body.description.strip(),
    )


@router.get("/knowledge-bases/{knowledge_base_id}")
@require_permission("knowledge_bases", "read")
async def get_knowledge_base(knowledge_base_id: str, request: Request):
    _ensure_enabled(request)
    item = await _repo(request).get_knowledge_base(knowledge_base_id, user_id=_user_id())
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return item


@router.patch("/knowledge-bases/{knowledge_base_id}")
@require_permission("knowledge_bases", "write")
async def update_knowledge_base(knowledge_base_id: str, request: Request, body: KnowledgeBaseUpdateRequest):
    _ensure_enabled(request)
    item = await _repo(request).update_knowledge_base(
        knowledge_base_id,
        user_id=_user_id(),
        **body.model_dump(exclude_none=True),
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return item


@router.delete("/knowledge-bases/{knowledge_base_id}", status_code=status.HTTP_202_ACCEPTED)
@require_permission("knowledge_bases", "delete")
async def delete_knowledge_base(knowledge_base_id: str, request: Request):
    _ensure_enabled(request)
    repo = _repo(request)
    existing = await repo.get_knowledge_base(knowledge_base_id, user_id=_user_id())
    if existing is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    if existing["status"] == "deleting":
        return {"id": knowledge_base_id, "status": "deleting"}
    item = await repo.update_knowledge_base(knowledge_base_id, user_id=_user_id(), status="deleting")
    assert item is not None
    documents = await repo.list_documents(knowledge_base_id=knowledge_base_id, user_id=_user_id())
    for document in documents:
        if document["status"] == "deleting":
            continue
        await repo.update_document(document["id"], user_id=_user_id(), status="deleting")
        await repo.create_ingestion_job(
            job_id=f"kjob-{uuid.uuid4().hex}",
            document_id=document["id"],
            user_id=_user_id(),
            operation="delete",
            max_attempts=_max_attempts(request),
        )
    if not documents:
        await repo.finalize_knowledge_base_if_empty(knowledge_base_id, user_id=_user_id())
    return {"id": knowledge_base_id, "status": "deleting"}


@router.get("/knowledge-bases/{knowledge_base_id}/documents")
@require_permission("knowledge_bases", "read")
async def list_knowledge_documents(knowledge_base_id: str, request: Request):
    await get_knowledge_base(knowledge_base_id, request=request)
    return {"documents": await _repo(request).list_documents(knowledge_base_id=knowledge_base_id, user_id=_user_id())}


@router.post("/knowledge-bases/{knowledge_base_id}/documents", status_code=status.HTTP_202_ACCEPTED)
@require_permission("knowledge_bases", "write")
async def upload_knowledge_document(knowledge_base_id: str, request: Request, file: UploadFile = File(...)):
    _ensure_enabled(request)
    await get_knowledge_base(knowledge_base_id, request=request)
    filename = file.filename or ""
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed = (
        set(getattr(getattr(request.app.state, "knowledge_config", None), "parser", None).allowed_extensions) if getattr(getattr(request.app.state, "knowledge_config", None), "parser", None) else {"md", "txt", "pdf", "docx", "pptx", "xlsx"}
    )
    if extension not in allowed:
        raise HTTPException(status_code=415, detail="Unsupported knowledge document type")
    content = await file.read(MAX_KNOWLEDGE_FILE_SIZE + 1)
    if len(content) > MAX_KNOWLEDGE_FILE_SIZE:
        raise HTTPException(status_code=413, detail="Knowledge document is too large")
    digest = hashlib.sha256(content).hexdigest()
    repo = _repo(request)
    duplicate = await repo.get_document_by_hash(knowledge_base_id=knowledge_base_id, user_id=_user_id(), content_sha256=digest)
    if duplicate is not None:
        return {"document": duplicate, "job": None, "duplicate": True}

    document_id = f"kdoc-{uuid.uuid4().hex}"
    storage = _state(request, "knowledge_storage")
    relative_path, size_bytes, digest = await storage.write_source(
        user_id=_user_id(),
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        filename=filename,
        content=content,
    )
    document = await repo.create_document(
        document_id=document_id,
        knowledge_base_id=knowledge_base_id,
        user_id=_user_id(),
        filename=filename,
        media_type=file.content_type or "application/octet-stream",
        size_bytes=size_bytes,
        content_sha256=digest,
        source_path=relative_path,
    )
    job = await repo.create_ingestion_job(
        job_id=f"kjob-{uuid.uuid4().hex}",
        document_id=document_id,
        user_id=_user_id(),
        operation="index",
        max_attempts=_max_attempts(request),
    )
    return {"document": document, "job": job, "duplicate": False}


@router.get("/knowledge-bases/{knowledge_base_id}/documents/{document_id}")
@require_permission("knowledge_bases", "read")
async def get_knowledge_document(knowledge_base_id: str, document_id: str, request: Request):
    await get_knowledge_base(knowledge_base_id, request=request)
    document = await _repo(request).get_document(document_id, user_id=_user_id())
    if document is None or document["knowledge_base_id"] != knowledge_base_id:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return document


@router.get("/knowledge-bases/{knowledge_base_id}/documents/{document_id}/content")
@require_permission("knowledge_bases", "read")
async def get_knowledge_document_content(
    knowledge_base_id: str,
    document_id: str,
    request: Request,
    chunk_id: str | None = Query(
        default=None,
        max_length=256,
        pattern=r"^[A-Za-z0-9:_-]+$",
    ),
):
    document = await get_knowledge_document(knowledge_base_id, document_id, request=request)
    try:
        content = await _state(request, "knowledge_storage").read_content(user_id=_user_id(), relative_path=document["source_path"])
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail="Parsed document content is not available") from exc
    headers = {"X-Content-Type-Options": "nosniff"}
    if chunk_id:
        headers["X-Knowledge-Chunk-Id"] = chunk_id
    return PlainTextResponse(
        content,
        media_type="text/markdown",
        headers=headers,
    )


@router.delete("/knowledge-bases/{knowledge_base_id}/documents/{document_id}", status_code=status.HTTP_202_ACCEPTED)
@require_permission("knowledge_bases", "delete")
async def delete_knowledge_document(knowledge_base_id: str, document_id: str, request: Request):
    document = await get_knowledge_document(knowledge_base_id, document_id, request=request)
    if document["status"] == "deleting":
        return {"document": document, "job": None}
    await _repo(request).update_document(document_id, user_id=_user_id(), status="deleting")
    job = await _repo(request).create_ingestion_job(
        job_id=f"kjob-{uuid.uuid4().hex}",
        document_id=document_id,
        user_id=_user_id(),
        operation="delete",
        max_attempts=_max_attempts(request),
    )
    return {"document": {**document, "status": "deleting"}, "job": job}


@router.post("/knowledge-bases/{knowledge_base_id}/documents/{document_id}/retry", status_code=status.HTTP_202_ACCEPTED)
@require_permission("knowledge_bases", "write")
async def retry_knowledge_document(knowledge_base_id: str, document_id: str, request: Request):
    document = await get_knowledge_document(knowledge_base_id, document_id, request=request)
    if document["status"] != "failed":
        raise HTTPException(status_code=409, detail="Only failed documents can be retried")
    updated = await _repo(request).update_document(document_id, user_id=_user_id(), status="queued", error_code=None, error_message=None)
    job = await _repo(request).create_ingestion_job(
        job_id=f"kjob-{uuid.uuid4().hex}",
        document_id=document_id,
        user_id=_user_id(),
        operation="index",
        max_attempts=_max_attempts(request),
    )
    return {"document": updated, "job": job}


@router.post("/knowledge-bases/{knowledge_base_id}/search")
@require_permission("knowledge_bases", "read")
async def search_knowledge_base(knowledge_base_id: str, request: Request, body: KnowledgeSearchRequest):
    await get_knowledge_base(knowledge_base_id, request=request)
    manager = _state(request, "knowledge_manager")
    hits = await manager.search(
        user_id=_user_id(),
        text=body.query,
        knowledge_base_ids=[knowledge_base_id],
        top_k=body.top_k,
        document_ids=body.document_ids,
    )
    return {"query": body.query, "hits": [asdict(hit) for hit in hits]}


@router.get("/knowledge-ingestion-jobs/{job_id}")
@require_permission("knowledge_bases", "read")
async def get_knowledge_ingestion_job(job_id: str, request: Request):
    _ensure_enabled(request)
    job = await _repo(request).get_ingestion_job(job_id, user_id=_user_id())
    if job is None:
        raise HTTPException(status_code=404, detail="Knowledge ingestion job not found")
    return job


async def _get_bindings(request: Request, *, scope_type: Literal["thread", "agent"], scope_id: str):
    _ensure_enabled(request)
    result = await _repo(request).get_bindings(user_id=_user_id(), scope_type=scope_type, scope_id=scope_id)
    return result or {"strategy": "inherit" if scope_type == "thread" else "replace", "knowledge_base_ids": []}


async def _update_bindings(request: Request, *, scope_type: Literal["thread", "agent"], scope_id: str, body: KnowledgeBindingUpdateRequest):
    _ensure_enabled(request)
    try:
        await _repo(request).set_bindings(
            user_id=_user_id(),
            scope_type=scope_type,
            scope_id=scope_id,
            strategy=body.strategy,
            knowledge_base_ids=body.knowledge_base_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="One or more knowledge bases were not found") from exc
    return await _get_bindings(request, scope_type=scope_type, scope_id=scope_id)


@router.get("/threads/{thread_id}/knowledge-bases")
@require_permission("threads", "read", owner_check=True)
async def get_thread_bindings(thread_id: str, request: Request):
    return await _get_bindings(request, scope_type="thread", scope_id=thread_id)


@router.put("/threads/{thread_id}/knowledge-bases")
@require_permission("threads", "write", owner_check=True, require_existing=False)
async def update_thread_bindings(thread_id: str, request: Request, body: KnowledgeBindingUpdateRequest):
    return await _update_bindings(request, scope_type="thread", scope_id=thread_id, body=body)


@router.get("/agents/{agent_name}/knowledge-bases")
@require_permission("knowledge_bases", "read")
async def get_agent_bindings(agent_name: str, request: Request):
    return await _get_bindings(request, scope_type="agent", scope_id=agent_name.lower())


@router.put("/agents/{agent_name}/knowledge-bases")
@require_permission("knowledge_bases", "write")
async def update_agent_bindings(agent_name: str, request: Request, body: KnowledgeBindingUpdateRequest):
    return await _update_bindings(request, scope_type="agent", scope_id=agent_name.lower(), body=body)
