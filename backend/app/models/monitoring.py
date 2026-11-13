import uuid
from datetime import datetime, timezone
from app.extensions import db


def generate_uuid():
    return str(uuid.uuid4())


class MonitoringState:
    """Standardized lifecycle states for equipment monitoring."""
    NOT_CONFIGURED = "NOT_CONFIGURED"
    READY = "READY"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    DISCONNECTED = "DISCONNECTED"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"

    ALL_STATES = [
        NOT_CONFIGURED,
        READY,
        ACTIVATING,
        ACTIVE,
        DEGRADED,
        DISCONNECTED,
        STOPPING,
        STOPPED,
        ERROR,
    ]


class SignalFreshness:
    """Freshness classification for telemetry signals."""
    FRESH = "FRESH"
    DELAYED = "DELAYED"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class MonitoringSession(db.Model):
    """Tracks a monitoring activation session, desired state vs observed gateway state."""
    __tablename__ = "monitoring_sessions"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    machine_id = db.Column(
        db.String(36),
        db.ForeignKey("machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    connector_id = db.Column(db.String(100), nullable=True)
    gateway_id = db.Column(db.String(100), nullable=True, default="gw-default")
    requested_by = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    desired_state = db.Column(db.String(50), nullable=False, default=MonitoringState.STOPPED)
    observed_state = db.Column(db.String(50), nullable=False, default=MonitoringState.STOPPED)
    status_reason = db.Column(db.Text, nullable=True)
    mapping_version = db.Column(db.Integer, nullable=False, default=1)
    activated_at = db.Column(db.DateTime(timezone=True), nullable=True)
    stopped_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    machine = db.relationship("Machine", backref=db.backref("monitoring_sessions", lazy=True, cascade="all, delete-orphan"))
    user = db.relationship("User")
    subscriptions = db.relationship("SubscriptionStatus", back_populates="monitoring_session", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "machine_id": self.machine_id,
            "connector_id": self.connector_id,
            "gateway_id": self.gateway_id,
            "requested_by": self.requested_by,
            "desired_state": self.desired_state,
            "observed_state": self.observed_state,
            "status_reason": self.status_reason,
            "mapping_version": self.mapping_version,
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class SubscriptionStatus(db.Model):
    """Tracks active OPC UA subscription per mapped signal."""
    __tablename__ = "subscription_status"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    monitoring_session_id = db.Column(
        db.String(36),
        db.ForeignKey("monitoring_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    signal_id = db.Column(
        db.String(36),
        db.ForeignKey("machine_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    subscription_identifier = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), nullable=False, default="PENDING")  # PENDING, SUBSCRIBED, FAILED, CANCELLED
    revised_sampling_interval = db.Column(db.Float, nullable=True)
    last_received_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    monitoring_session = db.relationship("MonitoringSession", back_populates="subscriptions")
    signal = db.relationship("MachineSignal")

    def to_dict(self):
        return {
            "id": self.id,
            "monitoring_session_id": self.monitoring_session_id,
            "signal_id": self.signal_id,
            "signal_name": self.signal.custom_name or (self.signal.signal_definition.name if self.signal and self.signal.signal_definition else None),
            "subscription_identifier": self.subscription_identifier,
            "status": self.status,
            "revised_sampling_interval": self.revised_sampling_interval,
            "last_received_at": self.last_received_at.isoformat() if self.last_received_at else None,
            "last_error": self.last_error,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class GatewayHealthRecord(db.Model):
    """Gateway health status, queue depth, and buffer metrics."""
    __tablename__ = "gateway_health"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    gateway_id = db.Column(db.String(100), unique=True, nullable=False, index=True)
    last_heartbeat = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    connection_status = db.Column(db.String(50), nullable=False, default="ONLINE")
    queue_depth = db.Column(db.Integer, default=0, nullable=False)
    buffered_readings = db.Column(db.Integer, default=0, nullable=False)
    dropped_readings = db.Column(db.Integer, default=0, nullable=False)
    last_error = db.Column(db.Text, nullable=True)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    def to_dict(self):
        return {
            "gateway_id": self.gateway_id,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "connection_status": self.connection_status,
            "queue_depth": self.queue_depth,
            "buffered_readings": self.buffered_readings,
            "dropped_readings": self.dropped_readings,
            "last_error": self.last_error,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class IngestionBatch(db.Model):
    """Audit log of batches ingested by the backend from gateways."""
    __tablename__ = "ingestion_batches"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    gateway_id = db.Column(db.String(100), nullable=False, index=True)
    batch_identifier = db.Column(db.String(100), unique=True, nullable=False, index=True)
    received_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    accepted_count = db.Column(db.Integer, default=0, nullable=False)
    rejected_count = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(50), default="ACCEPTED", nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "gateway_id": self.gateway_id,
            "batch_identifier": self.batch_identifier,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "status": self.status,
        }


class SignalReading(db.Model):
    """Time-series sensor readings storage table with TimescaleDB compatibility."""
    __tablename__ = "signal_readings"
    __table_args__ = (
        db.Index("ix_readings_machine_time", "machine_id", "source_timestamp"),
        db.Index("ix_readings_signal_time", "signal_id", "source_timestamp"),
        db.Index("ix_readings_org_time", "organization_id", "source_timestamp"),
    )

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    event_id = db.Column(db.String(128), unique=True, nullable=False, index=True)  # Deduplication key
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    machine_id = db.Column(
        db.String(36),
        db.ForeignKey("machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    signal_id = db.Column(
        db.String(36),
        db.ForeignKey("machine_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    connector_id = db.Column(db.String(100), nullable=True)
    gateway_id = db.Column(db.String(100), nullable=True, default="gw-default")
    mapping_version = db.Column(db.Integer, default=1, nullable=False)

    # Timestamps
    source_timestamp = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    server_timestamp = db.Column(db.DateTime(timezone=True), nullable=True)
    gateway_received_at = db.Column(db.DateTime(timezone=True), nullable=True)
    ingestion_timestamp = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Values
    source_value = db.Column(db.String(255), nullable=True)
    normalized_value = db.Column(db.Float, nullable=True)
    raw_value_numeric = db.Column(db.Float, nullable=True)
    raw_value_boolean = db.Column(db.Boolean, nullable=True)
    raw_value_string = db.Column(db.String(255), nullable=True)

    # Metadata & Quality
    source_unit = db.Column(db.String(50), nullable=True)
    normalized_unit = db.Column(db.String(50), nullable=True)
    quality_code = db.Column(db.String(50), default="Good", nullable=False)
    normalization_status = db.Column(db.String(50), default="NORMALIZED", nullable=False)
    sampling_interval_ms = db.Column(db.Integer, default=1000, nullable=True)
    simulator_flag = db.Column(db.Boolean, default=True, nullable=False)

    # Relationships
    signal = db.relationship("MachineSignal")
    machine = db.relationship("Machine")

    def to_dict(self):
        return {
            "id": self.id,
            "event_id": self.event_id,
            "organization_id": self.organization_id,
            "machine_id": self.machine_id,
            "signal_id": self.signal_id,
            "signal_name": self.signal.custom_name or (self.signal.signal_definition.name if self.signal and self.signal.signal_definition else None),
            "signal_group": self.signal.signal_definition.signal_group if self.signal and self.signal.signal_definition else None,
            "connector_id": self.connector_id,
            "mapping_version": self.mapping_version,
            "source_timestamp": self.source_timestamp.isoformat() if self.source_timestamp else None,
            "server_timestamp": self.server_timestamp.isoformat() if self.server_timestamp else None,
            "ingestion_timestamp": self.ingestion_timestamp.isoformat() if self.ingestion_timestamp else None,
            "source_value": self.source_value,
            "normalized_value": self.normalized_value,
            "raw_value_numeric": self.raw_value_numeric,
            "raw_value_boolean": self.raw_value_boolean,
            "source_unit": self.source_unit,
            "normalized_unit": self.normalized_unit,
            "quality_code": self.quality_code,
            "normalization_status": self.normalization_status,
            "sampling_interval_ms": self.sampling_interval_ms,
            "simulator_flag": self.simulator_flag,
        }


# ==============================================================================
# PHASE 3 STEP 3.1: RETENTION, AGGREGATION & STORAGE AUDITING MODELS
# ==============================================================================

class RetentionPolicy(db.Model):
    """Configurable telemetry retention policy per organization or machine.
    
    Default behavior: If no active policy exists, NO telemetry deletion is performed.
    """
    __tablename__ = "retention_policies"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    machine_id = db.Column(
        db.String(36),
        db.ForeignKey("machines.id", ondelete="CASCADE"),
        nullable=True,
        index=True
    )
    raw_retention_days = db.Column(db.Integer, nullable=False, default=90)
    aggregate_retention_days = db.Column(db.Integer, nullable=False, default=365)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    archive_before_delete = db.Column(db.Boolean, default=True, nullable=False)
    batch_size = db.Column(db.Integer, default=500, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    created_by_user_id = db.Column(db.String(36), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "machine_id": self.machine_id,
            "raw_retention_days": self.raw_retention_days,
            "aggregate_retention_days": self.aggregate_retention_days,
            "is_active": self.is_active,
            "archive_before_delete": self.archive_before_delete,
            "batch_size": self.batch_size,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by_user_id": self.created_by_user_id,
        }


class RetentionExecution(db.Model):
    """Audit record of retention job executions, tracking records scanned, aggregated, deleted, and duration."""
    __tablename__ = "retention_executions"

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    policy_id = db.Column(
        db.String(36),
        db.ForeignKey("retention_policies.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    organization_id = db.Column(db.String(36), nullable=False, index=True)
    machine_id = db.Column(db.String(36), nullable=True, index=True)
    started_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    dry_run = db.Column(db.Boolean, default=False, nullable=False)
    cutoff_timestamp = db.Column(db.DateTime(timezone=True), nullable=False)
    records_scanned = db.Column(db.Integer, default=0, nullable=False)
    records_aggregated = db.Column(db.Integer, default=0, nullable=False)
    records_deleted = db.Column(db.Integer, default=0, nullable=False)
    batch_count = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(50), default="IN_PROGRESS", nullable=False)
    error_message = db.Column(db.Text, nullable=True)
    executed_by = db.Column(db.String(100), default="SYSTEM", nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "policy_id": self.policy_id,
            "organization_id": self.organization_id,
            "machine_id": self.machine_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "dry_run": self.dry_run,
            "cutoff_timestamp": self.cutoff_timestamp.isoformat() if self.cutoff_timestamp else None,
            "records_scanned": self.records_scanned,
            "records_aggregated": self.records_aggregated,
            "records_deleted": self.records_deleted,
            "batch_count": self.batch_count,
            "status": self.status,
            "error_message": self.error_message,
            "executed_by": self.executed_by,
        }


class SignalReadingAggregate(db.Model):
    """Historical aggregate rollups (e.g. hourly buckets) preserved before raw telemetry pruning."""
    __tablename__ = "signal_reading_aggregates"
    __table_args__ = (
        db.Index("ix_agg_machine_bucket", "machine_id", "bucket_start"),
        db.Index("ix_agg_signal_bucket", "signal_id", "bucket_start"),
        db.UniqueConstraint("signal_id", "bucket_start", "bucket_resolution", name="uq_signal_bucket_resolution"),
    )

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    machine_id = db.Column(
        db.String(36),
        db.ForeignKey("machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    signal_id = db.Column(
        db.String(36),
        db.ForeignKey("machine_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    bucket_start = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    bucket_end = db.Column(db.DateTime(timezone=True), nullable=False)
    bucket_resolution = db.Column(db.String(20), default="1h", nullable=False)

    min_value = db.Column(db.Float, nullable=True)
    max_value = db.Column(db.Float, nullable=True)
    avg_value = db.Column(db.Float, nullable=True)
    first_value = db.Column(db.Float, nullable=True)
    last_value = db.Column(db.Float, nullable=True)
    reading_count = db.Column(db.Integer, default=0, nullable=False)
    quality_summary = db.Column(db.String(50), default="Good", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    signal = db.relationship("MachineSignal")
    machine = db.relationship("Machine")

    def to_dict(self):
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "machine_id": self.machine_id,
            "signal_id": self.signal_id,
            "bucket_start": self.bucket_start.isoformat() if self.bucket_start else None,
            "bucket_end": self.bucket_end.isoformat() if self.bucket_end else None,
            "bucket_resolution": self.bucket_resolution,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "avg_value": self.avg_value,
            "first_value": self.first_value,
            "last_value": self.last_value,
            "reading_count": self.reading_count,
            "quality_summary": self.quality_summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ==============================================================================
# PHASE 3 STEP 3.2: SIGNAL OPERATIONAL THRESHOLDS MODEL
# ==============================================================================

class SignalThreshold(db.Model):
    """Configurable operational warning and critical threshold envelopes for equipment signals.
    
    Visualization thresholds allow operators to detect process drift.
    Note: Must not be confused with or substituted for validated pharmaceutical process limits (CQA/CPP).
    """
    __tablename__ = "signal_thresholds"
    __table_args__ = (
        db.UniqueConstraint("signal_id", name="uq_signal_thresholds_signal_id"),
        db.Index("ix_thresholds_mach_sig", "machine_id", "signal_id"),
    )

    id = db.Column(db.String(36), primary_key=True, default=generate_uuid)
    organization_id = db.Column(
        db.String(36),
        db.ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    machine_id = db.Column(
        db.String(36),
        db.ForeignKey("machines.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    signal_id = db.Column(
        db.String(36),
        db.ForeignKey("machine_signals.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Threshold bounds
    warning_min = db.Column(db.Float, nullable=True)   # Lower Warning Limit (LWL)
    warning_max = db.Column(db.Float, nullable=True)   # Upper Warning Limit (UWL)
    critical_min = db.Column(db.Float, nullable=True)  # Lower Critical Limit (LCL)
    critical_max = db.Column(db.Float, nullable=True)  # Upper Critical Limit (UCL)

    unit = db.Column(db.String(50), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    created_by_user_id = db.Column(db.String(36), nullable=True)

    signal = db.relationship("MachineSignal")
    machine = db.relationship("Machine")

    def to_dict(self):
        return {
            "id": self.id,
            "organization_id": self.organization_id,
            "machine_id": self.machine_id,
            "signal_id": self.signal_id,
            "warning_min": self.warning_min,
            "warning_max": self.warning_max,
            "critical_min": self.critical_min,
            "critical_max": self.critical_max,
            "unit": self.unit,
            "is_active": self.is_active,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }



