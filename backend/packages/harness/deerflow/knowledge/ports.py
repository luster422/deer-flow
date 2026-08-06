from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from deerflow.knowledge.types import IndexedChunk, IndexStatus, ParsedDocument, SearchHit, SearchQuery


@runtime_checkable
class DocumentParser(Protocol):
    async def parse(self, path: Path, *, media_type: str) -> ParsedDocument: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class RetrievalIndex(Protocol):
    async def upsert(self, chunks: list[IndexedChunk]) -> None: ...

    async def delete_document(self, *, user_id: str, document_id: str) -> None: ...

    async def search(self, query: SearchQuery) -> list[SearchHit]: ...

    async def status(self) -> IndexStatus: ...
