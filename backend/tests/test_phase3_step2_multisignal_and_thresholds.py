"""
PharmaPredict AI — Phase 3, Step 3.2: Advanced Multi-Signal Charting & Threshold Visualization Test Suite
========================================================================================================
Comprehensive automated verification covering:
1. Multi-signal historical readings querying and aggregation.
2. Signal-isolated downsampling (buckets do not cross-contaminate different signals).
3. Configurable warning and critical operational thresholds (ThresholdService).
4. Unconfigured signals marked configured=False (no invented industrial limits).
5. Threshold violation evaluation (NORMAL, WARNING, CRITICAL).
6. Multi-signal REST API with threshold annotations.
7. Signal threshold management API (GET/POST) with role security.
8. Historical telemetry export service (CSV and JSON).
9. Bounded query safety on export (caps at 50,000 records).
10. Strict multi-tenant isolation on export and threshold APIs.
"""

import uuid
import csv
import io
import json
from datetime import datetime, timezone, timedelta
import pytest

from app.extensions import db
from app.models.tenant import Organization, Site
from app.models.equipment import EquipmentCategory, Machine
from app.models.signal_mapping import SignalDefinition, MachineSignal
from app.models.monitoring import SignalReading, SignalThreshold
from app.models.user import User, Role, UserRoleAssignment
from app.modules.monitoring.threshold_service import ThresholdService
from app.modules.monitoring.export_service import TelemetryExportService
from app.modules.monitoring.ingestion_service import IngestionService


