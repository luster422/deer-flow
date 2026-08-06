from __future__ import annotations

import asyncio
import json
import math
import re
import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deerflow.knowledge.types import IndexedChunk, IndexStatus, SearchHit, SearchQuery


class DimensionMismatchError(ValueError):
    pass


@dataclass(slots=True)
class _Candidate:
    row: dict[str, Any]
    embedding: list[float]
    vector_score: float | None = None
    text_score: float | None = None
    fused_score: float = 0.0


class LocalHybridIndex:
    """Small-deployment hybrid index backed by SQLite FTS5.

    SQL work is dispatched to a worker thread so searches do not block an ASGI
    event loop. The owner predicate is applied inside every read and delete.
    """

    def __init__(self, path: str | Path, *, embedding_model: str) -> None:
        self._path = Path(path)
        self._embedding_model = embedding_model
        self._lock = asyncio.Lock()

    async def upsert(self, chunks: list[IndexedChunk]) -> None:
        if not chunks:
            return
        async with self._lock:
            await asyncio.to_thread(self._upsert_sync, chunks)

    async def delete_document(self, *, user_id: str, document_id: str) -> None:
        async with self._lock:
            await asyncio.to_thread(self._delete_document_sync, user_id, document_id)

    async def search(self, query: SearchQuery) -> list[SearchHit]:
        if not query.knowledge_base_ids or not query.embedding or query.top_k <= 0:
            return []
        return await asyncio.to_thread(self._search_sync, query)

    async def status(self) -> IndexStatus:
        return await asyncio.to_thread(self._status_sync)

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema(connection)
        return connection

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS manifest (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                knowledge_base_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB NOT NULL,
                embedding_dimension INTEGER NOT NULL,
                metadata TEXT NOT NULL,
                token_count INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_chunks_owner_scope
                ON chunks(user_id, knowledge_base_id, document_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                chunk_id UNINDEXED,
                content,
                tokenize='unicode61'
            );
            """
        )

    def _upsert_sync(self, chunks: list[IndexedChunk]) -> None:
        dimension = self._validate_chunk_dimensions(chunks)
        with self._connect() as connection:
            self._validate_manifest(connection, dimension=dimension, initialize=True)
            for chunk in chunks:
                connection.execute("DELETE FROM chunk_fts WHERE chunk_id = ?", (chunk.id,))
                connection.execute(
                    """
                    INSERT INTO chunks (
                        id, user_id, knowledge_base_id, document_id, version,
                        chunk_index, content, embedding, embedding_dimension,
                        metadata, token_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        user_id=excluded.user_id,
                        knowledge_base_id=excluded.knowledge_base_id,
                        document_id=excluded.document_id,
                        version=excluded.version,
                        chunk_index=excluded.chunk_index,
                        content=excluded.content,
                        embedding=excluded.embedding,
                        embedding_dimension=excluded.embedding_dimension,
                        metadata=excluded.metadata,
                        token_count=excluded.token_count
                    """,
                    (
                        chunk.id,
                        chunk.user_id,
                        chunk.knowledge_base_id,
                        chunk.document_id,
                        chunk.version,
                        chunk.chunk_index,
                        chunk.content,
                        self._pack_vector(chunk.embedding),
                        len(chunk.embedding),
                        json.dumps(chunk.metadata, ensure_ascii=False, separators=(",", ":")),
                        chunk.token_count,
                    ),
                )
                connection.execute("INSERT INTO chunk_fts(chunk_id, content) VALUES (?, ?)", (chunk.id, chunk.content))

    def _delete_document_sync(self, user_id: str, document_id: str) -> None:
        with self._connect() as connection:
            rows = connection.execute("SELECT id FROM chunks WHERE user_id = ? AND document_id = ?", (user_id, document_id)).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                connection.execute(f"DELETE FROM chunk_fts WHERE chunk_id IN ({placeholders})", ids)
                connection.execute(f"DELETE FROM chunks WHERE id IN ({placeholders})", ids)

    def _search_sync(self, query: SearchQuery) -> list[SearchHit]:
        with self._connect() as connection:
            self._validate_manifest(connection, dimension=len(query.embedding), initialize=False)
            filters, params = self._filter_sql(query)
            rows = connection.execute(f"SELECT * FROM chunks WHERE {filters}", params).fetchall()
            candidates: dict[str, _Candidate] = {row["id"]: _Candidate(row=dict(row), embedding=self._unpack_vector(row["embedding"], row["embedding_dimension"])) for row in rows}

            vector_ranked = sorted(candidates.values(), key=lambda item: (-self._cosine(query.embedding, item.embedding), item.row["id"]))[: query.vector_candidate_k]
            for rank, candidate in enumerate(vector_ranked, start=1):
                candidate.vector_score = self._cosine(query.embedding, candidate.embedding)
                candidate.fused_score += 1.0 / (query.rrf_k + rank)

            text_ranked = self._text_search(connection, query)
            for rank, (chunk_id, text_score) in enumerate(text_ranked, start=1):
                candidate = candidates.get(chunk_id)
                if candidate is None:
                    continue
                candidate.text_score = text_score
                candidate.fused_score += 1.0 / (query.rrf_k + rank)

            ranked = sorted(candidates.values(), key=lambda item: (-item.fused_score, item.row["id"]))
            selected = self._mmr(ranked, query=query)
            return [
                SearchHit(
                    id=item.row["id"],
                    user_id=item.row["user_id"],
                    knowledge_base_id=item.row["knowledge_base_id"],
                    document_id=item.row["document_id"],
                    content=item.row["content"],
                    metadata=json.loads(item.row["metadata"]),
                    score=item.fused_score,
                    vector_score=item.vector_score,
                    text_score=item.text_score,
                )
                for item in selected
            ]

    def _text_search(self, connection: sqlite3.Connection, query: SearchQuery) -> list[tuple[str, float]]:
        fts_query = self._fts_query(query.text)
        if not fts_query:
            return []
        filters, params = self._filter_sql(query, table="c")
        rows = connection.execute(
            f"""
            SELECT c.id, bm25(chunk_fts) AS text_rank
            FROM chunk_fts
            JOIN chunks AS c ON c.id = chunk_fts.chunk_id
            WHERE chunk_fts MATCH ? AND {filters}
            ORDER BY text_rank ASC, c.id ASC
            LIMIT ?
            """,
            [fts_query, *params, query.text_candidate_k],
        ).fetchall()
        return [(row["id"], 1.0 / (1.0 + abs(float(row["text_rank"])))) for row in rows]

    def _status_sync(self) -> IndexStatus:
        with self._connect() as connection:
            manifest = dict(connection.execute("SELECT key, value FROM manifest").fetchall())
            count = int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])
            dimension = int(manifest["embedding_dimension"]) if "embedding_dimension" in manifest else None
            return IndexStatus(
                ready=manifest.get("embedding_model") == self._embedding_model and dimension is not None,
                embedding_model=self._embedding_model,
                embedding_dimension=dimension,
                chunk_count=count,
            )

    def _validate_manifest(self, connection: sqlite3.Connection, *, dimension: int, initialize: bool) -> None:
        manifest = dict(connection.execute("SELECT key, value FROM manifest").fetchall())
        existing_model = manifest.get("embedding_model")
        existing_dimension = int(manifest["embedding_dimension"]) if "embedding_dimension" in manifest else None
        if existing_model is not None and existing_model != self._embedding_model:
            raise DimensionMismatchError(f"index embedding model is {existing_model!r}, configured model is {self._embedding_model!r}")
        if existing_dimension is not None and existing_dimension != dimension:
            raise DimensionMismatchError(f"index embedding dimension is {existing_dimension}, received {dimension}")
        if initialize and existing_model is None:
            connection.executemany(
                "INSERT INTO manifest(key, value) VALUES (?, ?)",
                [("embedding_model", self._embedding_model), ("embedding_dimension", str(dimension))],
            )

    @staticmethod
    def _validate_chunk_dimensions(chunks: list[IndexedChunk]) -> int:
        dimensions = {len(chunk.embedding) for chunk in chunks}
        if 0 in dimensions or len(dimensions) != 1:
            raise DimensionMismatchError("all chunk embeddings must have the same non-zero dimension")
        return dimensions.pop()

    @staticmethod
    def _filter_sql(query: SearchQuery, *, table: str | None = None) -> tuple[str, list[Any]]:
        prefix = f"{table}." if table else ""
        kb_placeholders = ",".join("?" for _ in query.knowledge_base_ids)
        clauses = [f"{prefix}user_id = ?", f"{prefix}knowledge_base_id IN ({kb_placeholders})"]
        params: list[Any] = [query.user_id, *query.knowledge_base_ids]
        if query.document_ids is not None:
            if not query.document_ids:
                clauses.append("1 = 0")
            else:
                doc_placeholders = ",".join("?" for _ in query.document_ids)
                clauses.append(f"{prefix}document_id IN ({doc_placeholders})")
                params.extend(query.document_ids)
        return " AND ".join(clauses), params

    @staticmethod
    def _fts_query(text: str) -> str:
        terms = re.findall(r"[\w]+", text, flags=re.UNICODE)
        return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms[:32])

    @staticmethod
    def _pack_vector(vector: list[float]) -> bytes:
        return struct.pack(f"<{len(vector)}f", *vector)

    @staticmethod
    def _unpack_vector(value: bytes, dimension: int) -> list[float]:
        return list(struct.unpack(f"<{dimension}f", value))

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)

    def _mmr(self, ranked: list[_Candidate], *, query: SearchQuery) -> list[_Candidate]:
        pool = [candidate for candidate in ranked if candidate.fused_score > 0]
        selected: list[_Candidate] = []
        while pool and len(selected) < query.top_k:
            if not selected:
                chosen = pool[0]
            else:
                chosen = max(
                    pool,
                    key=lambda item: (
                        query.mmr_lambda * item.fused_score - (1.0 - query.mmr_lambda) * max(self._cosine(item.embedding, prior.embedding) for prior in selected),
                        item.fused_score,
                        item.row["id"],
                    ),
                )
            selected.append(chosen)
            pool.remove(chosen)
        return selected
