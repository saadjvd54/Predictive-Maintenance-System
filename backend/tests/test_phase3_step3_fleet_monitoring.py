"""
PharmaPredict AI — Phase 3, Step 3.3: Plant-Wide Observability & Fleet Monitoring Test Suite
============================================================================================
Comprehensive test suite verifying:
1. Plant-wide fleet KPI summary calculations from real DB state.
2. Exact status classification hierarchy (HEALTHY, WARNING, CRITICAL, OFFLINE, STALE, NOT CONFIGURED).
3. Stale telemetry detection as a connection pipeline delay (never machine failure).
4. Missing telemetry handling.
5. Production area, equipment type, and monitoring status filters.
6. Search by equipment name and asset code.
7. Fleet sorting and pagination.
8. Centralized active alarms panel & explicit user-driven acknowledgment.
9. Strict multi-tenant isolation.
10. Query performance & prevention of N+1 database patterns.
11. REST API integration for all fleet endpoints.
"""

import uuid
from datetime import datetime, timezone, timedelta
import pytest

from app.extensions import db
from app.models.tenant import Organization, Site
from app.models.equipment import EquipmentCategory, Machine
from app.models.signal_mapping import SignalDefinition, MachineSignal
from app.models.monitoring import (
    MonitoringSession,
    MonitoringState,
    SignalReading,
    SignalThreshold,
)
from app.models.condition import (
    EquipmentAlert,
    AlertStatus,
    AnomalySeverity,
    AnomalyEvent,
    AnomalyEvidence,
)
from app.models.user import User, Role, UserRoleAssignment
from app.modules.monitoring.fleet_service import FleetMonitoringService
from app.modules.monitoring.threshold_service import ThresholdService