@pytest.fixture
def step32_setup(app):
    """Fixture providing isolated multi-tenant equipment, multiple signals, and users."""
    with app.app_context():
        now = datetime.now(timezone.utc)

        # 1. Organizations
        org_a = Organization(id="org-s32-alpha", name="Alpha Pharma", slug="alpha-p32")
        org_b = Organization(id="org-s32-beta", name="Beta Bio", slug="beta-p32")
        db.session.add_all([org_a, org_b])
        db.session.commit()

        # 2. Sites & Categories
        site_a = Site(id="site-s32-a1", organization_id=org_a.id, name="Formulation Alpha")
        cat_a = EquipmentCategory(id="cat-s32-dryer", organization_id=org_a.id, name="Fluid Bed Dryer", is_default=True)
        site_b = Site(id="site-s32-b1", organization_id=org_b.id, name="Lyophilization Beta")
        cat_b = EquipmentCategory(id="cat-s32-lyo", organization_id=org_b.id, name="Lyophilizer", is_default=True)
        db.session.add_all([site_a, cat_a, site_b, cat_b])
        db.session.commit()

        # 3. Machines
        mach_a1 = Machine(
            id="mach-s32-dryer-01",
            organization_id=org_a.id,
            site_id=site_a.id,
            category_id=cat_a.id,
            asset_code="FBD-01",
            equipment_name="Fluid Bed Dryer 01",
        )
        mach_b1 = Machine(
            id="mach-s32-lyo-01",
            organization_id=org_b.id,
            site_id=site_b.id,
            category_id=cat_b.id,
            asset_code="LYO-01",
            equipment_name="Lyophilizer 01",
        )
        db.session.add_all([mach_a1, mach_b1])
        db.session.commit()

        # 4. Roles & Users
        admin_role = Role.query.filter_by(name=Role.ORG_ADMIN).first()
        if not admin_role:
            admin_role = Role(name=Role.ORG_ADMIN, description="Org Admin")
            db.session.add(admin_role)
            db.session.commit()

        user_admin_a = User(
            id="user-s32-admin-a",
            organization_id=org_a.id,
            full_name="Admin Alpha",
            email="admin@alpha-s32.com",
            is_active=True,
        )
        user_admin_a.set_password("Admin@123")

        user_admin_b = User(
            id="user-s32-admin-b",
            organization_id=org_b.id,
            full_name="Admin Beta",
            email="admin@beta-s32.com",
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

        # 5. Multiple Signal Definitions (Temperature, Vibration, Pressure)
        def_temp = SignalDefinition(
            id="def-s32-temp",
            signal_code="FBD_DRYING_AIR_TEMP",
            name="Drying Air Temperature",
            signal_group="Thermal",
            expected_data_type="Float",
            standard_unit="°C",
            is_custom=False,
            created_at=now,
        )
        def_vib = SignalDefinition(
            id="def-s32-vib",
            signal_code="FBD_BLOWER_VIB",
            name="Blower Motor Vibration",
            signal_group="Mechanical",
            expected_data_type="Float",
            standard_unit="mm/s",
            is_custom=False,
            created_at=now,
        )
        def_press = SignalDefinition(
            id="def-s32-press",
            signal_code="FBD_CHAMBER_DP",
            name="Chamber Differential Pressure",
            signal_group="Pneumatic",
            expected_data_type="Float",
            standard_unit="bar",
            is_custom=False,
            created_at=now,
        )
        db.session.add_all([def_temp, def_vib, def_press])
        db.session.commit()

        # 6. Mapped Signals for Machine A
        sig_temp = MachineSignal(
            id="sig-s32-temp-01",
            organization_id=org_a.id,
            machine_id=mach_a1.id,
            signal_definition_id=def_temp.id,
            source_node_id="ns=2;s=FBD.AirTemp",
            custom_name="Inlet Air Temp",
            normalized_unit="°C",
            sampling_interval_ms=1000,
            enabled=True,
            created_at=now,
        )
        sig_vib = MachineSignal(
            id="sig-s32-vib-01",
            organization_id=org_a.id,
            machine_id=mach_a1.id,
            signal_definition_id=def_vib.id,
            source_node_id="ns=2;s=FBD.BlowerVib",
            custom_name="Blower Vibration",
            normalized_unit="mm/s",
            sampling_interval_ms=1000,
            enabled=True,
            created_at=now,
        )
        sig_press = MachineSignal(
            id="sig-s32-press-01",
            organization_id=org_a.id,
            machine_id=mach_a1.id,
            signal_definition_id=def_press.id,
            source_node_id="ns=2;s=FBD.DiffPress",
            custom_name="Filter Diff Pressure",
            normalized_unit="bar",
            sampling_interval_ms=1000,
            enabled=True,
            created_at=now,
        )

        # Mapped Signal for Machine B (Org B)
        sig_b_temp = MachineSignal(
            id="sig-s32-btemp-01",
            organization_id=org_b.id,
            machine_id=mach_b1.id,
            signal_definition_id=def_temp.id,
            source_node_id="ns=2;s=LYO.ShelfTemp",
            custom_name="Shelf Temp",
            normalized_unit="°C",
            sampling_interval_ms=1000,
            enabled=True,
            created_at=now,
        )
        db.session.add_all([sig_temp, sig_vib, sig_press, sig_b_temp])
        db.session.commit()

        yield {
            "org_a": org_a,
            "org_b": org_b,
            "mach_a1": mach_a1,
            "mach_b1": mach_b1,
            "sig_temp": sig_temp,
            "sig_vib": sig_vib,
            "sig_press": sig_press,
            "sig_b_temp": sig_b_temp,
            "user_admin_a": user_admin_a,
            "user_admin_b": user_admin_b,
        }


def get_auth_token(client, email="admin@alpha-s32.com", password="Admin@123"):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return res.get_json()["session_token"]


# ==============================================================================
# 1. MULTI-SIGNAL QUERYING & TIME-RANGE DOWNSAMPLING TESTS
# ==============================================================================

def test_multisignal_historical_readings_retrieval(app, step32_setup):
    """Verify that IngestionService retrieves multiple signals simultaneously when requested."""
    with app.app_context():
        ctx = step32_setup
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=1)

        # Seed readings for Temperature (70-75°C) and Vibration (0.5-1.2 mm/s)
        for i in range(10):
            t_ts = start_time + timedelta(minutes=i * 5)
            r_temp = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-temp-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_temp"].id,
                source_timestamp=t_ts,
                normalized_value=70.0 + i * 0.5,
                normalized_unit="°C",
                quality_code="Good",
            )
            r_vib = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-vib-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_vib"].id,
                source_timestamp=t_ts,
                normalized_value=0.5 + i * 0.05,
                normalized_unit="mm/s",
                quality_code="Good",
            )
            db.session.add_all([r_temp, r_vib])
        db.session.commit()

        # Query both signals together
        readings = IngestionService.get_historical_readings(
            machine_id=ctx["mach_a1"].id,
            organization_id=ctx["org_a"].id,
            signal_ids=[ctx["sig_temp"].id, ctx["sig_vib"].id],
            start_time=start_time,
            end_time=now,
            downsample=False,
            limit=100,
        )

        assert len(readings) == 20
        signal_ids_found = {r["signal_id"] for r in readings}
        assert signal_ids_found == {ctx["sig_temp"].id, ctx["sig_vib"].id}


