"""knowledge bases and ingestion lifecycle.

Revision ID: 0008_knowledge_bases
Revises: 0007_scheduled_run_active_index
Create Date: 2026-07-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_knowledge_bases"
down_revision: str | Sequence[str] | None = "0007_scheduled_run_active_index"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("knowledge_bases"):
        return
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("document_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_bases_user_id", "knowledge_bases", ["user_id"], unique=False)
    op.create_index("ix_knowledge_bases_status", "knowledge_bases", ["status"], unique=False)

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("media_type", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("index_revision", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_documents_knowledge_base_id", "knowledge_documents", ["knowledge_base_id"], unique=False)
    op.create_index("ix_knowledge_documents_user_id", "knowledge_documents", ["user_id"], unique=False)
    op.create_index("ix_knowledge_documents_status", "knowledge_documents", ["status"], unique=False)
    op.create_index("ix_knowledge_documents_owner_base", "knowledge_documents", ["user_id", "knowledge_base_id"], unique=False)
    op.create_index("ix_knowledge_documents_owner_hash", "knowledge_documents", ["user_id", "knowledge_base_id", "content_sha256"], unique=False)

    op.create_table(
        "knowledge_ingestion_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_ingestion_jobs_document_id", "knowledge_ingestion_jobs", ["document_id"], unique=False)
    op.create_index("ix_knowledge_ingestion_jobs_user_id", "knowledge_ingestion_jobs", ["user_id"], unique=False)
    op.create_index("ix_knowledge_ingestion_jobs_status", "knowledge_ingestion_jobs", ["status"], unique=False)
    op.create_index("ix_knowledge_ingestion_jobs_claim", "knowledge_ingestion_jobs", ["status", "next_attempt_at", "lease_expires_at"], unique=False)

    op.create_table(
        "knowledge_binding_scopes",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=128), nullable=False),
        sa.Column("strategy", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "scope_type", "scope_id", name="uq_knowledge_binding_scope_selection"),
    )
    op.create_index("ix_knowledge_binding_scopes_user_id", "knowledge_binding_scopes", ["user_id"], unique=False)

    op.create_table(
        "knowledge_bindings",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("knowledge_base_id", sa.String(length=64), nullable=False),
        sa.Column("scope_type", sa.String(length=16), nullable=False),
        sa.Column("scope_id", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "knowledge_base_id", "scope_type", "scope_id", name="uq_knowledge_binding_scope"),
    )
    op.create_index("ix_knowledge_bindings_user_id", "knowledge_bindings", ["user_id"], unique=False)
    op.create_index("ix_knowledge_bindings_knowledge_base_id", "knowledge_bindings", ["knowledge_base_id"], unique=False)


def downgrade() -> None:
    op.drop_table("knowledge_bindings")
    op.drop_table("knowledge_binding_scopes")
    op.drop_table("knowledge_ingestion_jobs")
    op.drop_table("knowledge_documents")
    op.drop_table("knowledge_bases")
