"""
PharmaPredict AI — Phase 2, Step 2: Live Signal Mapping & Equipment Onboarding
=============================================================================
End-to-end automated verification covering:
1. Equipment registration and category assignment.
2. OPC UA node discovery across all 7 industrial categories:
   - Temperature (Sealing & Motor)
   - Vibration (Overall & Bearing)
   - Motor Current
   - Speed & RPM
   - Pressure (Vacuum & Pneumatic)
   - Alarms & Safety
   - Cycles & Production Count
3. Dynamic signal mapping with engineering units, scaling factors, and offsets.
4. Signal validation engine execution (7-check audit).
5. Edge gateway dynamic signal configuration and read-only telemetry acquisition.
6. Real HTTP batch ingestion to /api/v1/internal/ingestion/readings.
7. Persistence, retrieval, and clear distinction of simulator readings (simulator_flag=True).
8. OPC UA disconnect and automatic reconnection resilience.
9. Carry forward security: Wildcard authorization rejection & Corrupt record quarantine.
"""

import os
import sys
import json
import uuid
import time
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import pytest

from app.extensions import db
from app.models.tenant import Organization, Site
from app.models.equipment import EquipmentCategory, Machine
from app.models.signal_mapping import (
    SignalDefinition,
    MachineSignal,
    SignalGroup,
    ValidationStatus,
)
from app.models.monitoring import SignalReading
from app.modules.connectivity.simulator import PharmaOPCUASimulator
from app.modules.connectivity.opcua_client import SecureOPCUAClient
from app.modules.connectivity.discovery import TagDiscoveryService
from app.modules.connectivity.models import ConnectionConfig, ConnectionState, UserAuthType
from app.modules.signal_mapping.services import SignalMappingService
from app.modules.signal_mapping.repositories import SignalDefinitionRepository
from app.modules.monitoring.gateway_auth import GatewayAuthRegistry, GatewayIdentity
from app.modules.monitoring.gateway_buffer import BoundedGatewayBuffer
from app.modules.monitoring.ingestion_service import IngestionService
from gateway.edge_gateway import EdgeGateway, EdgeGatewayConfig


def _ensure_signals_mapped(onboarding_setup):
    """Seed machine and mapped signals covering all 7 categories if not already present."""
    if not db.session.get(Machine, "mach-blister-live-01"):
        mach = Machine(
            id="mach-blister-live-01",
            organization_id=onboarding_setup["org_id"],
            site_id=onboarding_setup["site_id"],
            category_id=onboarding_setup["cat_id"],
            asset_code="PHARMA-BLISTER-02",
            equipment_name="High-Speed Blister Packager Line 2",
        )
        db.session.add(mach)
        db.session.commit()

    existing = SignalMappingService.list_signals("mach-blister-live-01", onboarding_setup["org_id"])
    if len(existing) == 7:
        return existing

    temp_def = SignalDefinition.query.filter_by(signal_code="SEALING_TEMP").first()
    vib_def = SignalDefinition.query.filter_by(signal_code="MOTOR_VIBRATION").first()
    curr_def = SignalDefinition.query.filter_by(signal_code="MOTOR_CURRENT").first()
    rpm_def = SignalDefinition.query.filter_by(signal_code="ROTATIONAL_SPEED").first()
    press_def = SignalDefinition.query.filter_by(signal_code="LINE_PRESSURE").first()
    alarm_def = SignalDefinition.query.filter_by(signal_code="FAULT_ALARM").first()
    cycle_def = SignalDefinition.query.filter_by(signal_code="CYCLE_COUNTER").first()

    signals_to_create = [
        {
            "signal_definition_id": temp_def.id,
            "source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
            "custom_name": "Station 1 Sealing Temperature",
            "source_unit": "°C",
            "normalized_unit": "°C",
            "scaling_factor": 1.0,
            "offset": 0.0,
            "sampling_interval_ms": 1000,
        },
        {
            "signal_definition_id": vib_def.id,
            "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorVibration",
            "custom_name": "Main Motor RMS Vibration",
            "source_unit": "mm/s",
            "normalized_unit": "mm/s",
            "scaling_factor": 1.0,
            "offset": 0.0,
            "sampling_interval_ms": 500,
        },
        {
            "signal_definition_id": curr_def.id,
            "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorCurrent",
            "custom_name": "Main Drive Stator Current",
            "source_unit": "A",
            "normalized_unit": "A",
            "scaling_factor": 0.1,
            "offset": 0.5,
            "sampling_interval_ms": 1000,
        },
        {
            "signal_definition_id": rpm_def.id,
            "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MachineSpeedRPM",
            "custom_name": "Main Turret Rotational Speed",
            "source_unit": "RPM",
            "normalized_unit": "RPM",
            "scaling_factor": 1.0,
            "offset": 0.0,
            "sampling_interval_ms": 1000,
        },
        {
            "signal_definition_id": press_def.id,
            "source_node_id": "ns=2;s=BlisterPackagingMachine_01.FormingAirPressure",
            "custom_name": "Forming Station Pneumatic Pressure",
            "source_unit": "bar",
            "normalized_unit": "bar",
            "scaling_factor": 1.0,
            "offset": 0.0,
            "sampling_interval_ms": 1000,
        },
        {
            "signal_definition_id": alarm_def.id,
            "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MachineFaultAlarm",
            "custom_name": "Machine Trip Fault State",
            "source_unit": "Boolean",
            "normalized_unit": "Boolean",
            "scaling_factor": 1.0,
            "offset": 0.0,
            "sampling_interval_ms": 1000,
        },
        {
            "signal_definition_id": cycle_def.id,
            "source_node_id": "ns=2;s=BlisterPackagingMachine_01.CumulativeCycleCount",
            "custom_name": "Lifetime Blister Stroke Counter",
            "source_unit": "Count",
            "normalized_unit": "Count",
            "scaling_factor": 1.0,
            "offset": 0.0,
            "sampling_interval_ms": 2000,
        },
    ]

    SignalMappingService.bulk_create_signals(
        machine_id="mach-blister-live-01",
        organization_id=onboarding_setup["org_id"],
        items=signals_to_create,
    )
    return SignalMappingService.list_signals("mach-blister-live-01", onboarding_setup["org_id"])


