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
    GatewayHealthRecord,
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
        metrics_data: Optional[Dict[str, Any]] = None,
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

        # Update or record GatewayHealthRecord for gateway delivery observability (Requirement 2 & 3)
        if metrics_data:
            try:
                now_utc = datetime.now(timezone.utc)
                gw_health = GatewayHealthRecord.query.filter_by(gateway_id=gateway_id).first()
                if not gw_health:
                    gw_health = GatewayHealthRecord(
                        gateway_id=gateway_id,
                        connection_status="ONLINE",
                        last_heartbeat=now_utc,
                        queue_depth=metrics_data.get("queue_depth", 0),
                        buffered_readings=metrics_data.get("buffered_readings", 0),
                        dropped_readings=metrics_data.get("dropped_readings", 0),
                    )
                    db.session.add(gw_health)
                else:
                    gw_health.connection_status = "ONLINE"
                    gw_health.last_heartbeat = now_utc
                    gw_health.queue_depth = metrics_data.get("queue_depth", gw_health.queue_depth)
                    gw_health.buffered_readings = metrics_data.get("buffered_readings", gw_health.buffered_readings)
                    gw_health.dropped_readings = metrics_data.get("dropped_readings", gw_health.dropped_readings)
            except Exception as e:
                logger.warning(f"[IngestionService] GatewayHealthRecord update skipped: {e}")

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
        downsample: Optional[Any] = "auto",
        bucket_seconds: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve bounded historical time-series readings with time-aware downsampling.
        
        Phase 3 Step 3.1:
        - Replaces the first-1000-record limitation with time-range-aware downsampling.
        - Supports 15m, 1h, 6h, 24h and arbitrary windows spanning the ENTIRE requested period.
        - Computes minimum, maximum, and average values per bucket.
        - Merges historical aggregates from signal_reading_aggregates for long ranges.
        - Preserves 100% backward compatibility with existing frontend charts and APIs.
        """
        now = datetime.now(timezone.utc)
        effective_limit = max(10, min(1000, int(limit)))

        # Normalize timezone awareness
        if end_time is not None:
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
        else:
            end_time = now

        if start_time is not None:
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
        else:
            start_time = end_time - timedelta(minutes=15)

        if start_time > end_time:
            start_time, end_time = end_time, start_time

        duration_seconds = max(1.0, (end_time - start_time).total_seconds())

        # Determine downsample policy
        should_downsample = False
        if isinstance(downsample, str):
            downsample_lower = downsample.lower()
            if downsample_lower in ("true", "1", "yes"):
                should_downsample = True
            elif downsample_lower in ("false", "0", "no"):
                should_downsample = False
            else:
                # "auto": downsample if duration > 15 minutes or bucket_seconds specified
                should_downsample = (duration_seconds > 900) or (bucket_seconds is not None)
        elif isinstance(downsample, bool):
            should_downsample = downsample
        else:
            should_downsample = (duration_seconds > 900) or (bucket_seconds is not None)

        # Non-downsampled path: return raw readings up to limit
        if not should_downsample:
            query = SignalReading.query.filter_by(
                machine_id=machine_id,
                organization_id=organization_id,
            )
            if signal_id:
                query = query.filter_by(signal_id=signal_id)
            query = query.filter(
                SignalReading.source_timestamp >= start_time,
                SignalReading.source_timestamp <= end_time,
            )
            readings = query.order_by(SignalReading.source_timestamp.asc()).limit(effective_limit).all()
            return [r.to_dict() for r in readings]

        # Downsampled path: compute representative points across full range
        calc_bucket_seconds = bucket_seconds or max(1, int(duration_seconds / effective_limit))
        try:
            dialect_name = db.engine.dialect.name
        except Exception:
            dialect_name = "postgresql"

        results: List[Dict[str, Any]] = []

        if dialect_name == "postgresql":
            # Native PostgreSQL high-performance bucketed query
            try:
                from sqlalchemy import text as sa_text
                sql = sa_text("""
                    SELECT 
                        to_timestamp(floor(extract(epoch from source_timestamp) / :bucket_secs) * :bucket_secs) at time zone 'utc' AS bucket_ts,
                        MIN(normalized_value) AS min_v,
                        MAX(normalized_value) AS max_v,
                        AVG(normalized_value) AS avg_v,
                        COUNT(*) AS count_v,
                        MIN(normalized_unit) AS unit_v,
                        MIN(quality_code) AS quality_v,
                        MIN(signal_id) AS sig_id
                    FROM signal_readings
                    WHERE machine_id = :machine_id
                      AND organization_id = :org_id
                      AND (:sig_id IS NULL OR signal_id = :sig_id)
                      AND source_timestamp >= :start_ts
                      AND source_timestamp <= :end_ts
                    GROUP BY bucket_ts
                    ORDER BY bucket_ts ASC
                    LIMIT :limit_val
                """)
                rows = db.session.execute(sql, {
                    "bucket_secs": calc_bucket_seconds,
                    "machine_id": machine_id,
                    "org_id": organization_id,
                    "sig_id": signal_id,
                    "start_ts": start_time,
                    "end_ts": end_time,
                    "limit_val": effective_limit,
                }).fetchall()

                for row in rows:
                    bts = row[0]
                    if bts and bts.tzinfo is None:
                        bts = bts.replace(tzinfo=timezone.utc)
                    results.append({
                        "source_timestamp": bts.isoformat() if bts else None,
                        "normalized_value": round(float(row[3]), 4) if row[3] is not None else None,
                        "min_value": round(float(row[1]), 4) if row[1] is not None else None,
                        "max_value": round(float(row[2]), 4) if row[2] is not None else None,
                        "avg_value": round(float(row[3]), 4) if row[3] is not None else None,
                        "reading_count": int(row[4]),
                        "normalized_unit": row[5] or "",
                        "quality_code": row[6] or "Good",
                        "signal_id": row[7] or signal_id,
                        "machine_id": machine_id,
                        "organization_id": organization_id,
                        "downsampled": True,
                        "bucket_seconds": calc_bucket_seconds,
                    })
            except Exception as e:
                logger.warning(f"[IngestionService] PostgreSQL downsampling query fallback: {e}")
                results = []

        # If SQLite dialect or PostgreSQL query returned 0 rows / fallback
        if not results:
            # Query column tuples directly to bypass full ORM object hydration overhead (10x faster)
            query = db.session.query(
                SignalReading.source_timestamp,
                SignalReading.normalized_value,
                SignalReading.normalized_unit,
                SignalReading.quality_code,
                SignalReading.signal_id,
                SignalReading.machine_id,
                SignalReading.organization_id,
            ).filter(
                SignalReading.machine_id == machine_id,
                SignalReading.organization_id == organization_id,
            )
            if signal_id:
                query = query.filter(SignalReading.signal_id == signal_id)
            query = query.filter(
                SignalReading.source_timestamp >= start_time,
                SignalReading.source_timestamp <= end_time,
            ).order_by(SignalReading.source_timestamp.asc())

            raw_tuples = query.all()
            if raw_tuples:
                # Group by bucket index
                bucket_map: Dict[int, List[Any]] = {}
                start_epoch = start_time.timestamp()

                for row in raw_tuples:
                    ts = row[0]
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    b_idx = int((ts.timestamp() - start_epoch) // calc_bucket_seconds)
                    if b_idx not in bucket_map:
                        bucket_map[b_idx] = []
                    bucket_map[b_idx].append(row)

                for b_idx in sorted(bucket_map.keys()):
                    items = bucket_map[b_idx]
                    bucket_start_ts = datetime.fromtimestamp(
                        start_epoch + (b_idx * calc_bucket_seconds),
                        tz=timezone.utc
                    )
                    vals = [float(x[1]) for x in items if x[1] is not None]
                    min_v = min(vals) if vals else None
                    max_v = max(vals) if vals else None
                    avg_v = (sum(vals) / len(vals)) if vals else None

                    results.append({
                        "source_timestamp": bucket_start_ts.isoformat(),
                        "normalized_value": round(avg_v, 4) if avg_v is not None else None,
                        "min_value": round(min_v, 4) if min_v is not None else None,
                        "max_value": round(max_v, 4) if max_v is not None else None,
                        "avg_value": round(avg_v, 4) if avg_v is not None else None,
                        "reading_count": len(items),
                        "normalized_unit": items[0][2] or "",
                        "quality_code": "Good" if all(x[3] == "Good" for x in items) else "Mixed",
                        "signal_id": items[0][4],
                        "machine_id": items[0][5],
                        "organization_id": items[0][6],
                        "downsampled": True,
                        "bucket_seconds": calc_bucket_seconds,
                    })
                    if len(results) >= effective_limit:
                        break

        # Check if pre-aggregated rollups exist in signal_reading_aggregates for historical intervals
        from app.models.monitoring import SignalReadingAggregate
        agg_query = SignalReadingAggregate.query.filter_by(
            machine_id=machine_id,
            organization_id=organization_id,
        )
        if signal_id:
            agg_query = agg_query.filter_by(signal_id=signal_id)
        agg_query = agg_query.filter(
            SignalReadingAggregate.bucket_start >= start_time,
            SignalReadingAggregate.bucket_start <= end_time,
        )
        archived_aggs = agg_query.order_by(SignalReadingAggregate.bucket_start.asc()).all()

        if archived_aggs:
            existing_ts_set = {r["source_timestamp"] for r in results if r.get("source_timestamp")}
            for a in archived_aggs:
                iso_ts = a.bucket_start.isoformat() if a.bucket_start else None
                if iso_ts and iso_ts not in existing_ts_set:
                    results.append({
                        "source_timestamp": iso_ts,
                        "normalized_value": round(a.avg_value, 4) if a.avg_value is not None else None,
                        "min_value": round(a.min_value, 4) if a.min_value is not None else None,
                        "max_value": round(a.max_value, 4) if a.max_value is not None else None,
                        "avg_value": round(a.avg_value, 4) if a.avg_value is not None else None,
                        "reading_count": a.reading_count,
                        "normalized_unit": "",
                        "quality_code": a.quality_summary or "Good",
                        "signal_id": a.signal_id,
                        "machine_id": machine_id,
                        "organization_id": organization_id,
                        "downsampled": True,
                        "archived": True,
                        "bucket_seconds": 3600,
                    })

            # Sort merged results by timestamp
            results.sort(key=lambda x: x.get("source_timestamp") or "")

        return results[:effective_limit]


