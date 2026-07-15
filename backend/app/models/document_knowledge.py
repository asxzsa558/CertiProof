from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.config import settings
from app.core.database import Base

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # pragma: no cover - migrations install pgvector in production
    Vector = None


class KnowledgeGraphRevision(Base):
    __tablename__ = "knowledge_graph_revisions"

    id = Column(Integer, primary_key=True)
    graph_name = Column(String(63), nullable=False)
    library_name = Column(String(100), nullable=False)
    version = Column(String(80), nullable=False)
    content_sha256 = Column(String(64), nullable=False)
    node_count = Column(Integer, nullable=False, default=0)
    edge_count = Column(Integer, nullable=False, default=0)
    seeded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("graph_name", "library_name", name="uq_graph_revision_library"),
    )


class DocumentAnalysisRun(Base):
    __tablename__ = "document_analysis_runs"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    phase_id = Column(Integer, ForeignKey("phase_instances.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("task_instances.id", ondelete="CASCADE"), nullable=True, index=True)
    requested_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    run_kind = Column(String(24), nullable=False, default="initial")
    analysis_mode = Column(String(24), nullable=False, default="standard")
    parameters = Column(JSON, nullable=False, default=dict)
    status = Column(String(24), nullable=False, default="queued", index=True)
    progress = Column(JSON, nullable=False, default=dict)
    result_summary = Column(JSON, nullable=True)
    error_code = Column(String(80), nullable=True)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    run_files = relationship("DocumentRunFile", back_populates="analysis_run", cascade="all, delete-orphan")
    blocks = relationship("DocumentBlock", back_populates="analysis_run", cascade="all, delete-orphan")
    control_results = relationship("DocumentControlResult", back_populates="analysis_run", cascade="all, delete-orphan")
    findings = relationship("Finding", back_populates="document_run")


class DocumentFile(Base):
    __tablename__ = "document_files"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("task_instances.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_in_run_id = Column(Integer, ForeignKey("document_analysis_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    replaced_by_id = Column(Integer, ForeignKey("document_files.id", ondelete="SET NULL"), nullable=True)
    original_name = Column(String(500), nullable=False)
    storage_path = Column(String(1000), nullable=False)
    mime_type = Column(String(160), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    page_count = Column(Integer, nullable=False, default=0)
    parse_status = Column(String(24), nullable=False, default="queued", index=True)
    classification = Column(JSON, nullable=True)
    extraction_summary = Column(JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    runs = relationship("DocumentRunFile", back_populates="document_file", cascade="all, delete-orphan")
    blocks = relationship("DocumentBlock", back_populates="document_file", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_document_files_scope_active", "assessment_id", "task_id", "is_active"),
        Index("ix_document_files_scope_hash", "assessment_id", "sha256"),
    )


class DocumentRunFile(Base):
    __tablename__ = "document_run_files"

    analysis_run_id = Column(Integer, ForeignKey("document_analysis_runs.id", ondelete="CASCADE"), primary_key=True)
    document_file_id = Column(Integer, ForeignKey("document_files.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(24), nullable=False, default="corpus")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    analysis_run = relationship("DocumentAnalysisRun", back_populates="run_files")
    document_file = relationship("DocumentFile", back_populates="runs")


class DocumentBlock(Base):
    __tablename__ = "document_blocks"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    analysis_run_id = Column(Integer, ForeignKey("document_analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    document_file_id = Column(Integer, ForeignKey("document_files.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_block_id = Column(Integer, ForeignKey("document_blocks.id", ondelete="SET NULL"), nullable=True)
    ordinal = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    section_path = Column(JSON, nullable=False, default=list)
    block_type = Column(String(32), nullable=False)
    source = Column(String(24), nullable=False)
    source_confidence = Column(Float, nullable=False, default=1.0)
    bbox = Column(JSON, nullable=True)
    text = Column(Text, nullable=False)
    table_data = Column(JSON, nullable=True)
    content_sha256 = Column(String(64), nullable=False, index=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)
    embedding_model = Column(String(160), nullable=True)
    embedding = Column(Vector(settings.DOCUMENT_EMBEDDING_DIMENSION) if Vector else JSON, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    analysis_run = relationship("DocumentAnalysisRun", back_populates="blocks")
    document_file = relationship("DocumentFile", back_populates="blocks")

    __table_args__ = (
        UniqueConstraint("analysis_run_id", "document_file_id", "ordinal", name="uq_document_block_ordinal"),
        Index("ix_document_blocks_scope_active", "assessment_id", "is_active"),
        Index("ix_document_blocks_file_page", "document_file_id", "page_number", "ordinal"),
    )


class DocumentControlResult(Base):
    __tablename__ = "document_control_results"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.id", ondelete="CASCADE"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("task_instances.id", ondelete="SET NULL"), nullable=True, index=True)
    analysis_run_id = Column(Integer, ForeignKey("document_analysis_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    control_uid = Column(String(120), nullable=False, index=True)
    verdict = Column(String(24), nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    reason = Column(Text, nullable=False)
    missing_requirements = Column(JSON, nullable=False, default=list)
    contradictory_requirements = Column(JSON, nullable=False, default=list)
    rule_snapshot = Column(JSON, nullable=False)
    model_snapshot = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    analysis_run = relationship("DocumentAnalysisRun", back_populates="control_results")
    evidence_links = relationship("DocumentEvidenceLink", back_populates="control_result", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("analysis_run_id", "control_uid", name="uq_document_run_control"),
    )


class DocumentEvidenceLink(Base):
    __tablename__ = "document_evidence_links"

    id = Column(Integer, primary_key=True)
    control_result_id = Column(Integer, ForeignKey("document_control_results.id", ondelete="CASCADE"), nullable=False, index=True)
    document_block_id = Column(Integer, ForeignKey("document_blocks.id", ondelete="CASCADE"), nullable=False, index=True)
    requirement_uid = Column(String(160), nullable=False, index=True)
    stance = Column(String(24), nullable=False)
    confidence = Column(Float, nullable=False)
    rationale = Column(Text, nullable=False)
    rank = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    control_result = relationship("DocumentControlResult", back_populates="evidence_links")
    document_block = relationship("DocumentBlock")

    __table_args__ = (
        UniqueConstraint(
            "control_result_id",
            "document_block_id",
            "requirement_uid",
            name="uq_document_evidence_link",
        ),
    )