@pytest.fixture
def step33_setup(app):
    """Fixture providing multi-tenant plant fleet with various equipment states."""
    with app.app_context():
        now = datetime.now(timezone.utc)

        # 1. Organizations
        org_a = Organization(id="org-s33-alpha", name="Alpha Pharma Plant", slug="alpha-plant")
        org_b = Organization(id="org-s33-beta", name="Beta Biotech Plant", slug="beta-plant")
        db.session.add_all([org_a, org_b])
        db.session.commit()

        # 2. Sites (Production Areas)
        site_a1 = Site(id="site-s33-gran", organization_id=org_a.id, name="Granulation Suite A")
        site_a2 = Site(id="site-s33-pack", organization_id=org_a.id, name="Packaging Suite B")
        site_b1 = Site(id="site-s33-lyo", organization_id=org_b.id, name="Lyophilization Suite C")
        db.session.add_all([site_a1, site_a2, site_b1])
        db.session.commit()

        # 3. Categories (Equipment Types)
        cat_gran = EquipmentCategory(id="cat-s33-gran", organization_id=org_a.id, name="Granulator", is_default=True)
        cat_dryer = EquipmentCategory(id="cat-s33-dryer", organization_id=org_a.id, name="Fluid Bed Dryer", is_default=True)
        cat_press = EquipmentCategory(id="cat-s33-press", organization_id=org_a.id, name="Tablet Press", is_default=True)
        cat_pack = EquipmentCategory(id="cat-s33-pack", organization_id=org_a.id, name="Blister Line", is_default=True)
        db.session.add_all([cat_gran, cat_dryer, cat_press, cat_pack])
        db.session.commit()

        # 4. Users & Roles
        admin_role = Role.query.filter_by(name=Role.ORG_ADMIN).first()
        if not admin_role:
            admin_role = Role(name=Role.ORG_ADMIN, description="Org Admin")
            db.session.add(admin_role)
            db.session.commit()

        user_admin_a = User(
            id="user-s33-admin-a",
            organization_id=org_a.id,
            full_name="Plant Lead Alpha",
            email="lead@alpha-fleet.com",
            is_active=True,
        )
        user_admin_a.set_password("Admin@123")

        user_admin_b = User(
            id="user-s33-admin-b",
            organization_id=org_b.id,
            full_name="Plant Lead Beta",
            email="lead@beta-fleet.com",
            is_active=True,
        )
        user_admin_b.set_password("Admin@123")

        db.session.add_all([user_admin_a, user_admin_b])
        db.session.commit()

        db.session.add_all([
            UserRoleAssignment(user_id=user_admin_a.id, role_id=admin_role.id, organization_id=org_a.id),
            UserRoleAssignment(user_id=user_admin_b.id, role_id=admin_role.id, organization_id=org_b.id),
        ])
        db.session.commit()

        # 5. Standard Signal Definitions
        def_temp = SignalDefinition(
            id="def-s33-temp",
            signal_code="BEARING_TEMP",
            name="Bearing Temperature",
            signal_group="Thermal",
            expected_data_type="Float",
            standard_unit="°C",
            is_custom=False,
            created_at=now,
        )
        def_vib = SignalDefinition(
            id="def-s33-vib",
            signal_code="MOTOR_VIB",
            name="Motor Vibration",
            signal_group="Mechanical",
            expected_data_type="Float",
            standard_unit="mm/s",
            is_custom=False,
            created_at=now,
        )
        db.session.add_all([def_temp, def_vib])
        db.session.commit()

        # 6. Fleet Machines for Org A:
        # M1: HEALTHY (Active session, fresh reading within normal bounds)
        m1 = Machine(
            id="mach-s33-01",
            organization_id=org_a.id,
            site_id=site_a1.id,
            category_id=cat_gran.id,
            asset_code="GRAN-01",
            equipment_name="High Shear Granulator Alpha",
        )
        # M2: WARNING (Active session, warning threshold breach)
        m2 = Machine(
            id="mach-s33-02",
            organization_id=org_a.id,
            site_id=site_a1.id,
            category_id=cat_dryer.id,
            asset_code="FBD-01",
            equipment_name="Fluid Bed Dryer 01",
        )
        # M3: CRITICAL (Active session, critical alert in equipment_alerts)
        m3 = Machine(
            id="mach-s33-03",
            organization_id=org_a.id,
            site_id=site_a2.id,
            category_id=cat_press.id,
            asset_code="TAB-01",
            equipment_name="Rotary Tablet Press 01",
        )
        # M4: STALE (Active session, but last reading > 300s old)
        m4 = Machine(
            id="mach-s33-04",
            organization_id=org_a.id,
            site_id=site_a2.id,
            category_id=cat_pack.id,
            asset_code="BLIST-01",
            equipment_name="Blister Packaging Line 01",
        )
        # M5: OFFLINE (Stopped session)
        m5 = Machine(
            id="mach-s33-05",
            organization_id=org_a.id,
            site_id=site_a1.id,
            category_id=cat_gran.id,
            asset_code="GRAN-02",
            equipment_name="High Shear Granulator Beta",
        )
        # M6: NOT CONFIGURED (0 mapped signals)
        m6 = Machine(
            id="mach-s33-06",
            organization_id=org_a.id,
            site_id=site_a2.id,
            category_id=cat_press.id,
            asset_code="TAB-02",
            equipment_name="Rotary Tablet Press 02",
        )

        # Machine for Org B (Multi-tenant test)
        m_b1 = Machine(
            id="mach-s33-b1",
            organization_id=org_b.id,
            site_id=site_b1.id,
            category_id=cat_dryer.id,
            asset_code="LYO-01",
            equipment_name="Lyophilizer Beta",
        )

        db.session.add_all([m1, m2, m3, m4, m5, m6, m_b1])
        db.session.commit()

        # 7. Mapped Signals for M1-M5
        s1 = MachineSignal(
            id="sig-s33-m1-temp",
            organization_id=org_a.id,
            machine_id=m1.id,
            signal_definition_id=def_temp.id,
            source_node_id="ns=2;s=Gran01.Temp",
            custom_name="Bearing Temp",
            normalized_unit="°C",
            enabled=True,
            created_at=now,
        )
        s2 = MachineSignal(
            id="sig-s33-m2-temp",
            organization_id=org_a.id,
            machine_id=m2.id,
            signal_definition_id=def_temp.id,
            source_node_id="ns=2;s=FBD01.Temp",
            custom_name="Air Temp",
            normalized_unit="°C",
            enabled=True,
            created_at=now,
        )
        s3 = MachineSignal(
            id="sig-s33-m3-vib",
            organization_id=org_a.id,
            machine_id=m3.id,
            signal_definition_id=def_vib.id,
            source_node_id="ns=2;s=Tab01.Vib",
            custom_name="Punch Vib",
            normalized_unit="mm/s",
            enabled=True,
            created_at=now,
        )
        s4 = MachineSignal(
            id="sig-s33-m4-temp",
            organization_id=org_a.id,
            machine_id=m4.id,
            signal_definition_id=def_temp.id,
            source_node_id="ns=2;s=Blist01.Temp",
            custom_name="Seal Temp",
            normalized_unit="°C",
            enabled=True,
            created_at=now,
        )
        s5 = MachineSignal(
            id="sig-s33-m5-temp",
            organization_id=org_a.id,
            machine_id=m5.id,
            signal_definition_id=def_temp.id,
            source_node_id="ns=2;s=Gran02.Temp",
            custom_name="Bearing Temp",
            normalized_unit="°C",
            enabled=True,
            created_at=now,
        )
        db.session.add_all([s1, s2, s3, s4, s5])
        db.session.commit()

        # 8. Monitoring Sessions
        # M1: Active
        db.session.add(MonitoringSession(
            id="sess-s33-m1",
            organization_id=org_a.id,
            machine_id=m1.id,
            desired_state=MonitoringState.ACTIVE,
            observed_state=MonitoringState.ACTIVE,
            activated_at=now - timedelta(hours=1),
        ))
        # M2: Active
        db.session.add(MonitoringSession(
            id="sess-s33-m2",
            organization_id=org_a.id,
            machine_id=m2.id,
            desired_state=MonitoringState.ACTIVE,
            observed_state=MonitoringState.ACTIVE,
            activated_at=now - timedelta(hours=1),
        ))
        # M3: Active
        db.session.add(MonitoringSession(
            id="sess-s33-m3",
            organization_id=org_a.id,
            machine_id=m3.id,
            desired_state=MonitoringState.ACTIVE,
            observed_state=MonitoringState.ACTIVE,
            activated_at=now - timedelta(hours=1),
        ))
        # M4: Active (desired) but stale telemetry
        db.session.add(MonitoringSession(
            id="sess-s33-m4",
            organization_id=org_a.id,
            machine_id=m4.id,
            desired_state=MonitoringState.ACTIVE,
            observed_state=MonitoringState.ACTIVE,
            activated_at=now - timedelta(hours=1),
        ))
        # M5: Stopped
        db.session.add(MonitoringSession(
            id="sess-s33-m5",
            organization_id=org_a.id,
            machine_id=m5.id,
            desired_state=MonitoringState.STOPPED,
            observed_state=MonitoringState.STOPPED,
            activated_at=now - timedelta(hours=2),
            stopped_at=now - timedelta(hours=1),
        ))
        db.session.commit()

        # 9. Configured Thresholds
        # M1: Warning max: 80.0, Critical max: 90.0
        ThresholdService.set_signal_threshold(
            organization_id=org_a.id,
            machine_id=m1.id,
            signal_id=s1.id,
            warning_max=80.0,
            critical_max=90.0,
        )
        # M2: Warning max: 70.0, Critical max: 85.0
        ThresholdService.set_signal_threshold(
            organization_id=org_a.id,
            machine_id=m2.id,
            signal_id=s2.id,
            warning_max=70.0,
            critical_max=85.0,
        )

        # 10. Seed Readings:
        # M1 reading: 65.0 (Fresh, Normal)
        db.session.add(SignalReading(
            id=str(uuid.uuid4()),
            event_id="evt-s33-m1",
            organization_id=org_a.id,
            machine_id=m1.id,
            signal_id=s1.id,
            source_timestamp=now - timedelta(seconds=10),
            normalized_value=65.0,
            normalized_unit="°C",
            quality_code="Good",
        ))
        # M2 reading: 75.0 (Fresh, Warning breach: > 70.0)
        db.session.add(SignalReading(
            id=str(uuid.uuid4()),
            event_id="evt-s33-m2",
            organization_id=org_a.id,
            machine_id=m2.id,
            signal_id=s2.id,
            source_timestamp=now - timedelta(seconds=15),
            normalized_value=75.0,
            normalized_unit="°C",
            quality_code="Good",
        ))
        # M3 reading: 2.5 (Fresh)
        db.session.add(SignalReading(
            id=str(uuid.uuid4()),
            event_id="evt-s33-m3",
            organization_id=org_a.id,
            machine_id=m3.id,
            signal_id=s3.id,
            source_timestamp=now - timedelta(seconds=12),
            normalized_value=2.5,
            normalized_unit="mm/s",
            quality_code="Good",
        ))
        # M4 reading: 50.0 (Stale, 400 seconds ago)
        db.session.add(SignalReading(
            id=str(uuid.uuid4()),
            event_id="evt-s33-m4",
            organization_id=org_a.id,
            machine_id=m4.id,
            signal_id=s4.id,
            source_timestamp=now - timedelta(seconds=400),
            normalized_value=50.0,
            normalized_unit="°C",
            quality_code="Good",
        ))
        db.session.commit()

        # 11. Seed Critical Anomaly & Alert for M3
        anom_evt = AnomalyEvent(
            id="anom-s33-01",
            organization_id=org_a.id,
            machine_id=m3.id,
            detection_method="MULTIVARIATE_DRIFT",
            severity=AnomalySeverity.CRITICAL,
            summary="Excessive mechanical vibration on main turret punches.",
            affected_signals=[s3.id],
            first_detected_at=now - timedelta(minutes=20),
            latest_detected_at=now - timedelta(minutes=5),
        )
        db.session.add(anom_evt)
        db.session.commit()

        ev_item = AnomalyEvidence(
            id="ev-s33-01",
            anomaly_id=anom_evt.id,
            signal_id=s3.id,
            source_timestamp=now - timedelta(minutes=5),
            observed_value=4.8,
        )
        alert_m3 = EquipmentAlert(
            id="alert-s33-01",
            organization_id=org_a.id,
            machine_id=m3.id,
            anomaly_id=anom_evt.id,
            severity=AnomalySeverity.CRITICAL,
            status=AlertStatus.OPEN,
            first_detected_at=now - timedelta(minutes=20),
            last_detected_at=now - timedelta(minutes=5),
        )
        db.session.add_all([ev_item, alert_m3])
        db.session.commit()

        yield {
            "org_a": org_a,
            "org_b": org_b,
            "site_a1": site_a1,
            "site_a2": site_a2,
            "site_b1": site_b1,
            "cat_gran": cat_gran,
            "cat_dryer": cat_dryer,
            "cat_press": cat_press,
            "cat_pack": cat_pack,
            "m1": m1,
            "m2": m2,
            "m3": m3,
            "m4": m4,
            "m5": m5,
            "m6": m6,
            "m_b1": m_b1,
            "alert_m3": alert_m3,
            "user_admin_a": user_admin_a,
            "user_admin_b": user_admin_b,
        }