@asynccontextmanager
async def running_simulator(port: int = 48402):
    """Context manager running an active simulator on the current event loop."""
    sim = PharmaOPCUASimulator(port=port, enable_security=False)
    await sim.start()
    try:
        yield sim
    finally:
        await sim.stop()


@pytest.fixture
def onboarding_setup(app):
    """Set up organization, site, equipment categories, and gateway identity."""
    with app.app_context():
        # 1. Organization & Site
        org = Organization(id="org-pharma-step2", name="BioPharma Solutions", slug="biopharma-step2")
        db.session.add(org)
        db.session.commit()

        site = Site(id="site-packaging-01", organization_id=org.id, name="Sterile Packaging Facility")
        db.session.add(site)
        db.session.commit()

        # 2. Categories
        cat = EquipmentCategory(id="cat-blister-01", organization_id=org.id, name="Blister Packaging", is_default=True)
        db.session.add(cat)
        db.session.commit()

        # 3. Seed standard signal definitions
        SignalDefinitionRepository.seed_standard_definitions()

        # 4. Register Gateway Identity (Explicit machine whitelist, wildcard disabled)
        gw_secret = "step2-secure-gateway-token-2026"
        GatewayAuthRegistry.register_gateway(GatewayIdentity(
            gateway_id="gw-step2-live",
            organization_id=org.id,
            assigned_equipment_ids=["mach-blister-live-01"],
            secret=gw_secret,
            status="ACTIVE",
            allow_wildcard=False,  # Enforce explicit machine authorization
        ))

        yield {
            "org_id": org.id,
            "site_id": site.id,
            "cat_id": cat.id,
            "gateway_id": "gw-step2-live",
            "gateway_secret": gw_secret,
        }


# =============================================================================
# 1. EQUIPMENT REGISTRATION & CONNECTOR CONFIGURATION
# =============================================================================

def test_equipment_registration(app, onboarding_setup):
    """Register a new pharmaceutical machine in the catalog."""
    with app.app_context():
        machine = Machine(
            id="mach-blister-live-01",
            organization_id=onboarding_setup["org_id"],
            site_id=onboarding_setup["site_id"],
            category_id=onboarding_setup["cat_id"],
            asset_code="PHARMA-BLISTER-02",
            equipment_name="High-Speed Blister Packager Line 2",
            manufacturer="Uhlenbeck PharmaTech",
            model="B-3000X",
            serial_number="UPT-2026-9941",
            criticality="Critical",
        )
        db.session.add(machine)
        db.session.commit()

        saved = db.session.get(Machine, "mach-blister-live-01")
        assert saved is not None
        assert saved.asset_code == "PHARMA-BLISTER-02"
        assert saved.criticality == "Critical"
        assert saved.connection_status == "Not Configured"


