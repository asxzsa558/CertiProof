"""Replace loose remediation state with a traceable retest closure model.

Revision ID: 011
Revises: 010
Create Date: 2026-07-15
"""

from alembic import op
import sqlalchemy as sa


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _index(name: str, table: str, columns: list[str]) -> None:
    bind = op.get_bind()
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(table)}
    if name not in indexes:
        op.create_index(name, table, columns)


def _normalize_status_columns(bind) -> None:
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE findings ALTER COLUMN status DROP DEFAULT")
        op.execute("ALTER TABLE findings ALTER COLUMN status TYPE VARCHAR(32) USING lower(status::text)")
        op.execute("UPDATE findings SET status = CASE status WHEN 'resolved' THEN 'fixed' WHEN 'in_progress' THEN 'open' ELSE status END")
        op.execute("ALTER TABLE findings ALTER COLUMN status SET DEFAULT 'open'")
        op.execute("DROP TYPE IF EXISTS findingstatus")

        op.execute("ALTER TABLE remediation_tickets ALTER COLUMN status DROP DEFAULT")
        op.execute("ALTER TABLE remediation_tickets ALTER COLUMN status TYPE VARCHAR(32) USING lower(status::text)")
        op.execute("UPDATE remediation_tickets SET status = CASE status WHEN 'resolved' THEN 'ready_for_retest' ELSE status END")
        op.execute("ALTER TABLE remediation_tickets ALTER COLUMN status SET DEFAULT 'open'")
        op.execute("DROP TYPE IF EXISTS remediationstatus")
        return

    op.execute("UPDATE findings SET status = 'fixed' WHERE lower(status) = 'resolved'")
    op.execute("UPDATE findings SET status = 'open' WHERE lower(status) = 'in_progress'")
    op.execute("UPDATE remediation_tickets SET status = 'ready_for_retest' WHERE lower(status) = 'resolved'")


def upgrade() -> None:
    bind = op.get_bind()
    finding_columns = _columns(bind, "findings")
    for name, column in {
        "fingerprint": sa.Column("fingerprint", sa.String(64), nullable=True),
        "source_type": sa.Column("source_type", sa.String(24), nullable=False, server_default="manual"),
        "source_key": sa.Column("source_key", sa.String(120), nullable=True),
        "scope_key": sa.Column("scope_key", sa.String(500), nullable=True),
    }.items():
        if name not in finding_columns:
            op.add_column("findings", column)
    for column in ("fingerprint", "source_type", "source_key", "scope_key"):
        _index(f"ix_findings_{column}", "findings", [column])

    _normalize_status_columns(bind)

    tables = _tables(bind)
    if "remediation_submissions" not in tables:
        op.create_table(
            "remediation_submissions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_type", sa.String(24), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("document_file_ids", sa.JSON(), nullable=False),
            sa.Column("evidence_ids", sa.JSON(), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("submitted_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_remediation_submissions_id", "remediation_submissions", ["id"])
        op.create_index("ix_remediation_submissions_project_id", "remediation_submissions", ["project_id"])
        op.create_index("ix_remediation_submissions_source_type", "remediation_submissions", ["source_type"])

    if "remediation_submission_tickets" not in tables:
        op.create_table(
            "remediation_submission_tickets",
            sa.Column("submission_id", sa.Integer(), sa.ForeignKey("remediation_submissions.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("remediation_tickets.id", ondelete="CASCADE"), primary_key=True),
        )

    if "retest_batches" not in tables:
        op.create_table(
            "retest_batches",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=True),
            sa.Column("phase_id", sa.Integer(), sa.ForeignKey("phase_instances.id", ondelete="SET NULL"), nullable=True),
            sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
            sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("credential_envelope", sa.Text(), nullable=True),
            sa.Column("summary", sa.JSON(), nullable=False),
            sa.Column("lease_owner", sa.String(128), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        for column in ("id", "project_id", "assessment_id", "phase_id", "status", "lease_owner", "lease_expires_at"):
            op.create_index(f"ix_retest_batches_{column}", "retest_batches", [column])

    if "retest_items" not in tables:
        op.create_table(
            "retest_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("batch_id", sa.Integer(), sa.ForeignKey("retest_batches.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("remediation_tickets.id", ondelete="CASCADE"), nullable=False),
            sa.Column("finding_id", sa.Integer(), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("submission_id", sa.Integer(), sa.ForeignKey("remediation_submissions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_type", sa.String(24), nullable=False),
            sa.Column("target", sa.String(500), nullable=True),
            sa.Column("capability", sa.String(120), nullable=True),
            sa.Column("fingerprint", sa.String(64), nullable=False),
            sa.Column("outcome", sa.String(24), nullable=False, server_default="queued"),
            sa.Column("baseline_scan_task_id", sa.Integer(), sa.ForeignKey("scan_tasks.id", ondelete="SET NULL"), nullable=True),
            sa.Column("current_scan_task_id", sa.Integer(), sa.ForeignKey("scan_tasks.id", ondelete="SET NULL"), nullable=True),
            sa.Column("baseline_document_run_id", sa.Integer(), sa.ForeignKey("document_analysis_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("current_document_run_id", sa.Integer(), sa.ForeignKey("document_analysis_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("baseline_observation", sa.JSON(), nullable=False),
            sa.Column("current_observation", sa.JSON(), nullable=False),
            sa.Column("comparison", sa.JSON(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        for column in ("id", "batch_id", "project_id", "ticket_id", "finding_id", "submission_id", "source_type", "target", "capability", "fingerprint", "outcome"):
            op.create_index(f"ix_retest_items_{column}", "retest_items", [column])

    if "finding_events" not in tables:
        op.create_table(
            "finding_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("finding_id", sa.Integer(), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ticket_id", sa.Integer(), sa.ForeignKey("remediation_tickets.id", ondelete="CASCADE"), nullable=True),
            sa.Column("submission_id", sa.Integer(), sa.ForeignKey("remediation_submissions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("retest_item_id", sa.Integer(), sa.ForeignKey("retest_items.id", ondelete="SET NULL"), nullable=True),
            sa.Column("event_type", sa.String(40), nullable=False),
            sa.Column("event_data", sa.JSON(), nullable=False),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        for column in ("id", "project_id", "finding_id", "ticket_id", "event_type"):
            op.create_index(f"ix_finding_events_{column}", "finding_events", [column])


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    for table in ("finding_events", "retest_items", "retest_batches", "remediation_submission_tickets", "remediation_submissions"):
        if table in tables:
            op.drop_table(table)
    finding_columns = _columns(bind, "findings")
    for column in ("scope_key", "source_key", "source_type", "fingerprint"):
        if column in finding_columns:
            op.drop_column("findings", column)
