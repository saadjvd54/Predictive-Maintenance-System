"""PharmaPredict AI — Phase 9 Human-Approved Commissioning Models.

Manages the lifecycle of OPC UA tag discovery imports, candidate signal mapping review,
multi-criteria validation, human approval/rejection workflows, and activation into
production MachineSignal configurations with immutable audit logging.
"""
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Float,
    Integer,
    Boolean,
    Text,
    JSON,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.extensions import db


def generate_uuid() -> str:
    return str(uuid.uuid4())


class CommissioningStatus(str, Enum):
    """Lifecycle statuses for a commissioning session and individual candidates."""
    DISCOVERED = "DISCOVERED"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVATED = "ACTIVATED"
    CANCELLED = "CANCELLED"

    @classmethod
    def all_statuses(cls) -> List[str]:
        return [c.value for c in cls]


class CommissioningSession(db.Model):
    """Represents a human-in-the-loop industrial equipment commissioning session."""
    __tablename__ = "commissioning_sessions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    organization_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    machine_id = Column(
        String(36),
        ForeignKey("machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    session_name = Column(String(255), nullable=False)
    source_endpoint_url = Column(String(500), nullable=True)
    status = Column(
        String(50),
        default=CommissioningStatus.PENDING_REVIEW.value,
        nullable=False,
        index=True
    )
    discovered_nodes_count = Column(Integer, default=0, nullable=False)
    mapped_candidates_count = Column(Integer, default=0, nullable=False)
    unmapped_candidates_count = Column(Integer, default=0, nullable=False)
    approved_count = Column(Integer, default=0, nullable=False)
    rejected_count = Column(Integer, default=0, nullable=False)
    activated_count = Column(Integer, default=0, nullable=False)

    metadata_json = Column(JSON, default=dict, nullable=False)
    audit_log = Column(JSON, default=list, nullable=False)

    created_by = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    activated_at = Column(DateTime(timezone=True), nullable=True)
    activated_by = Column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )

    # Relationships
    candidates = relationship(
        "DiscoveredSignalCandidate",
        back_populates="session",
        cascade="all, delete-orphan",
        lazy=True
    )
    machine = relationship("Machine")
    organization = relationship("Organization")
    creator = relationship("User", foreign_keys=[created_by])
    activator = relationship("User", foreign_keys=[activated_by])

    def to_dict(self, include_candidates: bool = False) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "organization_id": self.organization_id,
            "machine_id": self.machine_id,
            "machine_name": getattr(self.machine, "equipment_name", getattr(self.machine, "name", None)) if self.machine else None,
            "asset_code": self.machine.asset_code if self.machine else None,
            "session_name": self.session_name,
            "source_endpoint_url": self.source_endpoint_url,
            "status": self.status,
            "discovered_nodes_count": self.discovered_nodes_count,
            "mapped_candidates_count": self.mapped_candidates_count,
            "unmapped_candidates_count": self.unmapped_candidates_count,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "activated_count": self.activated_count,
            "metadata": self.metadata_json or {},
            "audit_log": self.audit_log or [],
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "activated_by": self.activated_by,
        }
        if include_candidates:
            data["candidates"] = [c.to_dict() for c in self.candidates]
        return data


class DiscoveredSignalCandidate(db.Model):
    """Candidate signal mapping derived from Phase 8 discovery awaiting engineer review."""
    __tablename__ = "discovered_signal_candidates"
    __table_args__ = (
        UniqueConstraint("session_id", "source_node_id", name="uq_session_source_node"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    session_id = Column(
        String(36),
        ForeignKey("commissioning_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    organization_id = Column(
        String(36),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    machine_id = Column(
        String(36),
        ForeignKey("machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Discovered OPC UA Node Metadata
    source_node_id = Column(String(255), nullable=False, index=True)
    browse_name = Column(String(255), nullable=True)
    display_name = Column(String(255), nullable=True)
    source_data_type = Column(String(50), nullable=True)
    access_level = Column(String(50), nullable=True)
    source_unit = Column(String(50), nullable=True)

    # Classification & AI Suggestions
    suggested_category = Column(String(50), nullable=True)
    confidence_level = Column(String(20), default="UNMAPPED", nullable=False)
    confidence_score = Column(Float, default=0.0, nullable=False)
    suggested_signal_code = Column(String(100), nullable=True)

    # Configured Target Mapping (Human Reviewable & Correctable)
    target_signal_definition_id = Column(
        String(36),
        ForeignKey("signal_definitions.id", ondelete="SET NULL"),
        nullable=True
    )
    custom_name = Column(String(255), nullable=True)
    component_id = Column(
        String(36),
        ForeignKey("machine_components.id", ondelete="SET NULL"),
        nullable=True
    )
    engineering_unit = Column(String(50), nullable=True)
    scaling_factor = Column(Float, default=1.0, nullable=False)
    offset = Column(Float, default=0.0, nullable=False)
    sampling_interval_ms = Column(Integer, default=1000, nullable=False)

    # Operational Thresholds (from Pilot/Simulator Profile)
    warning_min = Column(Float, nullable=True)
    warning_max = Column(Float, nullable=True)
    critical_min = Column(Float, nullable=True)
    critical_max = Column(Float, nullable=True)

    # Workflow Status
    is_mapped = Column(Boolean, default=True, nullable=False, index=True)
    status = Column(
        String(50),
        default=CommissioningStatus.PENDING_REVIEW.value,
        nullable=False,
        index=True
    )
    registered_machine_signal_id = Column(
        String(36),
        ForeignKey("machine_signals.id", ondelete="SET NULL"),
        nullable=True
    )

    # Validation & Audit History
    review_history = Column(JSON, default=list, nullable=False)
    validation_errors = Column(JSON, default=list, nullable=False)
    validation_warnings = Column(JSON, default=list, nullable=False)
    is_valid = Column(Boolean, default=False, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    session = relationship("CommissioningSession", back_populates="candidates")
    machine = relationship("Machine")
    signal_definition = relationship("SignalDefinition")
    component = relationship("MachineComponent")
    registered_signal = relationship("MachineSignal")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "organization_id": self.organization_id,
            "machine_id": self.machine_id,
            "source_node_id": self.source_node_id,
            "browse_name": self.browse_name,
            "display_name": self.display_name,
            "source_data_type": self.source_data_type,
            "access_level": self.access_level,
            "source_unit": self.source_unit,
            "suggested_category": self.suggested_category,
            "confidence_level": self.confidence_level,
            "confidence_score": self.confidence_score,
            "suggested_signal_code": self.suggested_signal_code,
            "target_signal_definition_id": self.target_signal_definition_id,
            "signal_definition_code": self.signal_definition.signal_code if self.signal_definition else None,
            "signal_definition_name": self.signal_definition.name if self.signal_definition else None,
            "custom_name": self.custom_name,
            "component_id": self.component_id,
            "component_name": self.component.component_name if self.component else None,
            "engineering_unit": self.engineering_unit,
            "scaling_factor": self.scaling_factor,
            "offset": self.offset,
            "sampling_interval_ms": self.sampling_interval_ms,
            "warning_min": self.warning_min,
            "warning_max": self.warning_max,
            "critical_min": self.critical_min,
            "critical_max": self.critical_max,
            "is_mapped": self.is_mapped,
            "status": self.status,
            "registered_machine_signal_id": self.registered_machine_signal_id,
            "review_history": self.review_history or [],
            "validation_errors": self.validation_errors or [],
            "validation_warnings": self.validation_warnings or [],
            "is_valid": self.is_valid,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