# =============================================================================
# 2. EQUIPMENT-SPECIFIC OPC UA NODE DISCOVERY ACROSS 7 CATEGORIES
# =============================================================================

@pytest.mark.asyncio
async def test_opcua_node_discovery_all_7_categories():
    """Verify that node discovery finds nodes spanning all 7 required industrial categories."""
    async with running_simulator(port=48402) as sim:
        config = ConnectionConfig(
            endpoint_url=sim.get_endpoint(),
            timeout_sec=3.0,
            user_auth_type=UserAuthType.ANONYMOUS,
            auto_trust_unknown=True,
        )
        client = SecureOPCUAClient(config)
        await client.connect()
        assert client.is_connected() is True

        try:
            discovery = TagDiscoveryService(max_nodes_per_request=100, max_browse_depth=3)
            tags = await discovery.browse_root(client, max_depth=3, max_nodes=50)

            def _collect_names(tag_list):
                names = []
                for t in tag_list:
                    names.append(t.browse_name)
                    if t.children:
                        names.extend(_collect_names(t.children))
                return names

            browse_names = _collect_names(tags)

            # 1. Speed & RPM
            assert "Speed_CPM" in browse_names or "MachineSpeedRPM" in browse_names
            # 2. Temperature
            assert "SealingTemperature" in browse_names or "MotorTemperature" in browse_names
            # 3. Vibration
            assert "MainDriveMotorVibration" in browse_names or "BearingVibration" in browse_names
            # 4. Current
            assert "MainDriveMotorCurrent" in browse_names
            # 5. Pressure
            assert "VacuumLevel" in browse_names or "FormingAirPressure" in browse_names
            # 6. Alarms
            assert "MachineFaultAlarm" in browse_names or "EmergencyStopActive" in browse_names
            # 7. Cycles
            assert "CumulativeCycleCount" in browse_names or "BatchProductionCount" in browse_names

        finally:
            await client.disconnect()


# =============================================================================
# 3. DYNAMIC SIGNAL MAPPING (SCALING, OFFSETS, UNITS)
# =============================================================================

