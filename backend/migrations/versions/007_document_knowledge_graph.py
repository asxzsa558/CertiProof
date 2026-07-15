"""Add the document knowledge, evidence and vector data model.

Revision ID: 007
Revises: 006
Create Date: 2026-07-14
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    if postgres:
        op.execute("CREATE EXTENSION IF NOT EXISTS age")
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("LOAD 'age'")
        op.execute("SET search_path = ag_catalog, \"$user\", public")
        exists = bind.execute(sa.text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'certiproof'")).scalar()
        if not exists:
            op.execute("SELECT ag_catalog.create_graph('certiproof')")
        op.execute('SET search_path = public, ag_catalog, "$user"')

    tables = _tables()
    if "knowledge_graph_revisions" not in tables:
        op.create_table(
            "knowledge_graph_revisions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("graph_name", sa.String(63), nullable=False),
            sa.Column("library_name", sa.String(100), nullable=False),
            sa.Column("version", sa.String(80), nullable=False),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("edge_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("seeded_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("graph_name", "library_name", name="uq_graph_revision_library"),
        )

    if "document_analysis_runs" not in tables:
        op.create_table(
            "document_analysis_runs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("phase_id", sa.Integer(), sa.ForeignKey("phase_instances.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_instances.id", ondelete="CASCADE"), nullable=True),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("run_kind", sa.String(24), nullable=False, server_default="initial"),
            sa.Column("analysis_mode", sa.String(24), nullable=False, server_default="standard"),
            sa.Column("parameters", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
            sa.Column("progress", sa.JSON(), nullable=False),
            sa.Column("result_summary", sa.JSON(), nullable=True),
            sa.Column("error_code", sa.String(80), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if "document_files" not in tables:
        op.create_table(
            "document_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_instances.id", ondelete="SET NULL"), nullable=True),
            sa.Column("uploaded_in_run_id", sa.Integer(), sa.ForeignKey("document_analysis_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("replaced_by_id", sa.Integer(), sa.ForeignKey("document_files.id", ondelete="SET NULL"), nullable=True),
            sa.Column("original_name", sa.String(500), nullable=False),
            sa.Column("storage_path", sa.String(1000), nullable=False),
            sa.Column("mime_type", sa.String(160), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("parse_status", sa.String(24), nullable=False, server_default="queued"),
            sa.Column("classification", sa.JSON(), nullable=True),
            sa.Column("extraction_summary", sa.JSON(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if "document_run_files" not in tables:
        op.create_table(
            "document_run_files",
            sa.Column("analysis_run_id", sa.Integer(), sa.ForeignKey("document_analysis_runs.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("document_file_id", sa.Integer(), sa.ForeignKey("document_files.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("role", sa.String(24), nullable=False, server_default="corpus"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )

    if "document_blocks" not in tables:
        op.create_table(
            "document_blocks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("analysis_run_id", sa.Integer(), sa.ForeignKey("document_analysis_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document_file_id", sa.Integer(), sa.ForeignKey("document_files.id", ondelete="CASCADE"), nullable=False),
            sa.Column("parent_block_id", sa.Integer(), sa.ForeignKey("document_blocks.id", ondelete="SET NULL"), nullable=True),
            sa.Column("ordinal", sa.Integer(), nullable=False),
            sa.Column("page_number", sa.Integer(), nullable=True),
            sa.Column("section_path", sa.JSON(), nullable=False),
            sa.Column("block_type", sa.String(32), nullable=False),
            sa.Column("source", sa.String(24), nullable=False),
            sa.Column("source_confidence", sa.Float(), nullable=False, server_default="1"),
            sa.Column("bbox", sa.JSON(), nullable=True),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("table_data", sa.JSON(), nullable=True),
            sa.Column("content_sha256", sa.String(64), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("embedding_model", sa.String(160), nullable=True),
            sa.Column("embedding", Vector(1024), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("analysis_run_id", "document_file_id", "ordinal", name="uq_document_block_ordinal"),
        )

    if "document_control_results" not in tables:
        op.create_table(
            "document_control_results",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("task_id", sa.Integer(), sa.ForeignKey("task_instances.id", ondelete="SET NULL"), nullable=True),
            sa.Column("analysis_run_id", sa.Integer(), sa.ForeignKey("document_analysis_runs.id", ondelete="CASCADE"), nullable=False),
            sa.Column("control_uid", sa.String(120), nullable=False),
            sa.Column("verdict", sa.String(24), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("missing_requirements", sa.JSON(), nullable=False),
            sa.Column("contradictory_requirements", sa.JSON(), nullable=False),
            sa.Column("rule_snapshot", sa.JSON(), nullable=False),
            sa.Column("model_snapshot", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("analysis_run_id", "control_uid", name="uq_document_run_control"),
        )

    if "document_evidence_links" not in tables:
        op.create_table(
            "document_evidence_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("control_result_id", sa.Integer(), sa.ForeignKey("document_control_results.id", ondelete="CASCADE"), nullable=False),
            sa.Column("document_block_id", sa.Integer(), sa.ForeignKey("document_blocks.id", ondelete="CASCADE"), nullable=False),
            sa.Column("requirement_uid", sa.String(160), nullable=False),
            sa.Column("stance", sa.String(24), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("control_result_id", "document_block_id", "requirement_uid", name="uq_document_evidence_link"),
        )

    finding_columns = {column["name"] for column in sa.inspect(bind).get_columns("findings")}
    if "document_run_id" not in finding_columns:
        op.add_column("findings", sa.Column(
            "document_run_id",
            sa.Integer(),
            sa.ForeignKey("document_analysis_runs.id", ondelete="SET NULL"),
            nullable=True,
        ))
    if not next(column for column in sa.inspect(bind).get_columns("findings") if column["name"] == "scan_task_id")["nullable"]:
        op.alter_column("findings", "scan_task_id", existing_type=sa.Integer(), nullable=True)
    finding_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("findings")}
    if "ix_findings_document_run_id" not in finding_indexes:
        op.create_index("ix_findings_document_run_id", "findings", ["document_run_id"])

    indexes = {
        "document_analysis_runs": tuple((f"ix_document_analysis_runs_{column}", (column,)) for column in ("project_id", "assessment_id", "phase_id", "task_id", "status")),
        "document_files": (
            *((f"ix_document_files_{column}", (column,)) for column in ("project_id", "assessment_id", "task_id", "uploaded_in_run_id", "sha256", "parse_status", "is_active")),
            ("ix_document_files_scope_active", ("assessment_id", "task_id", "is_active")),
            ("ix_document_files_scope_hash", ("assessment_id", "sha256")),
        ),
        "document_blocks": (
            *((f"ix_document_blocks_{column}", (column,)) for column in ("project_id", "assessment_id", "analysis_run_id", "document_file_id", "content_sha256", "is_active")),
            ("ix_document_blocks_scope_active", ("assessment_id", "is_active")),
            ("ix_document_blocks_file_page", ("document_file_id", "page_number", "ordinal")),
        ),
        "document_control_results": tuple((f"ix_document_control_results_{column}", (column,)) for column in ("project_id", "assessment_id", "task_id", "analysis_run_id", "control_uid", "verdict")),
        "document_evidence_links": tuple((f"ix_document_evidence_links_{column}", (column,)) for column in ("control_result_id", "document_block_id", "requirement_uid")),
    }
    inspector = sa.inspect(bind)
    for table, groups in indexes.items():
        existing = {item["name"] for item in inspector.get_indexes(table)}
        for name, columns in groups:
            if name not in existing:
                op.create_index(name, table, list(columns))

    if postgres:
        existing = {item["name"] for item in sa.inspect(bind).get_indexes("document_blocks")}
        if "ix_document_blocks_embedding_hnsw" not in existing:
            op.create_index(
                "ix_document_blocks_embedding_hnsw",
                "document_blocks",
                ["embedding"],
                postgresql_using="hnsw",
                postgresql_ops={"embedding": "vector_cosine_ops"},
            )


def downgrade() -> None:
    finding_columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("findings")}
    if "document_run_id" in finding_columns:
        finding_indexes = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes("findings")}
        if "ix_findings_document_run_id" in finding_indexes:
            op.drop_index("ix_findings_document_run_id", table_name="findings")
        op.drop_column("findings", "document_run_id")
    for table in (
        "document_evidence_links",
        "document_control_results",
        "document_blocks",
        "document_run_files",
        "document_files",
        "document_analysis_runs",
        "knowledge_graph_revisions",
    ):
        if table in _tables():
            op.drop_table(table)
