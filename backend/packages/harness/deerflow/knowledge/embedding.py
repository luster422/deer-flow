from __future__ import annotations

import asyncio
from typing import Any


class LangChainEmbeddingAdapter:
    """Normalize LangChain embedding implementations to the RAG port."""

    def __init__(
        self,
        implementation: Any,
        *,
        batch_size: int = 64,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._implementation = implementation
        self._batch_size = batch_size
        self._timeout_seconds = timeout_seconds

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            results.extend(
                await asyncio.wait_for(
                    self._embed_documents_batch(batch),
                    timeout=self._timeout_seconds,
                )
            )
        return results

    async def _embed_documents_batch(self, texts: list[str]) -> list[list[float]]:
        async_method = getattr(self._implementation, "aembed_documents", None)
        if async_method is not None:
            return await async_method(texts)
        return await asyncio.to_thread(self._implementation.embed_documents, texts)

    async def embed_query(self, text: str) -> list[float]:
        return await asyncio.wait_for(self._embed_query(text), timeout=self._timeout_seconds)

    async def _embed_query(self, text: str) -> list[float]:
        async_method = getattr(self._implementation, "aembed_query", None)
        if async_method is not None:
            return await async_method(text)
        return await asyncio.to_thread(self._implementation.embed_query, text)
