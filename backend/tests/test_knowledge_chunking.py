from __future__ import annotations

from deerflow.knowledge.chunking.markdown import MarkdownChunker
from deerflow.knowledge.config import ChunkingConfig
from deerflow.knowledge.types import ParsedDocument


def _word_count(text: str) -> int:
    return len(text.split())


def test_chunker_returns_no_chunks_for_blank_document() -> None:
    chunker = MarkdownChunker(ChunkingConfig(), token_counter=_word_count)

    assert chunker.chunk(ParsedDocument(content="  \n\n"), document_id="doc-1", knowledge_base_id="kb-1", user_id="user-1") == []


def test_chunker_preserves_heading_context_and_chunk_identity() -> None:
    chunker = MarkdownChunker(
        ChunkingConfig(target_tokens=8, overlap_tokens=2, max_tokens=12),
        token_counter=_word_count,
    )
    document = ParsedDocument(
        content="# Handbook\n\n## Access\n\nalpha beta gamma delta epsilon zeta.\n\n## Billing\n\ninvoice refund receipt policy.",
        metadata={"source": "handbook.md"},
    )

    chunks = chunker.chunk(document, document_id="doc-1", knowledge_base_id="kb-1", user_id="user-1", version=2)

    assert len(chunks) >= 2
    assert chunks[0].id == "doc-1:2:0"
    assert all(chunk.user_id == "user-1" for chunk in chunks)
    assert all(chunk.knowledge_base_id == "kb-1" for chunk in chunks)
    assert all(chunk.document_id == "doc-1" for chunk in chunks)
    assert any("Access" in chunk.content for chunk in chunks)
    assert any("Billing" in chunk.content for chunk in chunks)
    assert all(chunk.metadata["source"] == "handbook.md" for chunk in chunks)


def test_chunker_hard_splits_a_single_oversized_block() -> None:
    chunker = MarkdownChunker(
        ChunkingConfig(target_tokens=5, overlap_tokens=1, max_tokens=6),
        token_counter=_word_count,
    )
    document = ParsedDocument(content=" ".join(f"token-{index}" for index in range(17)))

    chunks = chunker.chunk(document, document_id="doc-2", knowledge_base_id="kb-1", user_id="user-1")

    assert len(chunks) >= 3
    assert all(chunk.token_count <= 6 for chunk in chunks)
    assert "token-0" in chunks[0].content
    assert "token-16" in chunks[-1].content