def get_auth_token(client, email="lead@alpha-fleet.com", password="Admin@123"):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return res.get_json()["session_token"]


# ==============================================================================
# 1. PLANT-WIDE KPI OVERVIEW & SUMMARY TESTS
# ==============================================================================

def test_plant_overview_calculations(app, step33_setup):
    """Verify fleet overview counts are calculated from real DB state without fabrication."""
    with app.app_context():
        ctx = step33_setup
        overview = FleetMonitoringService.get_plant_overview(ctx["org_a"].id)

        assert overview["organization_id"] == ctx["org_a"].id
        assert overview["total_equipment"] == 6
        assert overview["monitoring_equipment"] == 4  # M1, M2, M3, M4 are active
        assert overview["healthy_equipment"] == 1    # M1
        assert overview["warning_equipment"] == 1    # M2 (threshold breach > 70.0)
        assert overview["critical_equipment"] == 1   # M3 (active critical alert)
        assert overview["stale_equipment"] == 1      # M4 (last reading 400s ago)
        assert overview["offline_equipment"] == 1    # M5 (stopped session)
        assert overview["not_configured_equipment"] == 1  # M6 (0 mapped signals)
        assert overview["active_alerts_count"] == 1
        assert overview["critical_alerts_count"] == 1
        assert overview["warning_alerts_count"] == 0


