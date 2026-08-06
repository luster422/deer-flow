from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from deerflow.persistence.knowledge.model import (
    KnowledgeBaseRow,
    KnowledgeBindingRow,
    KnowledgeBindingScopeRow,
    KnowledgeDocumentRow,
    KnowledgeIngestionJobRow,
)
from deerflow.utils.time import coerce_iso

ScopeType = Literal["thread", "agent"]
BindingStrategy = Literal["inherit", "union", "replace"]


class KnowledgeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._sf = session_factory

    @staticmethod
    def _dict(row: Any) -> dict[str, Any]:
        data = row.to_dict()
        for key, value in data.items():
            if isinstance(value, datetime):
                data[key] = coerce_iso(value)
        return data

    async def create_knowledge_base(self, *, knowledge_base_id: str, user_id: str, name: str, description: str = "") -> dict[str, Any]:
        row = KnowledgeBaseRow(id=knowledge_base_id, user_id=user_id, name=name, description=description)
        async with self._sf() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._dict(row)

    async def get_knowledge_base(self, knowledge_base_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(KnowledgeBaseRow, knowledge_base_id)
            return self._dict(row) if row is not None and row.user_id == user_id else None

    async def list_knowledge_bases(self, *, user_id: str) -> list[dict[str, Any]]:
        stmt = select(KnowledgeBaseRow).where(KnowledgeBaseRow.user_id == user_id).order_by(KnowledgeBaseRow.updated_at.desc(), KnowledgeBaseRow.id.asc())
        async with self._sf() as session:
            rows = (await session.execute(stmt)).scalars()
            return [self._dict(row) for row in rows]

    async def update_knowledge_base(self, knowledge_base_id: str, *, user_id: str, name: str | None = None, description: str | None = None, status: str | None = None) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(KnowledgeBaseRow, knowledge_base_id)
            if row is None or row.user_id != user_id:
                return None
            if name is not None:
                row.name = name
            if description is not None:
                row.description = description
            if status is not None:
                row.status = status
            row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._dict(row)

    async def delete_knowledge_base(self, knowledge_base_id: str, *, user_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(KnowledgeBaseRow, knowledge_base_id)
            if row is None or row.user_id != user_id:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def create_document(
        self,
        *,
        document_id: str,
        knowledge_base_id: str,
        user_id: str,
        filename: str,
        media_type: str,
        size_bytes: int,
        content_sha256: str,
        source_path: str,
        version: int = 1,
    ) -> dict[str, Any]:
        async with self._sf() as session:
            knowledge_base = await session.get(KnowledgeBaseRow, knowledge_base_id)
            if knowledge_base is None or knowledge_base.user_id != user_id:
                raise ValueError("knowledge base not owned by user")
            row = KnowledgeDocumentRow(
                id=document_id,
                knowledge_base_id=knowledge_base_id,
                user_id=user_id,
                filename=filename,
                media_type=media_type,
                size_bytes=size_bytes,
                content_sha256=content_sha256,
                source_path=source_path,
                version=version,
            )
            session.add(row)
            knowledge_base.document_count += 1
            knowledge_base.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._dict(row)

    async def get_document(self, document_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(KnowledgeDocumentRow, document_id)
            return self._dict(row) if row is not None and row.user_id == user_id else None

    async def get_document_by_hash(self, *, knowledge_base_id: str, user_id: str, content_sha256: str) -> dict[str, Any] | None:
        stmt = (
            select(KnowledgeDocumentRow)
            .where(
                KnowledgeDocumentRow.knowledge_base_id == knowledge_base_id,
                KnowledgeDocumentRow.user_id == user_id,
                KnowledgeDocumentRow.content_sha256 == content_sha256,
                KnowledgeDocumentRow.status != "deleting",
            )
            .order_by(KnowledgeDocumentRow.version.desc(), KnowledgeDocumentRow.id.desc())
        )
        async with self._sf() as session:
            row = (await session.execute(stmt)).scalars().first()
            return self._dict(row) if row is not None else None

    async def list_documents(self, *, knowledge_base_id: str, user_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(KnowledgeDocumentRow)
            .where(
                KnowledgeDocumentRow.knowledge_base_id == knowledge_base_id,
                KnowledgeDocumentRow.user_id == user_id,
            )
            .order_by(KnowledgeDocumentRow.created_at.desc(), KnowledgeDocumentRow.id.desc())
        )
        async with self._sf() as session:
            return [self._dict(row) for row in (await session.execute(stmt)).scalars()]

    async def list_searchable_document_ids(
        self,
        *,
        user_id: str,
        knowledge_base_ids: list[str],
        document_ids: list[str] | None = None,
    ) -> list[str]:
        if not knowledge_base_ids or document_ids == []:
            return []
        stmt = (
            select(KnowledgeDocumentRow.id)
            .join(
                KnowledgeBaseRow,
                KnowledgeBaseRow.id == KnowledgeDocumentRow.knowledge_base_id,
            )
            .where(
                KnowledgeDocumentRow.user_id == user_id,
                KnowledgeDocumentRow.knowledge_base_id.in_(knowledge_base_ids),
                KnowledgeDocumentRow.status == "ready",
                KnowledgeBaseRow.user_id == user_id,
                KnowledgeBaseRow.status == "active",
            )
            .order_by(KnowledgeDocumentRow.id.asc())
        )
        if document_ids is not None:
            stmt = stmt.where(KnowledgeDocumentRow.id.in_(document_ids))
        async with self._sf() as session:
            return list((await session.execute(stmt)).scalars())

    async def delete_document(self, document_id: str, *, user_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(KnowledgeDocumentRow, document_id)
            if row is None or row.user_id != user_id:
                return False
            knowledge_base = await session.get(KnowledgeBaseRow, row.knowledge_base_id)
            if knowledge_base is not None:
                knowledge_base.document_count = max(0, knowledge_base.document_count - 1)
                knowledge_base.chunk_count = max(0, knowledge_base.chunk_count - row.chunk_count)
                knowledge_base.updated_at = datetime.now(UTC)
            await session.delete(row)
            await session.commit()
            return True

    async def finalize_knowledge_base_if_empty(self, knowledge_base_id: str, *, user_id: str) -> bool:
        async with self._sf() as session:
            row = await session.get(KnowledgeBaseRow, knowledge_base_id)
            if row is None or row.user_id != user_id or row.status != "deleting":
                return False
            remaining = (
                await session.execute(
                    select(KnowledgeDocumentRow.id)
                    .where(
                        KnowledgeDocumentRow.knowledge_base_id == knowledge_base_id,
                        KnowledgeDocumentRow.user_id == user_id,
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if remaining is not None:
                return False
            await session.delete(row)
            await session.commit()
            return True

    async def update_document(self, document_id: str, *, user_id: str, **updates: Any) -> dict[str, Any] | None:
        allowed = {"status", "index_revision", "chunk_count", "error_code", "error_message"}
        async with self._sf() as session:
            row = await session.get(KnowledgeDocumentRow, document_id)
            if row is None or row.user_id != user_id:
                return None
            old_chunks = row.chunk_count
            for key, value in updates.items():
                if key in allowed:
                    setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            if row.chunk_count != old_chunks:
                knowledge_base = await session.get(KnowledgeBaseRow, row.knowledge_base_id)
                if knowledge_base is not None:
                    knowledge_base.chunk_count = max(0, knowledge_base.chunk_count + row.chunk_count - old_chunks)
                    knowledge_base.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return self._dict(row)

    async def create_ingestion_job(self, *, job_id: str, document_id: str, user_id: str, operation: str, max_attempts: int) -> dict[str, Any]:
        async with self._sf() as session:
            document = await session.get(KnowledgeDocumentRow, document_id)
            if document is None or document.user_id != user_id:
                raise ValueError("document not owned by user")
            row = KnowledgeIngestionJobRow(id=job_id, document_id=document_id, user_id=user_id, operation=operation, max_attempts=max_attempts)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return self._dict(row)

    async def get_ingestion_job(self, job_id: str, *, user_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            row = await session.get(KnowledgeIngestionJobRow, job_id)
            return self._dict(row) if row is not None and row.user_id == user_id else None

    async def claim_ingestion_jobs(self, *, now: datetime, lease_owner: str, lease_seconds: int, limit: int) -> list[dict[str, Any]]:
        stmt = (
            select(KnowledgeIngestionJobRow)
            .where(
                KnowledgeIngestionJobRow.attempts < KnowledgeIngestionJobRow.max_attempts,
                or_(KnowledgeIngestionJobRow.next_attempt_at.is_(None), KnowledgeIngestionJobRow.next_attempt_at <= now),
                or_(
                    KnowledgeIngestionJobRow.status == "queued",
                    and_(
                        KnowledgeIngestionJobRow.status == "running",
                        KnowledgeIngestionJobRow.lease_expires_at.is_not(None),
                        KnowledgeIngestionJobRow.lease_expires_at < now,
                    ),
                ),
            )
            .order_by(KnowledgeIngestionJobRow.created_at.asc(), KnowledgeIngestionJobRow.id.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        async with self._sf() as session:
            rows = list((await session.execute(stmt)).scalars())
            for row in rows:
                row.status = "running"
                row.attempts += 1
                row.lease_owner = lease_owner
                row.lease_expires_at = now + timedelta(seconds=lease_seconds)
                row.updated_at = now
            await session.commit()
            return [self._dict(row) for row in rows]

    async def complete_ingestion_job(self, job_id: str, *, lease_owner: str) -> bool:
        async with self._sf() as session:
            row = await session.get(KnowledgeIngestionJobRow, job_id)
            if row is None or row.status != "running" or row.lease_owner != lease_owner:
                return False
            row.status = "succeeded"
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def fail_ingestion_job(self, job_id: str, *, lease_owner: str, error: str, retry_at: datetime | None) -> bool:
        async with self._sf() as session:
            row = await session.get(KnowledgeIngestionJobRow, job_id)
            if row is None or row.status != "running" or row.lease_owner != lease_owner:
                return False
            row.status = "queued" if retry_at is not None and row.attempts < row.max_attempts else "failed"
            row.last_error = error
            row.next_attempt_at = retry_at
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def set_bindings(
        self,
        *,
        user_id: str,
        scope_type: ScopeType,
        scope_id: str,
        strategy: BindingStrategy,
        knowledge_base_ids: list[str],
    ) -> None:
        if scope_type not in {"thread", "agent"}:
            raise ValueError("unsupported binding scope type")
        if strategy not in {"inherit", "union", "replace"}:
            raise ValueError("unsupported binding strategy")
        unique_ids = list(dict.fromkeys(knowledge_base_ids))
        async with self._sf() as session:
            if unique_ids:
                owned = set((await session.execute(select(KnowledgeBaseRow.id).where(KnowledgeBaseRow.user_id == user_id, KnowledgeBaseRow.id.in_(unique_ids)))).scalars())
                if owned != set(unique_ids):
                    raise ValueError("one or more knowledge bases are not owned by user")
            await session.execute(
                delete(KnowledgeBindingRow).where(
                    KnowledgeBindingRow.user_id == user_id,
                    KnowledgeBindingRow.scope_type == scope_type,
                    KnowledgeBindingRow.scope_id == scope_id,
                )
            )
            scope_stmt = select(KnowledgeBindingScopeRow).where(
                KnowledgeBindingScopeRow.user_id == user_id,
                KnowledgeBindingScopeRow.scope_type == scope_type,
                KnowledgeBindingScopeRow.scope_id == scope_id,
            )
            scope = (await session.execute(scope_stmt)).scalar_one_or_none()
            if scope is None:
                scope = KnowledgeBindingScopeRow(id=f"kbs-{uuid.uuid4().hex}", user_id=user_id, scope_type=scope_type, scope_id=scope_id, strategy=strategy)
                session.add(scope)
            else:
                scope.strategy = strategy
                scope.updated_at = datetime.now(UTC)
            session.add_all(
                [
                    KnowledgeBindingRow(
                        id=f"kbd-{uuid.uuid4().hex}",
                        user_id=user_id,
                        knowledge_base_id=knowledge_base_id,
                        scope_type=scope_type,
                        scope_id=scope_id,
                    )
                    for knowledge_base_id in unique_ids
                ]
            )
            await session.commit()

    async def get_bindings(self, *, user_id: str, scope_type: ScopeType, scope_id: str) -> dict[str, Any] | None:
        async with self._sf() as session:
            scope = (
                await session.execute(
                    select(KnowledgeBindingScopeRow).where(
                        KnowledgeBindingScopeRow.user_id == user_id,
                        KnowledgeBindingScopeRow.scope_type == scope_type,
                        KnowledgeBindingScopeRow.scope_id == scope_id,
                    )
                )
            ).scalar_one_or_none()
            if scope is None:
                return None
            ids = list(
                (
                    await session.execute(
                        select(KnowledgeBindingRow.knowledge_base_id)
                        .join(KnowledgeBaseRow, KnowledgeBaseRow.id == KnowledgeBindingRow.knowledge_base_id)
                        .where(
                            KnowledgeBindingRow.user_id == user_id,
                            KnowledgeBindingRow.scope_type == scope_type,
                            KnowledgeBindingRow.scope_id == scope_id,
                            KnowledgeBaseRow.user_id == user_id,
                            KnowledgeBaseRow.status == "active",
                        )
                        .order_by(KnowledgeBindingRow.knowledge_base_id.asc())
                    )
                ).scalars()
            )
            return {"strategy": scope.strategy, "knowledge_base_ids": ids}

    async def resolve_bindings(self, *, user_id: str, agent_id: str | None, thread_id: str | None) -> list[str]:
        agent = await self.get_bindings(user_id=user_id, scope_type="agent", scope_id=agent_id) if agent_id else None
        base = list(agent["knowledge_base_ids"]) if agent is not None else []
        thread = await self.get_bindings(user_id=user_id, scope_type="thread", scope_id=thread_id) if thread_id else None
        if thread is None or thread["strategy"] == "inherit":
            return base
        if thread["strategy"] == "replace":
            return list(thread["knowledge_base_ids"])
        return list(dict.fromkeys([*base, *thread["knowledge_base_ids"]]))
