"""Remote scan nodes and their leased executions."""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.core.database import Base


class ScanNode(Base):
    __tablename__ = "scan_nodes"

    id = Column(Integer, primary_key=True, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    location = Column(String(160), nullable=True)
    description = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True)
    allowed_cidrs = Column(JSON, nullable=False, default=list)
    project_ids = Column(JSON, nullable=False, default=list)
    capabilities = Column(JSON, nullable=False, default=list)
    max_concurrency = Column(Integer, nullable=False, default=2)
    priority = Column(Integer, nullable=False, default=100)
    config_version = Column(Integer, nullable=False, default=1)
    enrollment_token_hash = Column(String(64), nullable=True)
    enrollment_expires_at = Column(DateTime(timezone=True), nullable=True)
    node_token_hash = Column(String(64), nullable=True)
    enrolled_at = Column(DateTime(timezone=True), nullable=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=True, index=True)
    runtime_info = Column(JSON, nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    executions = relationship("RemoteExecution", back_populates="node", cascade="all, delete-orphan")


class RemoteExecution(Base):
    __tablename__ = "remote_executions"

    id = Column(String(36), primary_key=True)
    scan_node_id = Column(Integer, ForeignKey("scan_nodes.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    capability = Column(String(80), nullable=False, index=True)
    target = Column(String(500), nullable=False)
    payload_envelope = Column(Text, nullable=False)
    status = Column(String(24), nullable=False, default="queued", index=True)
    control_state = Column(String(24), nullable=False, default="active")
    progress = Column(JSON, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    node = relationship("ScanNode", back_populates="executions")