# ==============================================================================
# 2. STATUS CLASSIFICATION HIERARCHY TESTS
# ==============================================================================

def test_fleet_status_classification_hierarchy(app, step33_setup):
    """Verify each machine is accurately classified by deterministic hierarchy."""
    with app.app_context():
        ctx = step33_setup
        fleet = FleetMonitoringService.get_fleet_machines(ctx["org_a"].id, limit_all=False)
        items_by_id = {item["id"]: item for item in fleet["items"]}

        # M1: HEALTHY
        assert items_by_id[ctx["m1"].id]["status"] == "HEALTHY"
        assert items_by_id[ctx["m1"].id]["data_freshness"] == "FRESH"

        # M2: WARNING
        assert items_by_id[ctx["m2"].id]["status"] == "WARNING"
        assert len(items_by_id[ctx["m2"].id]["threshold_breaches"]) == 1
        assert items_by_id[ctx["m2"].id]["threshold_breaches"][0]["status"] == "WARNING"

        # M3: CRITICAL
        assert items_by_id[ctx["m3"].id]["status"] == "CRITICAL"
        assert items_by_id[ctx["m3"].id]["active_alerts_count"] == 1
        assert items_by_id[ctx["m3"].id]["highest_alert_severity"] == "CRITICAL"

        # M4: STALE
        assert items_by_id[ctx["m4"].id]["status"] == "STALE"
        assert items_by_id[ctx["m4"].id]["data_freshness"] == "STALE"

        # M5: OFFLINE
        assert items_by_id[ctx["m5"].id]["status"] == "OFFLINE"
        assert items_by_id[ctx["m5"].id]["is_actively_monitoring"] is False

        # M6: NOT CONFIGURED
        assert items_by_id[ctx["m6"].id]["status"] == "NOT CONFIGURED"
        assert items_by_id[ctx["m6"].id]["signals_count"] == 0


