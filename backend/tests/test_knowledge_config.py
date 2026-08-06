from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from deerflow.config.app_config import AppConfig
from deerflow.config.reload_boundary import STARTUP_ONLY_FIELDS, STARTUP_ONLY_PREFIX
from deerflow.knowledge.config import KnowledgeConfig, RetrievalConfig
from deerflow.knowledge.manager import KnowledgeManager


def test_knowledge_config_is_disabled_and_credential_free_by_default() -> None:
    config = KnowledgeConfig()

    assert config.enabled is False
    assert config.storage_path is None
    assert config.embedding.api_key is None
    assert config.retrieval.top_k == 6
    assert config.chunking.overlap_tokens < config.chunking.target_tokens


def test_knowledge_config_rejects_invalid_chunk_overlap() -> None:
    with pytest.raises(ValidationError):
        KnowledgeConfig(
            chunking={
                "target_tokens": 100,
                "overlap_tokens": 100,
                "max_tokens": 200,
            }
        )


def test_app_config_loads_knowledge_section_without_resolving_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    extensions_path = tmp_path / "extensions_config.json"
    extensions_path.write_text('{"mcpServers": {}, "skills": {}}', encoding="utf-8")
    config_path.write_text(
        yaml.safe_dump(
            {
                "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"},
                "knowledge": {
                    "enabled": False,
                    "embedding": {
                        "model": "test-embedding-model",
                        "api_key": None,
                    },
                    "retrieval": {"top_k": 4},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(extensions_path))

    config = AppConfig.from_file(str(config_path))

    assert config.knowledge.enabled is False
    assert config.knowledge.embedding.model == "test-embedding-model"
    assert config.knowledge.retrieval.top_k == 4


def test_knowledge_config_is_declared_startup_only() -> None:
    assert "knowledge" in STARTUP_ONLY_FIELDS
    description = AppConfig.model_fields["knowledge"].description or ""
    assert description.startswith(STARTUP_ONLY_PREFIX)


@pytest.mark.asyncio
async def test_manager_applies_configured_retrieval_defaults() -> None:
    captured = None

    class FakeEmbedding:
        async def embed_query(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    class FakeIndex:
        async def search(self, query):
            nonlocal captured
            captured = query
            return []

    manager = KnowledgeManager(
        index=FakeIndex(),
        embedding=FakeEmbedding(),
        retrieval=RetrievalConfig(
            top_k=4,
            vector_candidate_k=17,
            text_candidate_k=19,
            rrf_k=23,
            mmr_lambda=0.7,
        ),
    )

    await manager.search(user_id="user-1", text="alpha", knowledge_base_ids=["kb-1"])

    assert captured is not None
    assert captured.top_k == 4
    assert captured.vector_candidate_k == 17
    assert captured.text_candidate_k == 19
    assert captured.rrf_k == 23
    assert captured.mmr_lambda == 0.7