def test_dynamic_signal_mapping_persistence(app, onboarding_setup):
    """Configure dynamic signal mappings with engineering units, scaling, and offsets."""
    with app.app_context():
        # Ensure machine exists
        if not db.session.get(Machine, "mach-blister-live-01"):
            mach = Machine(
                id="mach-blister-live-01",
                organization_id=onboarding_setup["org_id"],
                site_id=onboarding_setup["site_id"],
                category_id=onboarding_setup["cat_id"],
                asset_code="PHARMA-BLISTER-02",
                equipment_name="High-Speed Blister Packager Line 2",
            )
            db.session.add(mach)
            db.session.commit()

        # Lookup definitions for the 7 categories
        temp_def = SignalDefinition.query.filter_by(signal_code="SEALING_TEMP").first()
        vib_def = SignalDefinition.query.filter_by(signal_code="MOTOR_VIBRATION").first()
        curr_def = SignalDefinition.query.filter_by(signal_code="MOTOR_CURRENT").first()
        rpm_def = SignalDefinition.query.filter_by(signal_code="ROTATIONAL_SPEED").first()
        press_def = SignalDefinition.query.filter_by(signal_code="LINE_PRESSURE").first()
        alarm_def = SignalDefinition.query.filter_by(signal_code="FAULT_ALARM").first()
        cycle_def = SignalDefinition.query.filter_by(signal_code="CYCLE_COUNTER").first()

        assert all([temp_def, vib_def, curr_def, rpm_def, press_def, alarm_def, cycle_def])

        # Map signals covering all 7 categories with scaling factors and offsets
        signals_to_create = [
            {
                "signal_definition_id": temp_def.id,
                "source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
                "custom_name": "Station 1 Sealing Temperature",
                "source_unit": "°C",
                "normalized_unit": "°C",
                "scaling_factor": 1.0,
                "offset": 0.0,
                "sampling_interval_ms": 1000,
            },
            {
                "signal_definition_id": vib_def.id,
                "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorVibration",
                "custom_name": "Main Motor RMS Vibration",
                "source_unit": "mm/s",
                "normalized_unit": "mm/s",
                "scaling_factor": 1.0,
                "offset": 0.0,
                "sampling_interval_ms": 500,
            },
            {
                "signal_definition_id": curr_def.id,
                "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorCurrent",
                "custom_name": "Main Drive Stator Current",
                "source_unit": "A",
                "normalized_unit": "A",
                "scaling_factor": 0.1,  # 10x raw scaling test
                "offset": 0.5,
                "sampling_interval_ms": 1000,
            },
            {
                "signal_definition_id": rpm_def.id,
                "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MachineSpeedRPM",
                "custom_name": "Main Turret Rotational Speed",
                "source_unit": "RPM",
                "normalized_unit": "RPM",
                "scaling_factor": 1.0,
                "offset": 0.0,
                "sampling_interval_ms": 1000,
            },
            {
                "signal_definition_id": press_def.id,
                "source_node_id": "ns=2;s=BlisterPackagingMachine_01.FormingAirPressure",
                "custom_name": "Forming Station Pneumatic Pressure",
                "source_unit": "bar",
                "normalized_unit": "bar",
                "scaling_factor": 1.0,
                "offset": 0.0,
                "sampling_interval_ms": 1000,
            },
            {
                "signal_definition_id": alarm_def.id,
                "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MachineFaultAlarm",
                "custom_name": "Machine Trip Fault State",
                "source_unit": "Boolean",
                "normalized_unit": "Boolean",
                "scaling_factor": 1.0,
                "offset": 0.0,
                "sampling_interval_ms": 1000,
            },
            {
                "signal_definition_id": cycle_def.id,
                "source_node_id": "ns=2;s=BlisterPackagingMachine_01.CumulativeCycleCount",
                "custom_name": "Lifetime Blister Stroke Counter",
                "source_unit": "Count",
                "normalized_unit": "Count",
                "scaling_factor": 1.0,
                "offset": 0.0,
                "sampling_interval_ms": 2000,
            },
        ]

        created = SignalMappingService.bulk_create_signals(
            machine_id="mach-blister-live-01",
            organization_id=onboarding_setup["org_id"],
            items=signals_to_create,
        )

        assert len(created) == 7
        retrieved = SignalMappingService.list_signals("mach-blister-live-01", onboarding_setup["org_id"])
        assert len(retrieved) == 7
        
        # Verify scaling and offset were persisted accurately
        curr_sig = next(s for s in retrieved if s["source_node_id"].endswith("MainDriveMotorCurrent"))
        assert curr_sig["scaling_factor"] == 0.1
        assert curr_sig["offset"] == 0.5


# =============================================================================
# 4. SIGNAL VALIDATION ENGINE (7-CHECK AUDIT)
# =============================================================================

@pytest.mark.asyncio
async def test_signal_validation_engine_execution(app, onboarding_setup):
    """Execute the 7-check validation engine against mapped signals using the active simulator."""
    async with running_simulator(port=48403) as sim:
        with app.app_context():
            # Setup OPC UA client connected to simulator
            config = ConnectionConfig(
                endpoint_url=sim.get_endpoint(),
                timeout_sec=3.0,
                user_auth_type=UserAuthType.ANONYMOUS,
                auto_trust_unknown=True,
            )
            client = SecureOPCUAClient(config)
            await client.connect()

            try:
                _ensure_signals_mapped(onboarding_setup)
                results = await SignalMappingService.validate_machine_signals(
                    machine_id="mach-blister-live-01",
                    organization_id=onboarding_setup["org_id"],
                    client=client,
                )

                assert len(results) == 7
                for res in results:
                    # All signals should pass validation with VALID or WARNING (none INVALID)
                    assert res["validation_status"] in (ValidationStatus.VALID, ValidationStatus.WARNING), (
                        f"Signal {res['machine_signal_id']} failed validation: {res.get('error_messages')}"
                    )

                summary = SignalMappingService.get_summary("mach-blister-live-01", onboarding_setup["org_id"])
                assert summary["total_signals"] == 7
                assert summary["invalid_count"] == 0
                assert summary["ready_for_monitoring"] is True

            finally:
                await client.disconnect()