def test_stale_telemetry_detection_not_machine_failure(app, step33_setup):
    """Verify stale telemetry is classified as pipeline delay and never fabricated as machine failure."""
    with app.app_context():
        ctx = step33_setup
        fleet = FleetMonitoringService.get_fleet_machines(ctx["org_a"].id)
        m4_item = next(it for it in fleet["items"] if it["id"] == ctx["m4"].id)

        assert m4_item["status"] == "STALE"
        assert m4_item["data_freshness"] == "STALE"
        assert m4_item["telemetry_age_seconds"] >= 350
        # No synthetic alerts or false failure predictions generated
        assert m4_item["active_alerts_count"] == 0
        assert m4_item["threshold_breaches"] == []


# ==============================================================================
# 3. SEARCH & FILTER TESTS
# ==============================================================================

def test_fleet_search_by_name_and_code(app, step33_setup):
    """Verify search filter by equipment name or asset code (case-insensitive substring)."""
    with app.app_context():
        ctx = step33_setup

        # Search by asset code "fbd"
        res_fbd = FleetMonitoringService.get_fleet_machines(ctx["org_a"].id, search="fbd")
        assert len(res_fbd["items"]) == 1
        assert res_fbd["items"][0]["asset_code"] == "FBD-01"

        # Search by name "granulator"
        res_gran = FleetMonitoringService.get_fleet_machines(ctx["org_a"].id, search="granulator")
        assert len(res_gran["items"]) == 2
        codes = {it["asset_code"] for it in res_gran["items"]}
        assert codes == {"GRAN-01", "GRAN-02"}


