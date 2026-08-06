from __future__ import annotations

import asyncio
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

from deerflow.config.paths import make_safe_user_id

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class KnowledgeFileStorage:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    @staticmethod
    def _safe_id(value: str, *, field: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError(f"invalid {field}")
        return value

    @staticmethod
    def _safe_filename(filename: str) -> str:
        candidate = Path(filename).name
        if candidate != filename or candidate in {"", ".", ".."} or "\x00" in candidate:
            raise ValueError("invalid filename")
        return candidate

    def _user_root(self, user_id: str) -> Path:
        return self._root / "users" / make_safe_user_id(user_id) / "knowledge"

    async def write_source(
        self,
        *,
        user_id: str,
        knowledge_base_id: str,
        document_id: str,
        filename: str,
        content: bytes,
    ) -> tuple[str, int, str]:
        kb_id = self._safe_id(knowledge_base_id, field="knowledge_base_id")
        doc_id = self._safe_id(document_id, field="document_id")
        safe_filename = self._safe_filename(filename)
        destination = self._user_root(user_id) / kb_id / doc_id / "source" / safe_filename
        await asyncio.to_thread(self._write_atomic, destination, content)
        relative = destination.relative_to(self._root).as_posix()
        return relative, len(content), hashlib.sha256(content).hexdigest()

    def resolve_source(self, *, user_id: str, relative_path: str) -> Path:
        user_root = self._user_root(user_id).resolve()
        candidate = (self._root / relative_path).resolve()
        if not candidate.is_relative_to(user_root):
            raise ValueError("source path escapes user knowledge directory")
        return candidate

    async def read_content(self, *, user_id: str, relative_path: str) -> str:
        source = self.resolve_source(user_id=user_id, relative_path=relative_path)
        derived = source.parent.parent / "derived" / "content.md"
        if derived.is_file():
            return await asyncio.to_thread(derived.read_text, encoding="utf-8")
        if source.suffix.lower() not in {".md", ".markdown", ".txt"}:
            raise FileNotFoundError("parsed document content is not available")
        return await asyncio.to_thread(source.read_text, encoding="utf-8")

    async def delete_document(self, *, user_id: str, knowledge_base_id: str, document_id: str) -> None:
        kb_id = self._safe_id(knowledge_base_id, field="knowledge_base_id")
        doc_id = self._safe_id(document_id, field="document_id")
        document_dir = self._user_root(user_id) / kb_id / doc_id
        await asyncio.to_thread(shutil.rmtree, document_dir, True)

    @staticmethod
    def _write_atomic(destination: Path, content: bytes) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=".knowledge-upload-", suffix=".part", dir=destination.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, destination)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise
