import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from app.extensions import db
from app.models.monitoring import SignalThreshold
from app.models.signal_mapping import MachineSignal
from app.models.condition import BaselineProfile, BaselineVersion

logger = logging.getLogger(__name__)


class ThresholdService:
    """Service managing operational visualization thresholds for industrial signals.
    
    Adheres to strict pharmaceutical standards:
    - Visualization thresholds indicate process drift for predictive maintenance.
    - Explicitly distinguished from validated Critical Quality Attributes (CQA) or Critical Process Parameters (CPP).
    - If no threshold is configured, clearly indicates unconfigured status rather than fabricating arbitrary limits.
    """

    @classmethod
    def get_thresholds_for_machine(
        cls,
        machine_id: str,
        organization_id: str
    ) -> Dict[str, Any]:
        """Retrieve operational thresholds for all mapped signals of an equipment asset."""
        signals = MachineSignal.query.filter_by(
            machine_id=machine_id,
            organization_id=organization_id,
        ).all()

        threshold_map: Dict[str, Any] = {}

        for sig in signals:
            thresh = SignalThreshold.query.filter_by(
                signal_id=sig.id,
                organization_id=organization_id,
                is_active=True,
            ).first()

            if thresh:
                threshold_map[sig.id] = {
                    "signal_id": sig.id,
                    "signal_name": sig.custom_name or (sig.signal_definition.name if sig.signal_definition else sig.signal_code),
                    "signal_group": sig.signal_definition.signal_group if sig.signal_definition else "Other",
                    "unit": thresh.unit or sig.normalized_unit or (sig.signal_definition.standard_unit if sig.signal_definition else None),
                    "warning_min": thresh.warning_min,
                    "warning_max": thresh.warning_max,
                    "critical_min": thresh.critical_min,
                    "critical_max": thresh.critical_max,
                    "is_active": thresh.is_active,
                    "source": "CONFIGURED_OPERATIONAL_THRESHOLD",
                    "configured": True,
                    "notes": thresh.notes,
                    "updated_at": thresh.updated_at.isoformat() if thresh.updated_at else None,
                }
            else:
                # Check if baseline profile exists for statistical context
                baseline = (
                    BaselineProfile.query
                    .filter_by(signal_id=sig.id, machine_id=machine_id)
                    .first()
                )
                active_ver = None
                if baseline:
                    active_ver = baseline.versions.filter_by(version_number=baseline.active_version_number).first()

                if active_ver and active_ver.p5 is not None and active_ver.p95 is not None:
                    threshold_map[sig.id] = {
                        "signal_id": sig.id,
                        "signal_name": sig.custom_name or (sig.signal_definition.name if sig.signal_definition else sig.signal_code),
                        "signal_group": sig.signal_definition.signal_group if sig.signal_definition else "Other",
                        "unit": sig.normalized_unit or (sig.signal_definition.standard_unit if sig.signal_definition else None),
                        "warning_min": active_ver.p5,
                        "warning_max": active_ver.p95,
                        "critical_min": active_ver.min_value,
                        "critical_max": active_ver.max_value,
                        "is_active": True,
                        "source": "STATISTICAL_BASELINE_ENVELOPE",
                        "configured": True,
                        "notes": "Derived from approved baseline statistical distribution (P05/P95).",
                        "updated_at": active_ver.created_at.isoformat() if active_ver.created_at else None,
                    }
                else:
                    threshold_map[sig.id] = {
                        "signal_id": sig.id,
                        "signal_name": sig.custom_name or (sig.signal_definition.name if sig.signal_definition else sig.signal_code),
                        "signal_group": sig.signal_definition.signal_group if sig.signal_definition else "Other",
                        "unit": sig.normalized_unit or (sig.signal_definition.standard_unit if sig.signal_definition else None),
                        "warning_min": None,
                        "warning_max": None,
                        "critical_min": None,
                        "critical_max": None,
                        "is_active": False,
                        "source": "NONE",
                        "configured": False,
                        "notes": "No threshold configured.",
                        "updated_at": None,
                    }

        return threshold_map

    @classmethod
    def set_signal_threshold(
        cls,
        organization_id: str,
        machine_id: str,
        signal_id: str,
        warning_min: Optional[float] = None,
        warning_max: Optional[float] = None,
        critical_min: Optional[float] = None,
        critical_max: Optional[float] = None,
        unit: Optional[str] = None,
        notes: Optional[str] = None,
        is_active: bool = True,
        user_id: Optional[str] = None,
    ) -> SignalThreshold:
        """Create or update operational threshold bounds for a signal."""
        # Validation checks
        if warning_min is not None and warning_max is not None and warning_min > warning_max:
            raise ValueError(f"warning_min ({warning_min}) cannot be greater than warning_max ({warning_max}).")
        if critical_min is not None and critical_max is not None and critical_min > critical_max:
            raise ValueError(f"critical_min ({critical_min}) cannot be greater than critical_max ({critical_max}).")
        if warning_max is not None and critical_max is not None and warning_max > critical_max:
            raise ValueError(f"warning_max ({warning_max}) cannot be greater than critical_max ({critical_max}).")
        if warning_min is not None and critical_min is not None and warning_min < critical_min:
            raise ValueError(f"warning_min ({warning_min}) cannot be less than critical_min ({critical_min}).")

        thresh = SignalThreshold.query.filter_by(
            organization_id=organization_id,
            machine_id=machine_id,
            signal_id=signal_id,
        ).first()

        now = datetime.now(timezone.utc)
        if not thresh:
            thresh = SignalThreshold(
                id=str(uuid.uuid4()),
                organization_id=organization_id,
                machine_id=machine_id,
                signal_id=signal_id,
                warning_min=warning_min,
                warning_max=warning_max,
                critical_min=critical_min,
                critical_max=critical_max,
                unit=unit,
                is_active=is_active,
                notes=notes,
                created_at=now,
                updated_at=now,
                created_by_user_id=user_id,
            )
            db.session.add(thresh)
        else:
            thresh.warning_min = warning_min
            thresh.warning_max = warning_max
            thresh.critical_min = critical_min
            thresh.critical_max = critical_max
            thresh.unit = unit
            thresh.is_active = is_active
            thresh.notes = notes
            thresh.updated_at = now
            if user_id:
                thresh.created_by_user_id = user_id

        db.session.commit()
        return thresh

    @classmethod
    def evaluate_value(cls, value: Optional[float], threshold_dict: Optional[Dict[str, Any]]) -> str:
        """Classify a numeric value against threshold bounds into NORMAL, WARNING, CRITICAL, or UNCONFIGURED."""
        if value is None or not threshold_dict or not threshold_dict.get("configured"):
            return "UNCONFIGURED"

        crit_min = threshold_dict.get("critical_min")
        crit_max = threshold_dict.get("critical_max")
        warn_min = threshold_dict.get("warning_min")
        warn_max = threshold_dict.get("warning_max")

        # Critical breaches
        if crit_max is not None and value >= crit_max:
            return "CRITICAL"
        if crit_min is not None and value <= crit_min:
            return "CRITICAL"

        # Warning breaches
        if warn_max is not None and value >= warn_max:
            return "WARNING"
        if warn_min is not None and value <= warn_min:
            return "WARNING"

        return "NORMAL"