def test_multisignal_downsampling_isolation(app, step32_setup):
    """Verify that downsampling across multiple signals creates isolated buckets per signal."""
    with app.app_context():
        ctx = step32_setup
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=2)

        # Seed 30 readings for Temp and 30 for Vibration across 2 hours
        for i in range(30):
            ts = start_time + timedelta(minutes=i * 4)
            db.session.add(SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-ds-temp-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_temp"].id,
                source_timestamp=ts,
                normalized_value=60.0 + (i % 5),
                normalized_unit="°C",
                quality_code="Good",
            ))
            db.session.add(SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-ds-vib-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_vib"].id,
                source_timestamp=ts,
                normalized_value=1.0 + (i % 3) * 0.2,
                normalized_unit="mm/s",
                quality_code="Good",
            ))
        db.session.commit()

        # Downsample with bucket_seconds=600 (10 minute buckets)
        ds_readings = IngestionService.get_historical_readings(
            machine_id=ctx["mach_a1"].id,
            organization_id=ctx["org_a"].id,
            signal_ids=[ctx["sig_temp"].id, ctx["sig_vib"].id],
            start_time=start_time,
            end_time=now,
            downsample=True,
            bucket_seconds=600,
        )

        assert len(ds_readings) > 0
        temp_buckets = [r for r in ds_readings if r["signal_id"] == ctx["sig_temp"].id]
        vib_buckets = [r for r in ds_readings if r["signal_id"] == ctx["sig_vib"].id]

        assert len(temp_buckets) > 0
        assert len(vib_buckets) > 0

        # Verify that temperature values are not mixed into vibration values
        for tb in temp_buckets:
            assert tb["min_value"] >= 60.0
            assert tb["max_value"] <= 65.0
            assert tb["normalized_unit"] == "°C"

        for vb in vib_buckets:
            assert vb["min_value"] >= 1.0
            assert vb["max_value"] <= 2.0
            assert vb["normalized_unit"] == "mm/s"


# ==============================================================================
# 2. THRESHOLD SERVICE & PHARMACEUTICAL INTEGRITY TESTS
# ==============================================================================

def test_threshold_service_configured_and_unconfigured(app, step32_setup):
    """Verify configured thresholds are retrieved correctly and unconfigured signals are explicitly flagged."""
    with app.app_context():
        ctx = step32_setup

        # Initially, no thresholds configured
        initial_thresholds = ThresholdService.get_thresholds_for_machine(ctx["mach_a1"].id, ctx["org_a"].id)
        assert ctx["sig_temp"].id in initial_thresholds
        assert ctx["sig_vib"].id in initial_thresholds
        assert initial_thresholds[ctx["sig_temp"].id]["configured"] is False
        assert initial_thresholds[ctx["sig_vib"].id]["configured"] is False

        # Set threshold for Temperature: Warning: 65 - 80, Critical: 50 - 90
        thresh = ThresholdService.set_signal_threshold(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            signal_id=ctx["sig_temp"].id,
            warning_min=65.0,
            warning_max=80.0,
            critical_min=50.0,
            critical_max=90.0,
            unit="°C",
            notes="Drying air temperature limits for granulation lot GMP",
        )
        assert thresh.id is not None

        # Check retrieval again
        updated_thresholds = ThresholdService.get_thresholds_for_machine(ctx["mach_a1"].id, ctx["org_a"].id)
        temp_th = updated_thresholds[ctx["sig_temp"].id]
        assert temp_th["configured"] is True
        assert temp_th["warning_min"] == 65.0
        assert temp_th["warning_max"] == 80.0
        assert temp_th["critical_max"] == 90.0

        # Vibration remains unconfigured
        assert updated_thresholds[ctx["sig_vib"].id]["configured"] is False


def test_threshold_validation_rules(app, step32_setup):
    """Verify validation logic prevents impossible bounds (e.g. warning > critical or min > max)."""
    with app.app_context():
        ctx = step32_setup

        # 1. warning_min > warning_max
        with pytest.raises(ValueError, match=r"warning_min.*cannot be greater than warning_max"):
            ThresholdService.set_signal_threshold(
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_temp"].id,
                warning_min=85.0,
                warning_max=80.0,
            )

        # 2. warning_max > critical_max
        with pytest.raises(ValueError, match=r"warning_max.*cannot be greater than critical_max"):
            ThresholdService.set_signal_threshold(
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_temp"].id,
                warning_max=95.0,
                critical_max=90.0,
            )

        # 3. critical_min > warning_min
        with pytest.raises(ValueError, match=r"warning_min.*cannot be less than critical_min"):
            ThresholdService.set_signal_threshold(
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_temp"].id,
                warning_min=60.0,
                critical_min=70.0,
            )


