import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from sqlalchemy import text, func
from app.extensions import db
from app.models.monitoring import (
    SignalReading,
    SignalReadingAggregate,
    RetentionPolicy,
    RetentionExecution,
)

logger = logging.getLogger(__name__)


class StorageMonitoringService:
    """Enterprise storage auditing and telemetry growth monitoring service.
    
    Provides:
    - Accurate row counts and daily ingestion velocity metrics.
    - Neon PostgreSQL table and index storage footprints (when supported).
    - Retention policy enforcement status and cumulative pruned record counts.
    - Strict avoidance of fabricated metrics on non-PostgreSQL dialects.
    """

    @classmethod
    def get_storage_metrics(cls, organization_id: str) -> Dict[str, Any]:
        """Compile a comprehensive storage and retention diagnostic report for an organization."""
        now = datetime.now(timezone.utc)
        today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        h24_ago = now - timedelta(hours=24)
        h48_ago = now - timedelta(hours=48)

        # 1. Row counts
        total_raw = SignalReading.query.filter_by(organization_id=organization_id).count()
        total_aggregates = SignalReadingAggregate.query.filter_by(organization_id=organization_id).count()

        # Ingestion velocity
        readings_today = SignalReading.query.filter(
            SignalReading.organization_id == organization_id,
            SignalReading.source_timestamp >= today_midnight,
        ).count()

        readings_last_24h = SignalReading.query.filter(
            SignalReading.organization_id == organization_id,
            SignalReading.source_timestamp >= h24_ago,
        ).count()

        readings_prev_24h = SignalReading.query.filter(
            SignalReading.organization_id == organization_id,
            SignalReading.source_timestamp >= h48_ago,
            SignalReading.source_timestamp < h24_ago,
        ).count()

        if readings_prev_24h > 0:
            growth_rate_pct = round(((readings_last_24h - readings_prev_24h) / readings_prev_24h) * 100.0, 1)
        else:
            growth_rate_pct = 100.0 if readings_last_24h > 0 else 0.0

        # 2. Retention Statistics
        active_policies = RetentionPolicy.query.filter_by(
            organization_id=organization_id,
            is_active=True,
        ).all()

        last_execution = (
            RetentionExecution.query
            .filter_by(organization_id=organization_id)
            .order_by(RetentionExecution.started_at.desc())
            .first()
        )

        pruned_sum = (
            db.session.query(func.coalesce(func.sum(RetentionExecution.records_deleted), 0))
            .filter(RetentionExecution.organization_id == organization_id)
            .scalar()
        )

        # 3. Physical Storage Sizing (Dialect-aware)
        storage_sizing = cls._get_physical_storage_sizing()

        return {
            "organization_id": organization_id,
            "timestamp": now.isoformat(),
            "telemetry_counts": {
                "raw_readings_total": total_raw,
                "aggregates_total": total_aggregates,
                "readings_today": readings_today,
                "readings_last_24h": readings_last_24h,
                "readings_prev_24h": readings_prev_24h,
                "daily_growth_rate_pct": growth_rate_pct,
            },
            "retention_status": {
                "active_policies_count": len(active_policies),
                "total_records_pruned": int(pruned_sum or 0),
                "last_execution": last_execution.to_dict() if last_execution else None,
                "policies": [p.to_dict() for p in active_policies],
            },
            "physical_storage": storage_sizing,
        }

    @classmethod
    def _get_physical_storage_sizing(cls) -> Dict[str, Any]:
        """Inspect actual PostgreSQL physical relation size.
        
        Returns None / unsupported status if database dialect does not expose pg_total_relation_size.
        """
        try:
            dialect_name = db.engine.dialect.name
        except Exception:
            dialect_name = "unknown"

        if dialect_name != "postgresql":
            return {
                "supported": False,
                "dialect": dialect_name,
                "reason": f"Physical relation size measurement is not supported by database engine '{dialect_name}'.",
                "table_bytes": None,
                "index_bytes": None,
                "total_bytes": None,
                "total_mb": None,
            }

        try:
            sql = text("""
                SELECT
                    pg_total_relation_size('signal_readings') AS total_bytes,
                    pg_relation_size('signal_readings') AS table_bytes,
                    pg_indexes_size('signal_readings') AS index_bytes
            """)
            row = db.session.execute(sql).fetchone()
            if row:
                total_b = int(row[0]) if row[0] is not None else 0
                table_b = int(row[1]) if row[1] is not None else 0
                index_b = int(row[2]) if row[2] is not None else 0
                return {
                    "supported": True,
                    "dialect": "postgresql",
                    "table_name": "signal_readings",
                    "table_bytes": table_b,
                    "index_bytes": index_b,
                    "total_bytes": total_b,
                    "total_mb": round(total_b / (1024.0 * 1024.0), 2),
                    "human_readable": f"{round(total_b / (1024.0 * 1024.0), 2)} MB",
                }
        except Exception as e:
            logger.warning(f"[StorageMonitoringService] Error reading pg_total_relation_size: {e}")
            return {
                "supported": False,
                "dialect": "postgresql",
                "reason": f"Database user lacked permission or error querying pg_total_relation_size: {e}",
                "table_bytes": None,
                "index_bytes": None,
                "total_bytes": None,
                "total_mb": None,
            }

        return {
            "supported": False,
            "dialect": dialect_name,
            "reason": "Unknown error retrieving relation size",
            "table_bytes": None,
            "index_bytes": None,
            "total_bytes": None,
            "total_mb": None,
        }

