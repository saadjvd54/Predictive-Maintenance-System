"""
PharmaPredict AI — Phase 3, Step 3.3: Plant-Wide Observability & Fleet Monitoring Service
========================================================================================
Centralized fleet monitoring service adhering to strict pharmaceutical standards:
- Aggregates plant-wide telemetry, operational states, data freshness, and alerts.
- Evaluates operational status without fabricating industrial limits or machine predictions.
- Eliminates N+1 database queries through eager loading and bulk relation mappings.
- Enforces strict multi-tenant isolation (organization_id boundaries).
- Accurately distinguishes machine operational state from telemetry pipeline connection state.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy import func, or_, desc, asc
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.equipment import Machine, EquipmentCategory
from app.models.tenant import Site
from app.models.signal_mapping import MachineSignal
from app.models.monitoring import (
    MonitoringSession,
    MonitoringState,
    SignalReading,
    SignalThreshold,
    SignalFreshness,
)
from app.models.condition import EquipmentAlert, AlertStatus, AnomalySeverity
from app.modules.monitoring.threshold_service import ThresholdService

logger = logging.getLogger(__name__)


class FleetMonitoringService:
    """Plant-wide monitoring and equipment fleet observability engine."""

    # Telemetry freshness thresholds (in seconds)
    FRESH_THRESHOLD_SECONDS = 30
    DELAYED_THRESHOLD_SECONDS = 60
    STALE_THRESHOLD_SECONDS = 300

    @classmethod
    def get_plant_overview(cls, organization_id: str) -> Dict[str, Any]:
        """Compute plant-wide fleet KPI summary from actual database records.
        
        Metrics:
        - Total registered equipment
        - Currently monitoring equipment
        - Healthy equipment
        - Warning equipment
        - Critical equipment
        - Offline equipment
        - Stale equipment
        - Not configured equipment
        - Active alerts count (Warning and Critical)
        """
        now = datetime.now(timezone.utc)

        # 1. Total registered equipment for organization
        total_equipment = Machine.query.filter_by(organization_id=organization_id).count()

        # 2. Get fleet items to compute exact status distribution
        fleet_data = cls.get_fleet_machines(
            organization_id=organization_id,
            limit_all=True,
        )

        status_counts = fleet_data["status_counts"]
        monitoring_count = fleet_data["monitoring_count"]

        # 3. Active open/acknowledged alerts count
        active_alerts_query = EquipmentAlert.query.filter(
            EquipmentAlert.organization_id == organization_id,
            EquipmentAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.UNDER_INVESTIGATION]),
        )
        active_alerts_count = active_alerts_query.count()
        critical_alerts_count = active_alerts_query.filter(EquipmentAlert.severity == AnomalySeverity.CRITICAL).count()
        warning_alerts_count = active_alerts_query.filter(EquipmentAlert.severity == AnomalySeverity.WARNING).count()

        return {
            "organization_id": organization_id,
            "generated_at": now.isoformat(),
            "total_equipment": total_equipment,
            "monitoring_equipment": monitoring_count,
            "healthy_equipment": status_counts.get("HEALTHY", 0),
            "warning_equipment": status_counts.get("WARNING", 0),
            "critical_equipment": status_counts.get("CRITICAL", 0),
            "offline_equipment": status_counts.get("OFFLINE", 0),
            "stale_equipment": status_counts.get("STALE", 0),
            "not_configured_equipment": status_counts.get("NOT CONFIGURED", 0),
            "active_alerts_count": active_alerts_count,
            "critical_alerts_count": critical_alerts_count,
            "warning_alerts_count": warning_alerts_count,
            "simulator_flag": True,
        }

    @classmethod
    def get_fleet_machines(
        cls,
        organization_id: str,
        site_id: Optional[str] = None,
        category_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        sort_by: str = "severity",
        order: str = "asc",
        page: int = 1,
        per_page: int = 12,
        limit_all: bool = False,
    ) -> Dict[str, Any]:
        """Retrieve searchable, filterable, paginated fleet of equipment with real-time status.
        
        Uses bulk-loaded queries to avoid N+1 database operations.
        """
        now = datetime.now(timezone.utc)

        # Base query with eager loaded site & category
        query = (
            Machine.query.filter_by(organization_id=organization_id)
            .options(joinedload(Machine.site), joinedload(Machine.category))
        )

        if site_id:
            query = query.filter(Machine.site_id == site_id)
        if category_id:
            query = query.filter(Machine.category_id == category_id)
        if search:
            s = f"%{search.strip().lower()}%"
            query = query.filter(
                or_(
                    func.lower(Machine.equipment_name).like(s),
                    func.lower(Machine.asset_code).like(s),
                    func.lower(Machine.serial_number).like(s),
                )
            )

        all_matching_machines = query.all()
        machine_ids = [m.id for m in all_matching_machines]

        if not machine_ids:
            return {
                "items": [],
                "total": 0,
                "page": page,
                "per_page": per_page,
                "pages": 0,
                "monitoring_count": 0,
                "status_counts": {
                    "HEALTHY": 0,
                    "WARNING": 0,
                    "CRITICAL": 0,
                    "OFFLINE": 0,
                    "STALE": 0,
                    "NOT CONFIGURED": 0,
                },
                "sites": [],
                "categories": [],
            }

        # ----------------------------------------------------------------------
        # Bulk Fetch 1: Count of mapped & enabled signals per machine
        # ----------------------------------------------------------------------
        signal_counts_raw = (
            db.session.query(MachineSignal.machine_id, func.count(MachineSignal.id))
            .filter(
                MachineSignal.machine_id.in_(machine_ids),
                MachineSignal.organization_id == organization_id,
                MachineSignal.enabled.is_(True),
            )
            .group_by(MachineSignal.machine_id)
            .all()
        )
        signal_counts_map = {row[0]: row[1] for row in signal_counts_raw}

        # ----------------------------------------------------------------------
        # Bulk Fetch 2: Latest monitoring sessions per machine
        # ----------------------------------------------------------------------
        sessions_raw = (
            MonitoringSession.query.filter(
                MonitoringSession.machine_id.in_(machine_ids),
                MonitoringSession.organization_id == organization_id,
            )
            .order_by(MonitoringSession.created_at.desc())
            .all()
        )
        latest_session_map = {}
        for sess in sessions_raw:
            if sess.machine_id not in latest_session_map:
                latest_session_map[sess.machine_id] = sess

        # ----------------------------------------------------------------------
        # Bulk Fetch 3: Active Alerts (OPEN, ACKNOWLEDGED) per machine
        # ----------------------------------------------------------------------
        active_alerts_raw = (
            EquipmentAlert.query.filter(
                EquipmentAlert.machine_id.in_(machine_ids),
                EquipmentAlert.organization_id == organization_id,
                EquipmentAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.UNDER_INVESTIGATION]),
            )
            .order_by(EquipmentAlert.last_detected_at.desc())
            .all()
        )
        machine_alerts_map: Dict[str, List[EquipmentAlert]] = {}
        for a in active_alerts_raw:
            machine_alerts_map.setdefault(a.machine_id, []).append(a)

        # ----------------------------------------------------------------------
        # Bulk Fetch 4: Active configured thresholds per machine
        # ----------------------------------------------------------------------
        thresholds_raw = (
            SignalThreshold.query.filter(
                SignalThreshold.machine_id.in_(machine_ids),
                SignalThreshold.organization_id == organization_id,
                SignalThreshold.is_active.is_(True),
            )
            .all()
        )
        machine_thresholds_map: Dict[str, Dict[str, Dict[str, Any]]] = {}
        for th in thresholds_raw:
            machine_thresholds_map.setdefault(th.machine_id, {})[th.signal_id] = {
                "warning_min": th.warning_min,
                "warning_max": th.warning_max,
                "critical_min": th.critical_min,
                "critical_max": th.critical_max,
                "unit": th.unit,
                "configured": True,
            }

        # ----------------------------------------------------------------------
        # Bulk Fetch 5: Latest readings timestamp per machine
        # ----------------------------------------------------------------------
        latest_ts_raw = (
            db.session.query(SignalReading.machine_id, func.max(SignalReading.source_timestamp))
            .filter(
                SignalReading.machine_id.in_(machine_ids),
                SignalReading.organization_id == organization_id,
            )
            .group_by(SignalReading.machine_id)
            .all()
        )
        latest_ts_map = {row[0]: row[1] for row in latest_ts_raw}

        # ----------------------------------------------------------------------
        # Bulk Fetch 6: Check for latest readings with threshold violations
        # To avoid unbounded queries, fetch readings within last 1 hour for active machines
        # ----------------------------------------------------------------------
        recent_readings_raw = (
            db.session.query(
                SignalReading.machine_id,
                SignalReading.signal_id,
                SignalReading.normalized_value,
                SignalReading.source_value,
                SignalReading.normalized_unit,
                SignalReading.quality_code,
                SignalReading.source_timestamp,
            )
            .filter(
                SignalReading.machine_id.in_(machine_ids),
                SignalReading.organization_id == organization_id,
                SignalReading.source_timestamp >= now - timedelta(hours=1),
            )
            .order_by(SignalReading.source_timestamp.desc())
            .all()
        )

        # Map latest reading per signal per machine
        latest_reading_per_sig: Dict[str, Dict[str, Any]] = {}
        for r in recent_readings_raw:
            m_id = r[0]
            s_id = r[1]
            if m_id not in latest_reading_per_sig:
                latest_reading_per_sig[m_id] = {}
            if s_id not in latest_reading_per_sig[m_id]:
                latest_reading_per_sig[m_id][s_id] = {
                    "signal_id": s_id,
                    "normalized_value": r[2],
                    "source_value": r[3],
                    "unit": r[4],
                    "quality_code": r[5],
                    "timestamp": r[6],
                }

        # ----------------------------------------------------------------------
        # Classify each machine & compile fleet items
        # ----------------------------------------------------------------------
        all_items: List[Dict[str, Any]] = []
        global_status_counts = {
            "HEALTHY": 0,
            "WARNING": 0,
            "CRITICAL": 0,
            "OFFLINE": 0,
            "STALE": 0,
            "NOT CONFIGURED": 0,
        }
        monitoring_count = 0

        for machine in all_matching_machines:
            m_id = machine.id
            signals_count = signal_counts_map.get(m_id, 0)
            session = latest_session_map.get(m_id)
            alerts = machine_alerts_map.get(m_id, [])
            thresholds = machine_thresholds_map.get(m_id, {})
            latest_ts = latest_ts_map.get(m_id)

            if latest_ts and latest_ts.tzinfo is None:
                latest_ts = latest_ts.replace(tzinfo=timezone.utc)

            desired_state = session.desired_state if session else MonitoringState.STOPPED
            observed_state = session.observed_state if session else MonitoringState.STOPPED

            is_actively_monitoring = (
                desired_state == MonitoringState.ACTIVE or
                observed_state in [MonitoringState.ACTIVE, MonitoringState.DEGRADED, MonitoringState.ACTIVATING]
            )
            if is_actively_monitoring:
                monitoring_count += 1

            # Compute Data Freshness
            freshness = SignalFreshness.UNAVAILABLE
            age_seconds = None
            if latest_ts:
                age_seconds = max(0.0, (now - latest_ts).total_seconds())
                if age_seconds <= cls.FRESH_THRESHOLD_SECONDS:
                    freshness = SignalFreshness.FRESH
                elif age_seconds <= cls.DELAYED_THRESHOLD_SECONDS:
                    freshness = SignalFreshness.DELAYED
                else:
                    freshness = SignalFreshness.STALE

            # Check threshold breaches in latest readings
            sig_readings = latest_reading_per_sig.get(m_id, {})
            breaches = []
            has_crit_breach = False
            has_warn_breach = False

            for s_id, r_data in sig_readings.items():
                s_thresh = thresholds.get(s_id)
                if s_thresh and s_thresh.get("configured"):
                    val = r_data["normalized_value"]
                    eval_status = ThresholdService.evaluate_value(val, s_thresh)
                    if eval_status == "CRITICAL":
                        has_crit_breach = True
                        breaches.append({
                            "signal_id": s_id,
                            "value": val,
                            "unit": r_data["unit"],
                            "status": "CRITICAL",
                        })
                    elif eval_status == "WARNING":
                        has_warn_breach = True
                        breaches.append({
                            "signal_id": s_id,
                            "value": val,
                            "unit": r_data["unit"],
                            "status": "WARNING",
                        })

            # Check active alerts for critical / warning
            has_crit_alert = any(a.severity == AnomalySeverity.CRITICAL for a in alerts)
            has_warn_alert = any(a.severity == AnomalySeverity.WARNING for a in alerts)

            # Strict Status Classification Hierarchy (Requirement 3)
            # 1. NOT CONFIGURED: No signals mapped
            # 2. OFFLINE: Monitoring stopped or inactive
            # 3. CRITICAL: Critical alert or critical threshold breach
            # 4. WARNING: Warning alert or warning threshold breach
            # 5. STALE: Monitoring active but no telemetry received within freshness window
            # 6. HEALTHY: Monitoring active, telemetry fresh, normal limits
            calculated_status: str

            if signals_count == 0:
                calculated_status = "NOT CONFIGURED"
            elif not is_actively_monitoring:
                calculated_status = "OFFLINE"
            elif has_crit_alert or has_crit_breach:
                calculated_status = "CRITICAL"
            elif has_warn_alert or has_warn_breach:
                calculated_status = "WARNING"
            elif latest_ts is None or age_seconds is None or age_seconds > cls.DELAYED_THRESHOLD_SECONDS:
                calculated_status = "STALE"
            else:
                calculated_status = "HEALTHY"

            global_status_counts[calculated_status] = global_status_counts.get(calculated_status, 0) + 1

            item = {
                "id": machine.id,
                "asset_code": machine.asset_code,
                "equipment_name": machine.equipment_name,
                "category_id": machine.category_id,
                "equipment_type": machine.category.name if machine.category else "Unassigned",
                "site_id": machine.site_id,
                "site_name": machine.site.name if machine.site else "Unassigned",
                "location": getattr(machine, "location", None) or (machine.site.name if machine.site else "Main Facility"),
                "status": calculated_status,
                "monitoring_state": observed_state,
                "desired_state": desired_state,
                "is_actively_monitoring": is_actively_monitoring,
                "signals_count": signals_count,
                "active_alerts_count": len(alerts),
                "highest_alert_severity": (
                    "CRITICAL" if has_crit_alert else "WARNING" if has_warn_alert else None
                ),
                "latest_telemetry_at": latest_ts.isoformat() if latest_ts else None,
                "data_freshness": freshness,
                "telemetry_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
                "threshold_breaches": breaches,
                "created_at": machine.created_at.isoformat() if machine.created_at else None,
            }
            all_items.append(item)

        # If only requesting overview metrics, return early
        if limit_all:
            return {
                "status_counts": global_status_counts,
                "monitoring_count": monitoring_count,
            }

        # Filter by status if requested
        filtered_items = all_items
        if status:
            target_status = status.strip().upper()
            filtered_items = [it for it in all_items if it["status"] == target_status]

        # Sorting
        severity_rank = {
            "CRITICAL": 1,
            "WARNING": 2,
            "STALE": 3,
            "OFFLINE": 4,
            "NOT CONFIGURED": 5,
            "HEALTHY": 6,
        }

        reverse_order = order.lower() == "desc"

        if sort_by == "severity":
            filtered_items.sort(
                key=lambda x: severity_rank.get(x["status"], 99),
                reverse=reverse_order,
            )
        elif sort_by == "latest_telemetry":
            filtered_items.sort(
                key=lambda x: x["latest_telemetry_at"] or "",
                reverse=not reverse_order,  # Default newest first
            )
        elif sort_by == "asset_code":
            filtered_items.sort(
                key=lambda x: x["asset_code"].lower(),
                reverse=reverse_order,
            )
        elif sort_by == "name":
            filtered_items.sort(
                key=lambda x: x["equipment_name"].lower(),
                reverse=reverse_order,
            )

        # Pagination
        total_matching = len(filtered_items)
        effective_page = max(1, page)
        effective_per_page = max(1, min(100, per_page))
        total_pages = (total_matching + effective_per_page - 1) // effective_per_page if total_matching > 0 else 1

        start_idx = (effective_page - 1) * effective_per_page
        end_idx = start_idx + effective_per_page
        paginated_items = filtered_items[start_idx:end_idx]

        # Extract distinct sites and categories with counts
        site_counts: Dict[str, Dict[str, Any]] = {}
        category_counts: Dict[str, Dict[str, Any]] = {}

        for m in all_matching_machines:
            if m.site:
                s_id = m.site.id
                if s_id not in site_counts:
                    site_counts[s_id] = {"id": s_id, "name": m.site.name, "count": 0}
                site_counts[s_id]["count"] += 1

            if m.category:
                c_id = m.category.id
                if c_id not in category_counts:
                    category_counts[c_id] = {"id": c_id, "name": m.category.name, "count": 0}
                category_counts[c_id]["count"] += 1

        return {
            "items": paginated_items,
            "total": total_matching,
            "page": effective_page,
            "per_page": effective_per_page,
            "pages": total_pages,
            "status_counts": global_status_counts,
            "sites": list(site_counts.values()),
            "categories": list(category_counts.values()),
        }

    @classmethod
    def get_fleet_alerts(
        cls,
        organization_id: str,
        status: Optional[str] = None,
        severity: Optional[str] = None,
        machine_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve active plant-wide alarms with equipment and threshold context."""
        query = (
            EquipmentAlert.query.filter_by(organization_id=organization_id)
            .options(
                joinedload(EquipmentAlert.machine).joinedload(Machine.site),
                joinedload(EquipmentAlert.anomaly),
            )
        )

        if machine_id:
            query = query.filter(EquipmentAlert.machine_id == machine_id)

        if status and status.upper() != "ALL":
            query = query.filter(EquipmentAlert.status == status.upper())
        else:
            # Default to active unclosed alarms
            query = query.filter(
                EquipmentAlert.status.in_([AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED, AlertStatus.UNDER_INVESTIGATION])
            )

        if severity and severity.upper() != "ALL":
            query = query.filter(EquipmentAlert.severity == severity.upper())

        alerts = (
            query.order_by(
                desc(EquipmentAlert.last_detected_at),
                desc(EquipmentAlert.first_detected_at)
            )
            .limit(max(1, min(200, limit)))
            .all()
        )

        results: List[Dict[str, Any]] = []
        for a in alerts:
            mach = a.machine
            anomaly = a.anomaly

            # Extract evidence signal if present
            signal_name = "Overall Machine"
            observed_val = None
            if anomaly and anomaly.evidence_items:
                ev = anomaly.evidence_items[0]
                if ev.signal:
                    signal_name = ev.signal.custom_name or ev.signal.source_node_id
                observed_val = ev.observed_value

            results.append({
                "id": a.id,
                "machine_id": a.machine_id,
                "asset_code": mach.asset_code if mach else "N/A",
                "equipment_name": mach.equipment_name if mach else "Unknown Asset",
                "site_name": mach.site.name if (mach and mach.site) else "Unassigned",
                "severity": a.severity,
                "status": a.status,
                "signal_name": signal_name,
                "observed_value": observed_val,
                "first_detected_at": a.first_detected_at.isoformat() if a.first_detected_at else None,
                "last_detected_at": a.last_detected_at.isoformat() if a.last_detected_at else None,
                "acknowledged_by": a.acknowledged_by,
                "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
                "resolution_notes": a.resolution_notes,
                "anomaly_summary": anomaly.summary if anomaly else None,
            })

        return results

    @classmethod
    def acknowledge_alert(
        cls,
        organization_id: str,
        alert_id: str,
        user_id: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Acknowledge an equipment alarm through an authorized user action."""
        from app.modules.alerts.services import AlertService
        alert = AlertService.acknowledge_alert(
            alert_id=alert_id,
            organization_id=organization_id,
            user_id=user_id,
            notes=notes or "Alert acknowledged via Plant-Wide Fleet Monitoring Dashboard.",
        )
        return alert.to_dict()
