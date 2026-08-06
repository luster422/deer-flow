from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.knowledge.storage import KnowledgeFileStorage
from deerflow.knowledge.ports import DocumentParser, EmbeddingProvider, RetrievalIndex
from deerflow.knowledge.types import IndexedChunk
from deerflow.persistence.knowledge import KnowledgeRepository

logger = logging.getLogger(__name__)


class KnowledgeIngestionService:
    def __init__(
        self,
        *,
        repository: KnowledgeRepository,
        storage: KnowledgeFileStorage,
        parser: DocumentParser,
        chunker: Any,
        embedding: EmbeddingProvider,
        index: RetrievalIndex,
        workers: int = 2,
        lease_seconds: int = 120,
        poll_interval_seconds: float = 1.0,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._parser = parser
        self._chunker = chunker
        self._embedding = embedding
        self._index = index
        self._workers = workers
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._tasks: list[asyncio.Task[None]] = []
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._tasks:
            return
        self._stop.clear()
        self._tasks = [asyncio.create_task(self._worker_loop(f"knowledge-{index}")) for index in range(self._workers)]

    async def stop(self) -> None:
        self._stop.set()
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _worker_loop(self, lease_owner: str) -> None:
        while not self._stop.is_set():
            try:
                jobs = await self._repository.claim_ingestion_jobs(
                    now=datetime.now(UTC),
                    lease_owner=lease_owner,
                    lease_seconds=self._lease_seconds,
                    limit=1,
                )
                if not jobs:
                    await asyncio.sleep(self._poll_interval_seconds)
                    continue
                await self.process_claimed_job(jobs[0], lease_owner=lease_owner)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Knowledge ingestion worker failed")
                await asyncio.sleep(self._poll_interval_seconds)

    async def process_claimed_job(self, job: dict[str, Any], *, lease_owner: str) -> None:
        document = await self._repository.get_document(job["document_id"], user_id=job["user_id"])
        if document is None:
            await self._repository.fail_ingestion_job(job["id"], lease_owner=lease_owner, error="document not found", retry_at=None)
            return
        if job["operation"] == "delete":
            try:
                await self._index.delete_document(user_id=document["user_id"], document_id=document["id"])
                await self._storage.delete_document(
                    user_id=document["user_id"],
                    knowledge_base_id=document["knowledge_base_id"],
                    document_id=document["id"],
                )
                await self._repository.delete_document(document["id"], user_id=document["user_id"])
                await self._repository.finalize_knowledge_base_if_empty(document["knowledge_base_id"], user_id=document["user_id"])
            except Exception as exc:
                await self._repository.fail_ingestion_job(
                    job["id"],
                    lease_owner=lease_owner,
                    error=str(exc)[:500],
                    retry_at=self._retry_at(job),
                )
                logger.warning("Knowledge deletion failed for document %s: %s", document["id"], exc)
            return
        stage = "parsing"
        try:
            await self._repository.update_document(document["id"], user_id=document["user_id"], status="parsing", error_code=None, error_message=None)
            source = self._storage.resolve_source(user_id=document["user_id"], relative_path=document["source_path"])
            parsed = await self._parser.parse(source, media_type=document["media_type"])
            chunks = self._chunker.chunk(
                parsed,
                document_id=document["id"],
                knowledge_base_id=document["knowledge_base_id"],
                user_id=document["user_id"],
                version=document["version"],
            )
            if not chunks:
                raise ValueError("parsed document is empty")

            stage = "embedding"
            await self._repository.update_document(document["id"], user_id=document["user_id"], status="embedding")
            vectors = await self._embedding.embed_documents([chunk.content for chunk in chunks])
            if len(vectors) != len(chunks):
                raise ValueError("embedding provider returned an unexpected vector count")
            indexed = [
                IndexedChunk(
                    id=chunk.id,
                    user_id=chunk.user_id,
                    knowledge_base_id=chunk.knowledge_base_id,
                    document_id=chunk.document_id,
                    version=chunk.version,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    metadata=chunk.metadata,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]

            stage = "indexing"
            await self._repository.update_document(document["id"], user_id=document["user_id"], status="indexing")
            await self._index.upsert(indexed)
            await self._repository.update_document(
                document["id"],
                user_id=document["user_id"],
                status="ready",
                index_revision=document["version"],
                chunk_count=len(indexed),
                error_code=None,
                error_message=None,
            )
            await self._repository.complete_ingestion_job(job["id"], lease_owner=lease_owner)
        except Exception as exc:
            error_code = {"parsing": "parse_failed", "embedding": "embedding_failed", "indexing": "index_failed"}[stage]
            safe_message = str(exc)[:500]
            await self._repository.update_document(
                document["id"],
                user_id=document["user_id"],
                status="failed",
                error_code=error_code,
                error_message=safe_message,
            )
            retry_at = self._retry_at(job)
            await self._repository.fail_ingestion_job(job["id"], lease_owner=lease_owner, error=safe_message, retry_at=retry_at)
            logger.warning("Knowledge ingestion failed at %s for document %s: %s", stage, document["id"], exc)

    @staticmethod
    def _retry_at(job: dict[str, Any]) -> datetime | None:
        attempts = int(job.get("attempts", 1))
        if attempts >= int(job.get("max_attempts", 1)):
            return None
        return datetime.now(UTC) + timedelta(seconds=min(60, 2**attempts))