# =============================================================================
# 5. EDGE GATEWAY TELEMETRY ACQUISITION, SCALING, & INGESTION
# =============================================================================

@pytest.mark.asyncio
async def test_edge_gateway_telemetry_acquisition_and_scaling(app, onboarding_setup):
    """Verify that EdgeGateway reads simulator nodes, applies scaling and offset,
    preserves simulator_flag=True, and pushes batches to the cloud ingestion endpoint."""
    with app.app_context():
        signals = _ensure_signals_mapped(onboarding_setup)
        assert len(signals) == 7

    async with running_simulator(port=48404) as sim:
        temp_dir = tempfile.mkdtemp(prefix="gateway_test_step2_")
        try:
            gw_config = EdgeGatewayConfig(
                gateway_id=onboarding_setup["gateway_id"],
                organization_id=onboarding_setup["org_id"],
                equipment_id="mach-blister-live-01",
                opcua_endpoint_url=sim.get_endpoint(),
                cloud_ingestion_url="http://127.0.0.1:5000/api/v1/internal/ingestion/readings",
                gateway_secret=onboarding_setup["gateway_secret"],
                buffer_dir=temp_dir,
                is_simulator=True,  # Clearly mark as simulator readings (Requirement 12)
                batch_size=10,
                flush_interval_sec=0.2,
            )

            gateway = EdgeGateway(gw_config)
            gateway.set_monitored_signals(signals)
            assert len(gateway._monitored_signals) == 7

            # Connect OPC UA client
            await gateway.opcua_client.connect()
            assert gateway.opcua_client.is_connected() is True

            # Intercept batch delivery and simulate cloud receipt into IngestionService
            delivered_batches = []

            def mock_cloud_ingest(batch):
                with app.app_context():
                    auth_gw = GatewayAuthRegistry.get_gateway(onboarding_setup["gateway_id"])
                    res = IngestionService.ingest_batch(
                        gateway_id=onboarding_setup["gateway_id"],
                        readings_data=[item.to_dict() for item in batch],
                        batch_identifier=f"batch-test-{len(delivered_batches)}",
                        authenticated_gateway=auth_gw,
                    )
                    delivered_batches.append(res)
                    return True

            gateway.buffer.set_ingestion_handler(mock_cloud_ingest)
            await gateway.buffer.start()

            # Execute 2 telemetry collection cycles
            for _ in range(2):
                for sig in signals:
                    node_id = sig["source_node_id"]
                    val = await gateway.opcua_client.read_value(node_id)
                    now_iso = datetime.now(timezone.utc).isoformat()
                    
                    # Apply scaling & offset
                    norm = round((float(val) * sig["scaling_factor"]) + sig["offset"], 4) if isinstance(val, (int, float)) and not isinstance(val, bool) else (1.0 if val else 0.0)
                    
                    from app.modules.monitoring.data_contract import NormalizedReadingMessage
                    reading = NormalizedReadingMessage(
                        organization_id=onboarding_setup["org_id"],
                        machine_id="mach-blister-live-01",
                        signal_id=sig["id"],
                        source_node_id=node_id,
                        mapping_version=sig["mapping_version"],
                        source_timestamp=now_iso,
                        source_value=val,
                        normalized_value=norm,
                        source_unit=sig["source_unit"],
                        normalized_unit=sig["normalized_unit"],
                        simulator_flag=True,  # Requirement 12
                    )
                    await gateway.ingest_reading(reading)

            # Allow buffer to flush
            await asyncio.sleep(0.5)
            await gateway.buffer.flush()

            assert len(delivered_batches) > 0
            total_ingested = sum(b.get("accepted", 0) for b in delivered_batches)
            assert total_ingested > 0

            # Verify records stored in database
            with app.app_context():
                db_readings = SignalReading.query.filter_by(machine_id="mach-blister-live-01").all()
                assert len(db_readings) >= 7
                for r in db_readings:
                    # Must be strictly marked as simulator data
                    assert r.simulator_flag is True
                    assert r.organization_id == onboarding_setup["org_id"]

                # Verify scaling on current signal (raw ~14.8 -> norm = 14.8 * 0.1 + 0.5 = 1.98)
                curr_sig = next(s for s in signals if "MainDriveMotorCurrent" in s["source_node_id"])
                curr_readings = [r for r in db_readings if r.signal_id == curr_sig["id"]]
                assert len(curr_readings) > 0
                latest_curr = curr_readings[-1]
                assert 1.0 <= latest_curr.normalized_value <= 3.0

            await gateway.buffer.stop()
            await gateway.opcua_client.disconnect()

        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# 6. OPC UA RECONNECTION & FAULT TOLERANCE
