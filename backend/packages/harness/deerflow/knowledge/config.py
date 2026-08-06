from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ParserConfig(BaseModel):
    use: str = "deerflow.knowledge.parsing.markitdown:MarkItDownParser"
    allowed_extensions: list[str] = Field(default_factory=lambda: ["md", "txt", "pdf", "docx", "pptx", "xlsx"])


class ChunkingConfig(BaseModel):
    target_tokens: int = Field(default=500, ge=1)
    overlap_tokens: int = Field(default=80, ge=0)
    max_tokens: int = Field(default=900, ge=1)
    token_counting: Literal["tiktoken"] = "tiktoken"

    @model_validator(mode="after")
    def validate_token_windows(self) -> ChunkingConfig:
        if self.overlap_tokens >= self.target_tokens:
            raise ValueError("overlap_tokens must be smaller than target_tokens")
        if self.max_tokens < self.target_tokens:
            raise ValueError("max_tokens must be greater than or equal to target_tokens")
        return self


class EmbeddingConfig(BaseModel):
    use: str = "langchain_openai:OpenAIEmbeddings"
    model: str = "text-embedding-3-small"
    api_key: str | None = None
    batch_size: int = Field(default=64, ge=1, le=2048)
    timeout_seconds: float = Field(default=60.0, gt=0)


class IndexConfig(BaseModel):
    use: str = "deerflow.knowledge.retrieval.local:LocalHybridIndex"
    path: str | None = None


class RetrievalConfig(BaseModel):
    top_k: int = Field(default=6, ge=1, le=50)
    vector_candidate_k: int = Field(default=30, ge=1, le=1000)
    text_candidate_k: int = Field(default=30, ge=1, le=1000)
    rrf_k: int = Field(default=60, ge=1)
    mmr_lambda: float = Field(default=0.8, ge=0.0, le=1.0)
    max_context_tokens: int = Field(default=4000, ge=1)


class IngestionConfig(BaseModel):
    workers: int = Field(default=2, ge=1, le=32)
    lease_seconds: int = Field(default=120, ge=10)
    max_attempts: int = Field(default=3, ge=1, le=20)


class KnowledgeConfig(BaseModel):
    """Startup-only knowledge-base configuration.

    Component classes are described here but are not imported or constructed
    during config validation. Consequently the default disabled configuration
    remains safe when no embedding credentials are installed.
    """

    enabled: bool = False
    storage_path: str | None = None
    parser: ParserConfig = Field(default_factory=ParserConfig)
    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    index: IndexConfig = Field(default_factory=IndexConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    ingestion: IngestionConfig = Field(default_factory=IngestionConfig)
