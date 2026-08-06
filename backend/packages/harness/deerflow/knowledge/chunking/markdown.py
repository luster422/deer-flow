from __future__ import annotations

import re
from collections.abc import Callable

import tiktoken

from deerflow.knowledge.config import ChunkingConfig
from deerflow.knowledge.types import Chunk, ParsedDocument

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _default_token_counter(text: str) -> int:
    return len(tiktoken.get_encoding("cl100k_base").encode(text))


class MarkdownChunker:
    """Markdown-aware chunker that repeats active heading context."""

    def __init__(self, config: ChunkingConfig, *, token_counter: Callable[[str], int] | None = None) -> None:
        self._config = config
        self._count = token_counter or _default_token_counter

    def chunk(
        self,
        document: ParsedDocument,
        *,
        document_id: str,
        knowledge_base_id: str,
        user_id: str,
        version: int = 1,
    ) -> list[Chunk]:
        if not document.content.strip():
            return []

        blocks = self._contextual_blocks(document.content)
        pieces: list[str] = []
        current = ""
        for block in blocks:
            for part in self._split_oversized(block):
                candidate = f"{current}\n\n{part}".strip() if current else part
                if current and self._count(candidate) > self._config.target_tokens:
                    pieces.append(current)
                    overlap = self._overlap_suffix(current)
                    candidate = f"{overlap}\n\n{part}".strip() if overlap else part
                if self._count(candidate) > self._config.max_tokens:
                    if current:
                        pieces.append(current)
                    pieces.extend(self._split_oversized(part))
                    current = ""
                else:
                    current = candidate
        if current:
            pieces.append(current)

        chunks: list[Chunk] = []
        for index, content in enumerate(piece for piece in pieces if piece.strip()):
            chunks.append(
                Chunk(
                    id=f"{document_id}:{version}:{index}",
                    user_id=user_id,
                    knowledge_base_id=knowledge_base_id,
                    document_id=document_id,
                    version=version,
                    chunk_index=index,
                    content=content.strip(),
                    token_count=self._count(content),
                    metadata=dict(document.metadata),
                )
            )
        return chunks

    def _contextual_blocks(self, markdown: str) -> list[str]:
        headings: list[str] = []
        raw_blocks: list[str] = []
        buffer: list[str] = []
        in_fence = False

        def flush() -> None:
            if not buffer:
                return
            body = "\n".join(buffer).strip()
            buffer.clear()
            if body:
                prefix = "\n".join(headings)
                raw_blocks.append(f"{prefix}\n\n{body}".strip())

        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                buffer.append(line)
                continue
            heading = _HEADING_RE.match(line) if not in_fence else None
            if heading:
                flush()
                level = len(heading.group(1))
                headings[level - 1 :] = [line.strip()]
                continue
            if not stripped and not in_fence:
                flush()
                continue
            buffer.append(line)
        flush()
        return raw_blocks

    def _split_oversized(self, text: str) -> list[str]:
        if self._count(text) <= self._config.max_tokens:
            return [text]

        units = re.findall(r"\S+\s*", text)
        if len(units) <= 1:
            units = list(text)
        parts: list[str] = []
        start = 0
        while start < len(units):
            end = start + 1
            best = ""
            while end <= len(units):
                candidate = "".join(units[start:end]).strip()
                if self._count(candidate) > self._config.max_tokens:
                    break
                best = candidate
                end += 1
            if not best:
                best = units[start].strip()
                end = start + 2
            parts.append(best)
            if end > len(units):
                break
            next_start = max(start + 1, end - 1)
            while next_start > start + 1 and self._count("".join(units[next_start : end - 1])) < self._config.overlap_tokens:
                next_start -= 1
            start = next_start
        return parts

    def _overlap_suffix(self, text: str) -> str:
        if self._config.overlap_tokens == 0:
            return ""
        units = re.findall(r"\S+\s*", text)
        selected: list[str] = []
        for unit in reversed(units):
            candidate = "".join(reversed([unit, *selected])).strip()
            if selected and self._count(candidate) > self._config.overlap_tokens:
                break
            selected.insert(0, unit)
        return "".join(selected).strip()
