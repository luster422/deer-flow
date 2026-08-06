from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.knowledge.ingestion import KnowledgeIngestionService
from app.knowledge.storage import KnowledgeFileStorage
from deerflow.config.paths import get_paths
from deerflow.knowledge.chunking.markdown import MarkdownChunker
from deerflow.knowledge.embedding import LangChainEmbeddingAdapter
from deerflow.knowledge.manager import KnowledgeManager, set_knowledge_manager
from deerflow.persistence.knowledge import KnowledgeRepository
from deerflow.reflection.resolvers import resolve_class


@dataclass(slots=True)
class KnowledgeRuntime:
    manager: KnowledgeManager
    ingestion_service: KnowledgeIngestionService
    storage: KnowledgeFileStorage


def build_knowledge_runtime(config, repository: KnowledgeRepository) -> KnowledgeRuntime:
    knowledge = config.knowledge
    if not knowledge.enabled:
        raise ValueError("knowledge runtime cannot be built while knowledge.enabled=false")

    parser_class = resolve_class(knowledge.parser.use)
    parser = parser_class()

    embedding_class = resolve_class(knowledge.embedding.use)
    embedding_kwargs: dict[str, object] = {"model": knowledge.embedding.model}
    if knowledge.embedding.api_key:
        embedding_kwargs["api_key"] = knowledge.embedding.api_key
    embedding = LangChainEmbeddingAdapter(
        embedding_class(**embedding_kwargs),
        batch_size=knowledge.embedding.batch_size,
        timeout_seconds=knowledge.embedding.timeout_seconds,
    )

    base_dir = get_paths().base_dir
    index_path = Path(knowledge.index.path).expanduser() if knowledge.index.path else base_dir / "knowledge" / "index.sqlite"
    index_class = resolve_class(knowledge.index.use)
    index = index_class(index_path, embedding_model=knowledge.embedding.model)

    storage_root = Path(knowledge.storage_path).expanduser() if knowledge.storage_path else base_dir
    storage = KnowledgeFileStorage(storage_root)
    manager = KnowledgeManager(
        index=index,
        embedding=embedding,
        repository=repository,
        retrieval=knowledge.retrieval,
    )
    set_knowledge_manager(manager)
    ingestion = KnowledgeIngestionService(
        repository=repository,
        storage=storage,
        parser=parser,
        chunker=MarkdownChunker(knowledge.chunking),
        embedding=embedding,
        index=index,
        workers=knowledge.ingestion.workers,
        lease_seconds=knowledge.ingestion.lease_seconds,
    )
    return KnowledgeRuntime(manager=manager, ingestion_service=ingestion, storage=storage)
