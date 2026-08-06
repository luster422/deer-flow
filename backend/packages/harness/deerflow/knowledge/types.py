from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Chunk:
    id: str
    user_id: str
    knowledge_base_id: str
    document_id: str
    version: int
    chunk_index: int
    content: str
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IndexedChunk(Chunk):
    embedding: list[float] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SearchQuery:
    user_id: str
    knowledge_base_ids: tuple[str, ...]
    text: str
    embedding: list[float]
    top_k: int = 6
    vector_candidate_k: int = 30
    text_candidate_k: int = 30
    document_ids: tuple[str, ...] | None = None
    rrf_k: int = 60
    mmr_lambda: float = 0.8


@dataclass(frozen=True, slots=True)
class SearchHit:
    id: str
    user_id: str
    knowledge_base_id: str
    document_id: str
    content: str
    metadata: dict[str, Any]
    score: float
    vector_score: float | None = None
    text_score: float | None = None


@dataclass(frozen=True, slots=True)
class IndexStatus:
    ready: bool
    embedding_model: str
    embedding_dimension: int | None
    chunk_count: int