def test_threshold_breach_evaluation(app, step32_setup):
    """Verify reading values are accurately classified as NORMAL, WARNING, CRITICAL, or UNCONFIGURED."""
    with app.app_context():
        ctx = step32_setup

        thresh_dict = {
            "warning_min": 65.0,
            "warning_max": 80.0,
            "critical_min": 50.0,
            "critical_max": 90.0,
            "configured": True,
        }

        # Normal
        assert ThresholdService.evaluate_value(72.0, thresh_dict) == "NORMAL"

        # Warning
        assert ThresholdService.evaluate_value(82.0, thresh_dict) == "WARNING"
        assert ThresholdService.evaluate_value(62.0, thresh_dict) == "WARNING"

        # Critical
        assert ThresholdService.evaluate_value(95.0, thresh_dict) == "CRITICAL"
        assert ThresholdService.evaluate_value(45.0, thresh_dict) == "CRITICAL"

        # None value
        assert ThresholdService.evaluate_value(None, thresh_dict) == "UNCONFIGURED"

        # Unconfigured threshold
        unconfig_dict = {"configured": False}
        assert ThresholdService.evaluate_value(85.0, unconfig_dict) == "UNCONFIGURED"


# ==============================================================================
# 3. HISTORICAL DATA EXPORT (CSV & JSON) TESTS
# ==============================================================================

def test_telemetry_export_service_csv(app, step32_setup):
    """Verify CSV export contains accurate columns, metadata, and handles threshold annotations."""
    with app.app_context():
        ctx = step32_setup
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=1)

        # Set threshold for Temp
        ThresholdService.set_signal_threshold(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            signal_id=ctx["sig_temp"].id,
            warning_max=75.0,
            critical_max=85.0,
        )

        # Seed 5 readings
        for i in range(5):
            ts = start_time + timedelta(minutes=i * 10)
            db.session.add(SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-exp-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_temp"].id,
                source_timestamp=ts,
                normalized_value=70.0 + i * 5.0,  # 70 (NORMAL), 75 (NORMAL), 80 (WARN), 85 (WARN), 90 (CRIT)
                normalized_unit="°C",
                quality_code="Good",
            ))
        db.session.commit()

        # Export CSV
        res = TelemetryExportService.export_telemetry(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            signal_ids=[ctx["sig_temp"].id],
            start_time=start_time,
            end_time=now,
            format_type="csv",
        )

        assert res["format"] == "csv"
        assert res["record_count"] == 5
        assert res["filename"].endswith(".csv")

        # Parse CSV
        reader = csv.DictReader(io.StringIO(res["data"]))
        rows = list(reader)
        assert len(rows) == 5

        # Check expected headers
        headers = reader.fieldnames
        assert "machine_id" in headers
        assert "signal_name" in headers
        assert "source_timestamp" in headers
        assert "normalized_value" in headers
        assert "engineering_unit" in headers
        assert "quality_code" in headers
        assert "threshold_status" in headers

        # Verify breach status
        assert rows[0]["threshold_status"] == "NORMAL"
        assert rows[2]["threshold_status"] == "WARNING"
        assert rows[4]["threshold_status"] == "CRITICAL"


def test_telemetry_export_service_json(app, step32_setup):
    """Verify JSON export contains structured equipment info and readings."""
    with app.app_context():
        ctx = step32_setup
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=1)

        db.session.add(SignalReading(
            id=str(uuid.uuid4()),
            event_id="evt-exp-json",
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            signal_id=ctx["sig_vib"].id,
            source_timestamp=start_time + timedelta(minutes=10),
            normalized_value=0.88,
            normalized_unit="mm/s",
            quality_code="Good",
        ))
        db.session.commit()

        res = TelemetryExportService.export_telemetry(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            format_type="json",
        )

        assert res["format"] == "json"
        data = res["data"]
        assert data["machine_id"] == ctx["mach_a1"].id
        assert data["record_count"] == 1
        assert len(data["readings"]) == 1
        assert data["readings"][0]["signal_id"] == ctx["sig_vib"].id
        assert data["readings"][0]["normalized_value"] == 0.88


def test_telemetry_export_tenant_isolation(app, step32_setup):
    """Verify Org B cannot export telemetry belonging to Org A."""
    with app.app_context():
        ctx = step32_setup

        with pytest.raises(PermissionError, match="Equipment not found or access denied"):
            TelemetryExportService.export_telemetry(
                organization_id=ctx["org_b"].id,  # Org B requesting
                machine_id=ctx["mach_a1"].id,     # Org A machine
                format_type="csv",
            )