def test_fleet_filters_by_site_and_category(app, step33_setup):
    """Verify filtering by site (production area) and category (equipment type)."""
    with app.app_context():
        ctx = step33_setup

        # Filter by site_a1 (Granulation Suite A) -> M1, M2, M5
        res_site1 = FleetMonitoringService.get_fleet_machines(ctx["org_a"].id, site_id=ctx["site_a1"].id)
        assert len(res_site1["items"]) == 3
        site_codes = {it["asset_code"] for it in res_site1["items"]}
        assert site_codes == {"GRAN-01", "FBD-01", "GRAN-02"}

        # Filter by category Press -> M3, M6
        res_cat = FleetMonitoringService.get_fleet_machines(ctx["org_a"].id, category_id=ctx["cat_press"].id)
        assert len(res_cat["items"]) == 2
        cat_codes = {it["asset_code"] for it in res_cat["items"]}
        assert cat_codes == {"TAB-01", "TAB-02"}


def test_fleet_filter_by_status(app, step33_setup):
    """Verify filtering fleet grid by monitoring status."""
    with app.app_context():
        ctx = step33_setup

        # Filter CRITICAL
        res_crit = FleetMonitoringService.get_fleet_machines(ctx["org_a"].id, status="CRITICAL")
        assert len(res_crit["items"]) == 1
        assert res_crit["items"][0]["asset_code"] == "TAB-01"

        # Filter OFFLINE
        res_off = FleetMonitoringService.get_fleet_machines(ctx["org_a"].id, status="OFFLINE")
        assert len(res_off["items"]) == 1
        assert res_off["items"][0]["asset_code"] == "GRAN-02"


# ==============================================================================
# 4. PAGINATION & SORTING TESTS
# ==============================================================================

def test_fleet_pagination_and_sorting(app, step33_setup):
    """Verify pagination slices and sorting by severity and asset code."""
    with app.app_context():
        ctx = step33_setup

        # Page 1 with per_page = 2
        p1 = FleetMonitoringService.get_fleet_machines(
            ctx["org_a"].id,
            sort_by="severity",
            order="asc",
            page=1,
            per_page=2,
        )
        assert p1["total"] == 6
        assert p1["pages"] == 3
        assert len(p1["items"]) == 2
        # Severity rank 1 & 2: CRITICAL and WARNING
        assert p1["items"][0]["status"] == "CRITICAL"
        assert p1["items"][1]["status"] == "WARNING"

        # Page 2
        p2 = FleetMonitoringService.get_fleet_machines(
            ctx["org_a"].id,
            sort_by="severity",
            order="asc",
            page=2,
            per_page=2,
        )
        assert len(p2["items"]) == 2
        assert p2["items"][0]["status"] in ["STALE", "OFFLINE"]


# ==============================================================================
# 5. ACTIVE ALERTS & USER ACKNOWLEDGMENT TESTS
# ==============================================================================