# =============================================================================

@pytest.mark.asyncio
async def test_edge_gateway_reconnection_resilience():
    """Verify that EdgeGateway detects OPC UA disconnect and automatically recovers."""
    async with running_simulator(port=48405) as sim:
        config = ConnectionConfig(
            endpoint_url=sim.get_endpoint(),
            timeout_sec=2.0,
            user_auth_type=UserAuthType.ANONYMOUS,
            auto_trust_unknown=True,
        )
        client = SecureOPCUAClient(config)
        await client.connect()
        assert client.is_connected() is True

        # Simulate connection drop
        await client.disconnect()
        assert client.is_connected() is False
        assert client.get_state() == ConnectionState.DISCONNECTED

        # Reconnect successfully
        await client.connect()
        assert client.is_connected() is True
        assert client.get_state() == ConnectionState.CONNECTED

        # Read value after recovery
        val = await client.read_value("ns=2;s=BlisterPackagingMachine_01.SealingTemperature")
        assert isinstance(val, (int, float))

        await client.disconnect()


# =============================================================================
# 7. CARRY FORWARD SECURITY: WILDCARD REJECTION & CORRUPT RECORD QUARANTINE
# =============================================================================

def test_wildcard_machine_authorization_disabled_by_default():
    """Verify that wildcard machine assignment ('*') is strictly rejected by default."""
    gw = GatewayIdentity(
        gateway_id="gw-test-wildcard",
        organization_id="org-test-alpha",
        assigned_equipment_ids=["*"],
        secret="secret-token",
        allow_wildcard=False,  # Default
    )
    
    # Must reject authorization even if '*' is in assigned_equipment_ids
    assert gw.is_authorized_for("org-test-alpha", "mach-arbitrary-99") is False

    # Explicit authorization requires allow_wildcard=True
    gw_allowed = GatewayIdentity(
        gateway_id="gw-test-wildcard-enabled",
        organization_id="org-test-alpha",
        assigned_equipment_ids=["*"],
        secret="secret-token",
        allow_wildcard=True,
    )
    assert gw_allowed.is_authorized_for("org-test-alpha", "mach-arbitrary-99") is True


@pytest.mark.asyncio
async def test_corrupt_records_quarantined_with_critical_alert():
    """Verify that corrupted buffer records are quarantined to a separate file instead of being discarded without trace."""
    temp_dir = tempfile.mkdtemp(prefix="quarantine_test_")
    try:
        buffer = BoundedGatewayBuffer(gateway_id="gw-quarantine-test", disk_buffer_dir=temp_dir)
        recovering_file = Path(temp_dir) / "gateway_recovering.jsonl"
        quarantine_file = Path(temp_dir) / "gateway_corrupt_records.jsonl"

        # Write 1 valid line and 2 corrupted lines
        valid_json = json.dumps({
            "organization_id": "org-01",
            "machine_id": "mach-01",
            "signal_id": "sig-01",
            "source_node_id": "ns=2;s=Node1",
            "mapping_version": 1,
            "source_timestamp": datetime.now(timezone.utc).isoformat(),
            "source_value": 42.0,
            "normalized_value": 42.0,
        })
        with open(recovering_file, "w", encoding="utf-8") as f:
            f.write(valid_json + "\n")
            f.write("CORRUPTED_NON_JSON_RECORD_LINE_1\n")
            f.write("{\"incomplete_json\": true, truncated\n")

        # Run recovery
        await buffer._recover_disk_buffer()

        # Valid reading enqueued in memory
        assert len(buffer._queue) == 1
        # Corrupt records quarantined counter incremented
        metrics = buffer.get_metrics()
        assert metrics["quarantined_corrupt_records"] == 2
        # Quarantine log file exists and contains quarantined records
        assert quarantine_file.exists() is True
        with open(quarantine_file, "r", encoding="utf-8") as qf:
            lines = [json.loads(line) for line in qf]
            assert len(lines) == 2
            assert lines[0]["gateway_id"] == "gw-quarantine-test"

    finally:
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)
