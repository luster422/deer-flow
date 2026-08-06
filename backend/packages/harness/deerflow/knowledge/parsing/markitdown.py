from __future__ import annotations

import asyncio
from pathlib import Path

from deerflow.knowledge.types import ParsedDocument
from deerflow.utils.file_conversion import convert_file_to_markdown


class MarkItDownParser:
    """Parse plain text directly and office/PDF sources through MarkItDown."""

    async def parse(self, path: Path, *, media_type: str) -> ParsedDocument:
        suffix = path.suffix.lower()
        if suffix in {".md", ".markdown", ".txt"} or media_type.startswith("text/"):
            content = await asyncio.to_thread(path.read_text, encoding="utf-8")
        else:
            derived_dir = path.parent.parent / "derived"
            await asyncio.to_thread(derived_dir.mkdir, parents=True, exist_ok=True)
            converted = await convert_file_to_markdown(path, output_path=derived_dir / "content.md")
            if converted is None:
                raise ValueError(f"could not parse document type {suffix or media_type}")
            content = await asyncio.to_thread(converted.read_text, encoding="utf-8")
        return ParsedDocument(content=content, metadata={"filename": path.name, "media_type": media_type})
