"""Replace the ticket workflow with direct finding verification.

Revision ID: 012
Revises: 011
Create Date: 2026-07-16

This is intentionally a clean break. Existing assessment output is discarded while
accounts, organizations, projects, and assets are retained.
"""

from alembic import op
import sqlalchemy as sa


revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _drop_if_exists(bind, table: str) -> None:
    if table in _tables(bind):
        op.drop_table(table)


def _clear_assessment_outputs(bind) -> None:
    tables = _tables(bind)
    ordered = (
        "document_evidence_links",
        "document_control_results",
        "document_run_files",
        "document_blocks",
        "evidences",
        "findings",
        "document_files",
        "document_analysis_runs",
        "flow_events",
        "task_instances",
        "phase_instances",
        "assessments",
    )
    if "document_files" in tables:
        op.execute("UPDATE document_files SET replaced_by_id = NULL, uploaded_in_run_id = NULL")
    for table in ordered:
        if table in tables:
            op.execute(f"DELETE FROM {table}")
    if "project_assessments" in tables and "assessment_types" in tables:
        op.execute(
            "DELETE FROM project_assessments WHERE assessment_type_id IN "
            "(SELECT id FROM assessment_types WHERE code = 'dengbao')"
        )
    if "projects" in tables:
        op.execute("UPDATE projects SET compliance_score = NULL")


def upgrade() -> None:
    bind = op.get_bind()

    # Remove the rejected ticket/submission/retest model in FK order.
    for table in (
        "finding_events",
        "retest_items",
        "retest_batches",
        "remediation_submission_tickets",
        "remediation_submissions",
        "remediation_tickets",
    ):
        _drop_if_exists(bind, table)

    _clear_assessment_outputs(bind)

    op.create_table(
        "verification_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assessment_id", sa.Integer(), sa.ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phase_id", sa.Integer(), sa.ForeignKey("phase_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="queued"),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("document_file_ids", sa.JSON(), nullable=False),
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
    for column in ("id", "project_id", "assessment_id", "phase_id", "source_type", "status", "lease_owner", "lease_expires_at"):
        op.create_index(f"ix_verification_runs_{column}", "verification_runs", [column])

    op.create_table(
        "verification_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("verification_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
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
    for column in ("id", "run_id", "project_id", "finding_id", "source_type", "target", "capability", "fingerprint", "outcome"):
        op.create_index(f"ix_verification_items_{column}", "verification_items", [column])

    op.create_table(
        "finding_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("finding_id", sa.Integer(), sa.ForeignKey("findings.id", ondelete="CASCADE"), nullable=False),
        sa.Column("verification_item_id", sa.Integer(), sa.ForeignKey("verification_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("event_data", sa.JSON(), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("id", "project_id", "finding_id", "verification_item_id", "event_type"):
        op.create_index(f"ix_finding_events_{column}", "finding_events", [column])


def downgrade() -> None:
    for table in ("finding_events", "verification_items", "verification_runs"):
        _drop_if_exists(op.get_bind(), table)