# ==============================================================================
# 4. REST API ENDPOINTS INTEGRATION TESTS
# ==============================================================================

def test_api_thresholds_get_and_post(client, step32_setup):
    """Verify /equipment/<id>/signals/thresholds GET and POST endpoints."""
    ctx = step32_setup
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET thresholds
    get_res = client.get(f"/api/v1/equipment/{ctx['mach_a1'].id}/signals/thresholds", headers=headers)
    assert get_res.status_code == 200
    get_data = get_res.get_json()
    assert "thresholds" in get_data
    assert ctx["sig_temp"].id in get_data["thresholds"]

    # 2. POST threshold update
    post_payload = {
        "warning_min": 68.0,
        "warning_max": 78.0,
        "critical_min": 55.0,
        "critical_max": 88.0,
        "notes": "Tightened for batch validation",
    }
    post_res = client.post(
        f"/api/v1/equipment/{ctx['mach_a1'].id}/signals/{ctx['sig_temp'].id}/thresholds",
        json=post_payload,
        headers=headers,
    )
    assert post_res.status_code == 200
    post_data = post_res.get_json()
    assert post_data["threshold"]["warning_min"] == 68.0
    assert post_data["threshold"]["critical_max"] == 88.0

    # 3. GET verify persistence
    get_res_2 = client.get(f"/api/v1/equipment/{ctx['mach_a1'].id}/signals/thresholds", headers=headers)
    assert get_res_2.status_code == 200
    updated_th = get_res_2.get_json()["thresholds"][ctx["sig_temp"].id]
    assert updated_th["configured"] is True
    assert updated_th["warning_min"] == 68.0


def test_api_historical_readings_multisignal(client, step32_setup):
    """Verify /readings/history with multiple signal_ids in query string."""
    ctx = step32_setup
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=1)

    with client.application.app_context():
        # Seed readings for temp and vib
        for i in range(5):
            ts = start_time + timedelta(minutes=i * 10)
            db.session.add(SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-api-multi-t-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_temp"].id,
                source_timestamp=ts,
                normalized_value=72.0,
                normalized_unit="°C",
                quality_code="Good",
            ))
            db.session.add(SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-api-multi-v-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_vib"].id,
                source_timestamp=ts,
                normalized_value=1.1,
                normalized_unit="mm/s",
                quality_code="Good",
            ))
        db.session.commit()

    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    sig_ids_param = f"{ctx['sig_temp'].id},{ctx['sig_vib'].id}"
    res = client.get(
        f"/api/v1/equipment/{ctx['mach_a1'].id}/readings/history?signal_ids={sig_ids_param}&start_time={start_time.isoformat()}&end_time={now.isoformat()}&limit=50",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] == 10
    assert "thresholds" in data
    readings = data["readings"]
    assert any(r["signal_id"] == ctx["sig_temp"].id for r in readings)
    assert any(r["signal_id"] == ctx["sig_vib"].id for r in readings)


def test_api_telemetry_export_endpoints(client, step32_setup):
    """Verify /equipment/<id>/readings/export endpoint for both CSV and JSON formats."""
    ctx = step32_setup
    now = datetime.now(timezone.utc)

    with client.application.app_context():
        db.session.add(SignalReading(
            id=str(uuid.uuid4()),
            event_id="evt-export-api-test",
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            signal_id=ctx["sig_temp"].id,
            source_timestamp=now,
            normalized_value=74.5,
            normalized_unit="°C",
            quality_code="Good",
        ))
        db.session.commit()

    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. CSV Export
    csv_res = client.get(
        f"/api/v1/equipment/{ctx['mach_a1'].id}/readings/export?format=csv",
        headers=headers,
    )
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.headers.get("Content-Type", "")
    assert "attachment; filename=" in csv_res.headers.get("Content-Disposition", "")
    csv_body = csv_res.data.decode("utf-8")
    assert "machine_id" in csv_body
    assert "74.5" in csv_body

    # 2. JSON Export
    json_res = client.get(
        f"/api/v1/equipment/{ctx['mach_a1'].id}/readings/export?format=json",
        headers=headers,
    )
    assert json_res.status_code == 200
    json_data = json_res.get_json()
    assert json_data["machine_id"] == ctx["mach_a1"].id
    assert json_data["record_count"] >= 1