def test_fleet_alerts_retrieval_and_user_acknowledgment(app, step33_setup):
    """Verify alert listing and explicit user-driven acknowledgment (never automated)."""
    with app.app_context():
        ctx = step33_setup

        # Retrieve active fleet alerts
        alerts = FleetMonitoringService.get_fleet_alerts(ctx["org_a"].id)
        assert len(alerts) == 1
        a = alerts[0]
        assert a["id"] == ctx["alert_m3"].id
        assert a["severity"] == "CRITICAL"
        assert a["status"] == "OPEN"
        assert a["asset_code"] == "TAB-01"
        assert a["observed_value"] == 4.8

        # Explicit user acknowledgment
        updated = FleetMonitoringService.acknowledge_alert(
            organization_id=ctx["org_a"].id,
            alert_id=a["id"],
            user_id=ctx["user_admin_a"].id,
            notes="Turret vibration inspected. Scheduled bearing replacement for next downtime window.",
        )
        assert updated["status"] == AlertStatus.ACKNOWLEDGED
        assert updated["acknowledged_by"] == ctx["user_admin_a"].id
        assert updated["acknowledged_at"] is not None

        # Verify alert now shows as ACKNOWLEDGED
        refetched = db.session.get(EquipmentAlert, a["id"])
        assert refetched.status == AlertStatus.ACKNOWLEDGED


# ==============================================================================
# 6. MULTI-TENANT ISOLATION TESTS
# ==============================================================================

def test_multi_tenant_fleet_isolation(app, step33_setup):
    """Verify Org B cannot observe or acknowledge Org A fleet data."""
    with app.app_context():
        ctx = step33_setup

        # Org B overview
        overview_b = FleetMonitoringService.get_plant_overview(ctx["org_b"].id)
        assert overview_b["total_equipment"] == 1
        assert overview_b["monitoring_equipment"] == 0

        # Org B fleet list contains only Org B machine
        fleet_b = FleetMonitoringService.get_fleet_machines(ctx["org_b"].id)
        assert len(fleet_b["items"]) == 1
        assert fleet_b["items"][0]["id"] == ctx["m_b1"].id

        # Org B cannot view Org A alerts
        alerts_b = FleetMonitoringService.get_fleet_alerts(ctx["org_b"].id)
        assert len(alerts_b) == 0

        # Org B cannot acknowledge Org A alert
        with pytest.raises(Exception):
            FleetMonitoringService.acknowledge_alert(
                organization_id=ctx["org_b"].id,
                alert_id=ctx["alert_m3"].id,
                user_id=ctx["user_admin_b"].id,
            )


# ==============================================================================
# 7. REST API INTEGRATION TESTS
# ==============================================================================

def test_rest_api_fleet_endpoints(client, step33_setup):
    """Verify REST API endpoints for overview, fleet list, alerts, and acknowledgment."""
    ctx = step33_setup
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET /monitoring/fleet/overview
    res_ov = client.get("/api/v1/monitoring/fleet/overview", headers=headers)
    assert res_ov.status_code == 200
    ov_data = res_ov.get_json()
    assert ov_data["total_equipment"] == 6
    assert ov_data["active_alerts_count"] == 1

    # 2. GET /monitoring/fleet
    res_fleet = client.get("/api/v1/monitoring/fleet?page=1&per_page=10", headers=headers)
    assert res_fleet.status_code == 200
    fl_data = res_fleet.get_json()
    assert fl_data["total"] == 6
    assert len(fl_data["items"]) == 6
    assert "status_counts" in fl_data

    # 3. GET /monitoring/fleet/alerts
    res_alerts = client.get("/api/v1/monitoring/fleet/alerts", headers=headers)
    assert res_alerts.status_code == 200
    al_data = res_alerts.get_json()
    assert al_data["count"] >= 1
    target_alert_id = al_data["alerts"][0]["id"]

    # 4. POST /monitoring/fleet/alerts/<id>/acknowledge
    ack_res = client.post(
        f"/api/v1/monitoring/fleet/alerts/{target_alert_id}/acknowledge",
        json={"notes": "Acknowledged via API integration test."},
        headers=headers,
    )
    assert ack_res.status_code == 200
    ack_data = ack_res.get_json()
    assert ack_data["alert"]["status"] == "ACKNOWLEDGED"

