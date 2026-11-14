import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

from app.extensions import db
from app.models.equipment import Machine
from app.models.signal_mapping import MachineSignal
from app.models.monitoring import SignalReading
from app.models.condition import DataQualityEvent, QualityState
from app.modules.data_quality.engine import DataQualityEngine

logger = logging.getLogger(__name__)


class DataQualityService:
    """Service providing data quality evaluation, storage of events, and health reporting."""

    @classmethod
    def evaluate_machine_quality(
        cls, machine_id: str, organization_id: str, recent_minutes: int = 15
    ) -> Dict[str, Any]:
        """Assess data quality across all active signals of a machine and log any issues."""
        machine = db.session.get(Machine, machine_id)
        if not machine or machine.organization_id != organization_id:
            raise ValueError("Equipment not found or access denied.")

        signals = MachineSignal.query.filter_by(
            machine_id=machine_id, organization_id=organization_id, enabled=True
        ).all()

        total_signals = len(signals)
        evaluated_signals = []
        overall_good_count = 0
        overall_suspect_count = 0
        overall_bad_count = 0
        overall_missing_count = 0

        for sig in signals:
            # Query the 25 most recent readings for this signal to check trends, spikes, and freezing
            recent_readings = (
                SignalReading.query.filter_by(signal_id=sig.id, machine_id=machine_id)
                .order_by(SignalReading.source_timestamp.desc())
                .limit(25)
                .all()
            )

            if not recent_readings:
                overall_missing_count += 1
                evaluated_signals.append({
                    "signal_id": sig.id,
                    "signal_code": sig.signal_definition.signal_code if sig.signal_definition else None,
                    "custom_name": sig.custom_name,
                    "quality_state": QualityState.MISSING,
                    "is_usable": False,
                    "issues": [{"type": "NO_DATA", "severity": "CRITICAL", "message": "Zero readings received for this sensor."}],
                })
                continue

            latest = recent_readings[0].to_dict()
            history = [r.to_dict() for r in recent_readings[1:]]

            result = DataQualityEngine.evaluate_reading(
                signal=sig, reading=latest, recent_history=history
            )

            # Record event in database if issue was detected
            if result.issues:
                for issue in result.issues:
                    event = DataQualityEvent(
                        organization_id=organization_id,
                        machine_id=machine_id,
                        signal_id=sig.id,
                        reading_id=latest.get("id"),
                        quality_state=result.quality_state,
                        issue_type=issue["type"],
                        details=issue,
                        detected_at=datetime.now(timezone.utc),
                    )
                    db.session.add(event)

            if result.quality_state == QualityState.GOOD:
                overall_good_count += 1
            elif result.quality_state == QualityState.SUSPECT:
                overall_suspect_count += 1
            elif result.quality_state == QualityState.BAD:
                overall_bad_count += 1
            else:
                overall_missing_count += 1

            evaluated_signals.append({
                "signal_id": sig.id,
                "signal_code": sig.signal_definition.signal_code if sig.signal_definition else None,
                "custom_name": sig.custom_name,
                "quality_state": result.quality_state,
                "is_usable": result.is_usable_for_baseline,
                "issues": result.issues,
                "latest_value": result.sanitized_value or latest.get("normalized_value"),
            })

        db.session.commit()

        # Compute data quality score (0 to 100%)
        quality_score = 0.0
        if total_signals > 0:
            quality_score = round(
                ((overall_good_count * 1.0 + overall_suspect_count * 0.5) / total_signals) * 100.0,
                1
            )

        # Determine overall quality state
        if overall_bad_count > 0:
            overall_state = QualityState.BAD
        elif overall_missing_count > 0:
            overall_state = QualityState.MISSING
        elif overall_suspect_count > 0:
            overall_state = QualityState.SUSPECT
        else:
            overall_state = QualityState.GOOD

        return {
            "machine_id": machine_id,
            "machine_name": machine.equipment_name,
            "overall_state": overall_state,
            "quality_score_pct": quality_score,
            "total_signals": total_signals,
            "good_count": overall_good_count,
            "suspect_count": overall_suspect_count,
            "bad_count": overall_bad_count,
            "missing_count": overall_missing_count,
            "signals": evaluated_signals,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def get_quality_events(
        cls, machine_id: str, organization_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Retrieve recent data quality audit events for a machine."""
        events = (
            DataQualityEvent.query.filter_by(
                machine_id=machine_id, organization_id=organization_id
            )
            .order_by(DataQualityEvent.detected_at.desc())
            .limit(min(200, limit))
            .all()
        )
        return [e.to_dict() for e in events]

