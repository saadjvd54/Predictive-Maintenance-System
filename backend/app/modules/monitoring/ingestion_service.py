import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from app.extensions import db
from app.models.equipment import Machine
from app.models.signal_mapping import MachineSignal
from app.models.monitoring import (
    SignalReading,
    IngestionBatch,
    SignalFreshness,
    MonitoringSession,
    MonitoringState,
)

logger = logging.getLogger(__name__)


class IngestionService:
    """Handles time-series persistence, idempotent deduplication,
    batch processing, and historical retrieval.
    """

    @classmethod
    def ingest_batch(
        cls,
        gateway_id: str,
        readings_data: List[Dict[str, Any]],
        batch_identifier: Optional[str] = None,
        authenticated_gateway: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Ingest a batch of normalized readings idempotently with atomic conflict handling and strict authorization (Fix 1 & Fix 2)."""
        import uuid
        batch_id = batch_identifier or f"batch-{datetime.now(timezone.utc).timestamp()}"

        accepted = 0
        rejected = 0
        duplicates = 0

        records_to_insert: List[Dict[str, Any]] = []

        for item in readings_data:
            eid = item.get("event_id")
            org_id = item.get("organization_id")
            mach_id = item.get("machine_id")
            sig_id = item.get("signal_id")

            if not eid or not org_id or not mach_id or not sig_id:
                rejected += 1
                continue

            # Strict Gateway Authorization Check (Fix 1)
            if authenticated_gateway:
                if not authenticated_gateway.is_authorized_for(org_id, mach_id):
                    logger.warning(
                        f"[GatewayAuth] Unauthorized reading rejected: gateway '{authenticated_gateway.gateway_id}' "
                        f"is not authorized for organization '{org_id}', machine '{mach_id}'"
                    )
                    rejected += 1
                    continue

                # Verify target machine exists in the database and belongs to the authorized organization
                target_machine = db.session.get(Machine, mach_id)
                if not target_machine or target_machine.organization_id != org_id:
                    logger.warning(
                        f"[IngestionService] Target machine '{mach_id}' not found or does not belong to org '{org_id}'"
                    )
                    rejected += 1
                    continue

            try:
                # Parse timestamps
                src_ts_raw = item.get("source_timestamp")
                if isinstance(src_ts_raw, str):
                    src_ts = datetime.fromisoformat(src_ts_raw.replace("Z", "+00:00"))
                elif isinstance(src_ts_raw, datetime):
                    src_ts = src_ts_raw
                else:
                    src_ts = datetime.now(timezone.utc)

                srv_ts = None
                if item.get("server_timestamp"):
                    srv_raw = item["server_timestamp"]
                    srv_ts = datetime.fromisoformat(srv_raw.replace("Z", "+00:00")) if isinstance(srv_raw, str) else srv_raw

                gw_ts = None
                if item.get("gateway_received_at"):
                    gw_raw = item["gateway_received_at"]
                    gw_ts = datetime.fromisoformat(gw_raw.replace("Z", "+00:00")) if isinstance(gw_raw, str) else gw_raw

                record_dict = {
                    "id": str(uuid.uuid4()),
                    "event_id": eid,
                    "organization_id": org_id,
                    "machine_id": mach_id,
                    "signal_id": sig_id,
                    "connector_id": item.get("connector_id"),
                    "gateway_id": gateway_id,
                    "mapping_version": int(item.get("mapping_version", 1)),
                    "source_timestamp": src_ts,
                    "server_timestamp": srv_ts,
                    "gateway_received_at": gw_ts,
                    "ingestion_timestamp": datetime.now(timezone.utc),
                    "source_value": str(item.get("source_value")) if item.get("source_value") is not None else None,
                    "normalized_value": float(item["normalized_value"]) if item.get("normalized_value") is not None else None,
                    "raw_value_numeric": float(item["raw_value_numeric"]) if item.get("raw_value_numeric") is not None else None,
                    "raw_value_boolean": bool(item["raw_value_boolean"]) if item.get("raw_value_boolean") is not None else None,
                    "raw_value_string": str(item.get("raw_value_string")) if item.get("raw_value_string") is not None else None,
                    "source_unit": item.get("source_unit"),
                    "normalized_unit": item.get("normalized_unit"),
                    "quality_code": item.get("opcua_quality_code") or item.get("quality_code") or "Good",
                    "normalization_status": item.get("normalization_status", "NORMALIZED"),
                    "sampling_interval_ms": int(item.get("sampling_interval_ms", 1000)),
                    "simulator_flag": bool(item.get("simulator_flag", True)),
                }
                records_to_insert.append(record_dict)
            except Exception as e:
                logger.error(f"[IngestionService] Error preparing reading {eid}: {e}")
                rejected += 1

        # Atomic Idempotent Insertion (Fix 2: ON CONFLICT DO NOTHING)
        if records_to_insert:
            dialect_name = db.session.bind.dialect.name if (db.session.bind and hasattr(db.session.bind, "dialect")) else "postgresql"
            try:
                if dialect_name == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert as pg_insert
                    stmt = pg_insert(SignalReading).values(records_to_insert)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
                elif dialect_name == "sqlite":
                    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                    stmt = sqlite_insert(SignalReading).values(records_to_insert)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
                else:
                    from sqlalchemy.dialects.postgresql import insert as gen_insert
                    stmt = gen_insert(SignalReading).values(records_to_insert)
                    stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])

                result = db.session.execute(stmt)
                inserted_count = result.rowcount if (result.rowcount is not None and result.rowcount >= 0) else len(records_to_insert)
                accepted += inserted_count
                duplicates += (len(records_to_insert) - inserted_count)
            except Exception as e:
                logger.error(f"[IngestionService] Atomic insert error: {e}")
                db.session.rollback()
                raise

        # Record ingestion batch audit (safely handling duplicate batch identifier)
        existing_batch = IngestionBatch.query.filter_by(batch_identifier=batch_id).first()
        if not existing_batch:
            batch_record = IngestionBatch(
                gateway_id=gateway_id,
                batch_identifier=batch_id,
                accepted_count=accepted,
                rejected_count=rejected,
                status="ACCEPTED" if rejected == 0 else ("PARTIAL" if accepted > 0 else "REJECTED"),
            )
            db.session.add(batch_record)
        else:
            existing_batch.accepted_count += accepted

        try:
            db.session.commit()
        except Exception as e:
            logger.error(f"[IngestionService] Failed to commit batch {batch_id}: {e}")
            db.session.rollback()
            raise

        return {
            "batch_identifier": batch_id,
            "accepted": accepted,
            "rejected": rejected,
            "duplicates": duplicates,
            "total_processed": len(readings_data),
        }

    @classmethod
    def get_latest_readings(cls, machine_id: str, organization_id: str) -> List[Dict[str, Any]]:
        """Retrieve the most recent reading for each mapped signal of a machine,
        calculating real-time data freshness (FRESH, DELAYED, STALE, UNAVAILABLE).
        """
        signals = MachineSignal.query.filter_by(machine_id=machine_id, organization_id=organization_id).all()
        now = datetime.now(timezone.utc)

        results = []
        for sig in signals:
            latest = (
                SignalReading.query.filter_by(
                    signal_id=sig.id,
                    machine_id=machine_id,
                    organization_id=organization_id,
                )
                .order_by(SignalReading.source_timestamp.desc())
                .first()
            )

            if latest:
                item = latest.to_dict()
                # Compute freshness
                ts = latest.source_timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age_ms = (now - ts).total_seconds() * 1000.0
                expected_ms = float(sig.sampling_interval_ms or 1000)

                if age_ms <= expected_ms * 2.5:
                    freshness = SignalFreshness.FRESH
                elif age_ms <= expected_ms * 6.0:
                    freshness = SignalFreshness.DELAYED
                else:
                    freshness = SignalFreshness.STALE

                item["freshness"] = freshness
                item["age_seconds"] = round(age_ms / 1000.0, 1)
                results.append(item)
            else:
                # No readings yet
                def_name = sig.signal_definition.name if sig.signal_definition else sig.signal_code
                results.append({
                    "signal_id": sig.id,
                    "signal_name": sig.custom_name or def_name,
                    "signal_group": sig.signal_definition.signal_group if sig.signal_definition else "Other",
                    "machine_id": machine_id,
                    "organization_id": organization_id,
                    "source_node_id": sig.source_node_id,
                    "normalized_unit": sig.normalized_unit or (sig.signal_definition.standard_unit if sig.signal_definition else None),
                    "normalized_value": None,
                    "quality_code": "No Data",
                    "freshness": SignalFreshness.UNAVAILABLE,
                    "source_timestamp": None,
                    "simulator_flag": True,
                })

        return results

    @classmethod
    def get_historical_readings(
        cls,
        machine_id: str,
        organization_id: str,
        signal_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Retrieve bounded historical time-series readings for charting."""
        query = SignalReading.query.filter_by(
            machine_id=machine_id,
            organization_id=organization_id,
        )

        if signal_id:
            query = query.filter_by(signal_id=signal_id)

        if start_time:
            query = query.filter(SignalReading.source_timestamp >= start_time)
        if end_time:
            query = query.filter(SignalReading.source_timestamp <= end_time)

        # Order ascending for time-series charts
        readings = query.order_by(SignalReading.source_timestamp.asc()).limit(min(1000, limit)).all()
        return [r.to_dict() for r in readings]

