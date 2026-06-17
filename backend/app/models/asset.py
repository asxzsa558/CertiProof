from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base
import enum


class AssetType(str, enum.Enum):
    IP = "ip"
    DOMAIN = "domain"
    CLOUD_RESOURCE = "cloud_resource"


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class VerificationMethod(str, enum.Enum):
    DNS_TXT = "dns_txt"
    FILE = "file"
    PORT_RESPONSE = "port_response"
    CLOUD_API = "cloud_api"


class Asset(Base):
    __tablename__ = "assets"
    
    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    
    # Asset info
    asset_type = Column(SQLEnum(AssetType), nullable=False)
    value = Column(String(500), nullable=False)  # IP, domain, or cloud resource ID
    name = Column(String(200), nullable=True)  # Optional friendly name
    
    # Verification
    verification_status = Column(SQLEnum(VerificationStatus), default=VerificationStatus.PENDING, nullable=False)
    verification_method = Column(SQLEnum(VerificationMethod), nullable=True)
    verification_token = Column(String(200), nullable=True)  # Token for DNS TXT or file verification
    
    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    project = relationship("Project", back_populates="assets")
    scan_tasks = relationship("ScanTask", back_populates="asset", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Asset(id={self.id}, type={self.asset_type}, value={self.value})>"
