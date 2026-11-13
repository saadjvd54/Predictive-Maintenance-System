import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Generator
from sqlalchemy import text
from app.extensions import db
from app.models.equipment import Machine
from app.models.signal_mapping import MachineSignal
from app.models.monitoring import SignalReading
from app.modules.monitoring.threshold_service import ThresholdService

logger = logging.getLogger(__name__)


class TelemetryExportService:
    """Enterprise telemetry data export service for CSV and JSON outputs.
    
    Adheres to strict pharmaceutical standards:
    - Enforces tenant and equipment authorization boundaries.
    - Exports full precision timestamps (ISO 8601 UTC) and values.
    - Annotates readings with operational thresholds and quality indicators.
    - Strictly bounded queries (max 50,000 records) to prevent memory exhaustion.
    - Never mutates or alters database source records.
    """

    MAX_EXPORT_ROWS = 50000

    @classmethod
    def export_telemetry(
        cls,
        organization_id: str,
        machine_id: str,
        signal_ids: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        format_type: str = "csv",
        limit: int = 10000,
        downsample: bool = False,
    ) -> Dict[str, Any]:
        """Fetch and format bounded telemetry data for CSV or JSON download."""
        machine = db.session.get(Machine, machine_id)
        if not machine or machine.organization_id != organization_id:
            raise PermissionError("Equipment not found or access denied for this organization.")

        effective_limit = min(cls.MAX_EXPORT_ROWS, max(1, limit))

        # Retrieve mapped signals for metadata
        sig_query = MachineSignal.query.filter_by(
            machine_id=machine_id,
            organization_id=organization_id,
        )
        if signal_ids:
            sig_query = sig_query.filter(MachineSignal.id.in_(signal_ids))
        mapped_signals = sig_query.all()
        sig_map = {
            s.id: {
                "signal_code": s.signal_definition.signal_code if s.signal_definition else s.source_node_id,
                "signal_name": s.custom_name or (s.signal_definition.name if s.signal_definition else s.source_node_id),
                "unit": s.normalized_unit or (s.signal_definition.standard_unit if s.signal_definition else ""),
            }
            for s in mapped_signals
        }

        # Retrieve thresholds for active signals
        thresholds = ThresholdService.get_thresholds_for_machine(machine_id, organization_id)

        # Base query for readings
        readings_query = db.session.query(
            SignalReading.source_timestamp,
            SignalReading.signal_id,
            SignalReading.source_value,
            SignalReading.raw_value_numeric,
            SignalReading.normalized_value,
            SignalReading.source_unit,
            SignalReading.normalized_unit,
            SignalReading.quality_code,
            SignalReading.normalization_status,
        ).filter(
            SignalReading.organization_id == organization_id,
            SignalReading.machine_id == machine_id,
        )

        if signal_ids:
            readings_query = readings_query.filter(SignalReading.signal_id.in_(signal_ids))

        if start_time:
            if start_time.tzinfo is None:
                start_time = start_time.replace(tzinfo=timezone.utc)
            readings_query = readings_query.filter(SignalReading.source_timestamp >= start_time)

        if end_time:
            if end_time.tzinfo is None:
                end_time = end_time.replace(tzinfo=timezone.utc)
            readings_query = readings_query.filter(SignalReading.source_timestamp <= end_time)

        readings_rows = readings_query.order_by(SignalReading.source_timestamp.asc()).limit(effective_limit).all()

        records: List[Dict[str, Any]] = []
        for r in readings_rows:
            ts = r[0]
            if ts and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            sig_id = r[1]
            meta = sig_map.get(sig_id, {})
            sig_thresh = thresholds.get(sig_id, {})

            norm_val = r[4]
            thresh_status = ThresholdService.evaluate_value(norm_val, sig_thresh)

            records.append({
                "equipment_id": machine.id,
                "machine_id": machine.id,
                "asset_code": machine.asset_code,
                "equipment_name": machine.equipment_name,
                "signal_id": sig_id,
                "signal_code": meta.get("signal_code", ""),
                "signal_name": meta.get("signal_name", ""),
                "source_timestamp": ts.isoformat() if ts else None,
                "raw_value": r[3] if r[3] is not None else r[2],
                "normalized_value": norm_val,
                "engineering_unit": r[6] or meta.get("unit", "") or r[5],
                "quality_code": r[7] or "Good",
                "normalization_status": r[8] or "NORMALIZED",
                "threshold_status": thresh_status,
                "warning_min": sig_thresh.get("warning_min"),
                "warning_max": sig_thresh.get("warning_max"),
                "critical_min": sig_thresh.get("critical_min"),
                "critical_max": sig_thresh.get("critical_max"),
            })

        if format_type.lower() == "json":
            return {
                "format": "json",
                "content_type": "application/json",
                "filename": f"telemetry_{machine.asset_code}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
                "data": {
                    "machine_id": machine.id,
                    "equipment_id": machine.id,
                    "asset_code": machine.asset_code,
                    "equipment_name": machine.equipment_name,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "record_count": len(records),
                    "readings": records,
                    "records": records,
                },
            }

        # CSV format
        output = io.StringIO()
        fieldnames = [
            "equipment_id",
            "machine_id",
            "asset_code",
            "equipment_name",
            "signal_id",
            "signal_code",
            "signal_name",
            "source_timestamp",
            "raw_value",
            "normalized_value",
            "engineering_unit",
            "quality_code",
            "normalization_status",
            "threshold_status",
            "warning_min",
            "warning_max",
            "critical_min",
            "critical_max",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)

        csv_content = output.getvalue()
        output.close()

        return {
            "format": "csv",
            "content_type": "text/csv; charset=utf-8",
            "filename": f"telemetry_{machine.asset_code}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
            "data": csv_content,
            "record_count": len(records),
        }

