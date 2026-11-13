import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Tuple
from sqlalchemy import text, func, and_
from app.extensions import db
from app.models.monitoring import (
    SignalReading,
    RetentionPolicy,
    RetentionExecution,
    SignalReadingAggregate,
)
from app.models.signal_mapping import MachineSignal

logger = logging.getLogger(__name__)


class RetentionService:
    """Enterprise telemetry retention and lifecycle management service for PharmaPredict AI.
    
    Adheres to strict pharmaceutical data integrity standards:
    - Default behavior is SAFE: No deletion is performed unless an active policy is configured.
    - Pre-aggregates raw time-series into hourly rollups before any deletion.
    - Executes deletion in bounded, transactional batches to prevent database locking.
    - Provides dry-run analysis mode for compliance and operational preview.
    - Full execution audit tracking with record counts, durations, and status logging.
    - Dialect-aware: Fully compatible with PostgreSQL and SQLite.
    """

    DEFAULT_BATCH_SIZE = 500

    @classmethod
    def get_effective_policy(
        cls,
        organization_id: str,
        machine_id: Optional[str] = None
    ) -> Optional[RetentionPolicy]:
        """Resolve the effective retention policy for a machine or organization.
        
        Machine-specific active policy overrides the organization default.
        Returns None if no active policy is configured.
        """
        if machine_id:
            mach_policy = RetentionPolicy.query.filter_by(
                organization_id=organization_id,
                machine_id=machine_id,
                is_active=True,
            ).first()
            if mach_policy:
                return mach_policy

        # Fall back to organization-wide default policy (where machine_id is None)
        org_policy = RetentionPolicy.query.filter_by(
            organization_id=organization_id,
            machine_id=None,
            is_active=True,
        ).first()
        return org_policy

    @classmethod
    def set_policy(
        cls,
        organization_id: str,
        machine_id: Optional[str] = None,
        raw_retention_days: int = 90,
        aggregate_retention_days: int = 365,
        is_active: bool = True,
        archive_before_delete: bool = True,
        batch_size: int = DEFAULT_BATCH_SIZE,
        user_id: Optional[str] = None,
    ) -> RetentionPolicy:
        """Create or update a telemetry retention policy."""
        if raw_retention_days < 1:
            raise ValueError("raw_retention_days must be at least 1 day.")
        if aggregate_retention_days < raw_retention_days:
            raise ValueError("aggregate_retention_days cannot be less than raw_retention_days.")
        if batch_size < 1 or batch_size > 10000:
            raise ValueError("batch_size must be between 1 and 10000 records.")

        policy = RetentionPolicy.query.filter_by(
            organization_id=organization_id,
            machine_id=machine_id,
        ).first()

        now = datetime.now(timezone.utc)
        if not policy:
            policy = RetentionPolicy(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                machine_id=machine_id,
                raw_retention_days=raw_retention_days,
                aggregate_retention_days=aggregate_retention_days,
                is_active=is_active,
                archive_before_delete=archive_before_delete,
                batch_size=batch_size,
                created_at=now,
                updated_at=now,
                created_by_user_id=user_id,
            )
            db.session.add(policy)
        else:
            policy.raw_retention_days = raw_retention_days
            policy.aggregate_retention_days = aggregate_retention_days
            policy.is_active = is_active
            policy.archive_before_delete = archive_before_delete
            policy.batch_size = batch_size
            policy.updated_at = now
            if user_id:
                policy.created_by_user_id = user_id

        db.session.commit()
        return policy

    @classmethod
    def execute_retention(
        cls,
        organization_id: str,
        machine_id: Optional[str] = None,
        dry_run: bool = False,
        batch_size: Optional[int] = None,
        max_batches: Optional[int] = None,
        executed_by: str = "SYSTEM",
    ) -> Dict[str, Any]:
        """Execute a safe, bounded telemetry retention and pre-aggregation cycle.
        
        If no policy exists: Safely skips deletion to protect historical data.
        If dry_run=True: Returns impact metrics without modifying any telemetry.
        """
        policy = cls.get_effective_policy(organization_id, machine_id)
        now = datetime.now(timezone.utc)

        if not policy:
            logger.info(
                f"[RetentionService] No active policy for org={organization_id}, machine={machine_id}. "
                "Preserving all telemetry records."
            )
            return {
                "status": "SKIPPED",
                "dry_run": dry_run,
                "message": "No active retention policy configured. Deletion bypassed for pharmaceutical record protection.",
                "records_scanned": 0,
                "records_aggregated": 0,
                "records_deleted": 0,
                "batches_processed": 0,
            }

        cutoff_timestamp = now - timedelta(days=policy.raw_retention_days)
        actual_batch_size = batch_size or policy.batch_size or cls.DEFAULT_BATCH_SIZE

        # Create execution audit record
        execution = RetentionExecution(
            id=str(uuid.uuid4()),
            policy_id=policy.id,
            organization_id=organization_id,
            machine_id=machine_id,
            started_at=now,
            dry_run=dry_run,
            cutoff_timestamp=cutoff_timestamp,
            records_scanned=0,
            records_aggregated=0,
            records_deleted=0,
            batch_count=0,
            status="DRY_RUN" if dry_run else "IN_PROGRESS",
            executed_by=executed_by,
        )
        db.session.add(execution)
        db.session.commit()

        try:
            # Query candidate raw readings older than cutoff
            base_query = SignalReading.query.filter(
                SignalReading.organization_id == organization_id,
                SignalReading.source_timestamp < cutoff_timestamp,
            )
            if machine_id:
                base_query = base_query.filter(SignalReading.machine_id == machine_id)

            total_eligible = base_query.count()
            execution.records_scanned = total_eligible

            if dry_run:
                # Dry run only: report metrics, do not alter data
                execution.completed_at = datetime.now(timezone.utc)
                execution.status = "DRY_RUN"
                db.session.commit()
                return {
                    "status": "DRY_RUN",
                    "dry_run": True,
                    "policy_id": policy.id,
                    "cutoff_timestamp": cutoff_timestamp.isoformat(),
                    "records_scanned": total_eligible,
                    "records_aggregated": 0,
                    "records_deleted": 0,
                    "batches_processed": 0,
                    "message": f"Dry-run preview: {total_eligible} records eligible for archiving and deletion older than {cutoff_timestamp.isoformat()}.",
                }

            if total_eligible == 0:
                execution.completed_at = datetime.now(timezone.utc)
                execution.status = "COMPLETED"
                db.session.commit()
                return {
                    "status": "COMPLETED",
                    "dry_run": False,
                    "policy_id": policy.id,
                    "cutoff_timestamp": cutoff_timestamp.isoformat(),
                    "records_scanned": 0,
                    "records_aggregated": 0,
                    "records_deleted": 0,
                    "batches_processed": 0,
                    "message": "Zero records older than retention cutoff. Database is clean.",
                }

            # Step 1: Pre-aggregation into hourly rollups before deletion
            aggregated_count = 0
            if policy.archive_before_delete:
                aggregated_count = cls._pre_aggregate_records(
                    organization_id=organization_id,
                    machine_id=machine_id,
                    cutoff_timestamp=cutoff_timestamp,
                )
                execution.records_aggregated = aggregated_count

            # Step 2: Safe Bounded Batch Deletion
            deleted_count = 0
            batch_idx = 0

            while True:
                if max_batches and batch_idx >= max_batches:
                    logger.info(f"[RetentionService] Reached max_batches limit ({max_batches}). Yielding.")
                    break

                # Query up to actual_batch_size primary keys
                id_subquery = (
                    db.session.query(SignalReading.id)
                    .filter(
                        SignalReading.organization_id == organization_id,
                        SignalReading.source_timestamp < cutoff_timestamp,
                    )
                )
                if machine_id:
                    id_subquery = id_subquery.filter(SignalReading.machine_id == machine_id)

                batch_ids = [row[0] for row in id_subquery.limit(actual_batch_size).all()]

                if not batch_ids:
                    break  # All eligible records processed

                # Atomic deletion of the batch
                deleted_in_batch = (
                    SignalReading.query
                    .filter(SignalReading.id.in_(batch_ids))
                    .delete(synchronize_session=False)
                )

                db.session.commit()
                deleted_count += deleted_in_batch
                batch_idx += 1

                # Update progress on execution log
                execution.records_deleted = deleted_count
                execution.batch_count = batch_idx
                db.session.commit()

            execution.completed_at = datetime.now(timezone.utc)
            execution.status = "COMPLETED"
            db.session.commit()

            return {
                "status": "COMPLETED",
                "dry_run": False,
                "policy_id": policy.id,
                "cutoff_timestamp": cutoff_timestamp.isoformat(),
                "records_scanned": total_eligible,
                "records_aggregated": aggregated_count,
                "records_deleted": deleted_count,
                "batches_processed": batch_idx,
                "message": f"Successfully aggregated {aggregated_count} intervals and pruned {deleted_count} raw records across {batch_idx} batches.",
            }

        except Exception as e:
            logger.error(f"[RetentionService] Error during retention execution: {e}")
            db.session.rollback()
            execution.completed_at = datetime.now(timezone.utc)
            execution.status = "FAILED"
            execution.error_message = str(e)
            db.session.commit()
            raise

    @classmethod
    def _pre_aggregate_records(
        cls,
        organization_id: str,
        machine_id: Optional[str],
        cutoff_timestamp: datetime,
    ) -> int:
        """Aggregate candidate raw readings into hourly rollups in signal_reading_aggregates.
        
        Computes min, max, avg, first, last, and reading count per signal per hour bucket.
        Dialect-aware for PostgreSQL and SQLite.
        """
        dialect_name = db.session.bind.dialect.name if (db.session.bind and hasattr(db.session.bind, "dialect")) else "postgresql"

        readings_query = SignalReading.query.filter(
            SignalReading.organization_id == organization_id,
            SignalReading.source_timestamp < cutoff_timestamp,
        )
        if machine_id:
            readings_query = readings_query.filter(SignalReading.machine_id == machine_id)

        # Get unique signals involved
        signal_ids = [row[0] for row in readings_query.with_entities(SignalReading.signal_id).distinct().all()]
        if not signal_ids:
            return 0

        created_aggregates = 0

        for sig_id in signal_ids:
            sig_readings = readings_query.filter(SignalReading.signal_id == sig_id).order_by(SignalReading.source_timestamp.asc()).all()
            if not sig_readings:
                continue

            # Group in memory by 1-hour bucket
            buckets: Dict[datetime, List[SignalReading]] = {}
            for r in sig_readings:
                ts = r.source_timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                b_start = ts.replace(minute=0, second=0, microsecond=0)
                if b_start not in buckets:
                    buckets[b_start] = []
                buckets[b_start].append(r)

            for b_start, items in buckets.items():
                b_end = b_start + timedelta(hours=1)
                numeric_vals = [
                    float(x.normalized_value) for x in items
                    if x.normalized_value is not None
                ]

                min_v = min(numeric_vals) if numeric_vals else None
                max_v = max(numeric_vals) if numeric_vals else None
                avg_v = (sum(numeric_vals) / len(numeric_vals)) if numeric_vals else None
                first_v = numeric_vals[0] if numeric_vals else None
                last_v = numeric_vals[-1] if numeric_vals else None

                # Check if rollup already exists
                existing = SignalReadingAggregate.query.filter_by(
                    signal_id=sig_id,
                    bucket_start=b_start,
                    bucket_resolution="1h",
                ).first()

                if not existing:
                    agg = SignalReadingAggregate(
                        id=str(uuid.uuid4()),
                        organization_id=organization_id,
                        machine_id=items[0].machine_id,
                        signal_id=sig_id,
                        bucket_start=b_start,
                        bucket_end=b_end,
                        bucket_resolution="1h",
                        min_value=min_v,
                        max_value=max_v,
                        avg_value=avg_v,
                        first_value=first_v,
                        last_value=last_v,
                        reading_count=len(items),
                        quality_summary="Good" if all(x.quality_code == "Good" for x in items) else "Mixed",
                        created_at=datetime.now(timezone.utc),
                    )
                    db.session.add(agg)
                    created_aggregates += 1
                else:
                    # Update existing aggregate
                    existing.min_value = min(existing.min_value, min_v) if (existing.min_value is not None and min_v is not None) else (min_v or existing.min_value)
                    existing.max_value = max(existing.max_value, max_v) if (existing.max_value is not None and max_v is not None) else (max_v or existing.max_value)
                    existing.reading_count += len(items)

        db.session.commit()
        return created_aggregates

    @classmethod
    def get_execution_history(
        cls,
        organization_id: str,
        machine_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent retention execution audit records."""
        query = RetentionExecution.query.filter_by(organization_id=organization_id)
        if machine_id:
            query = query.filter_by(machine_id=machine_id)

        executions = query.order_by(RetentionExecution.started_at.desc()).limit(min(100, limit)).all()
        return [e.to_dict() for e in executions]

