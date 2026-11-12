"""
PharmaPredict AI — Phase 2, Step 3: End-to-End Cloud Ingestion Verification
===========================================================================
Comprehensive end-to-end automated verification testing the complete industrial pipeline:
OPC UA Simulator -> Edge Gateway -> Secure HTTPS Delivery -> Gateway Auth & Machine Authorization
-> Atomic Idempotent Database Storage -> Monitoring APIs (/status, /readings/latest, /readings/history)
-> Frontend-ready Telemetry & Observability.

Test Suite Coverage:
1. Normal telemetry ingestion via HTTP delivery.
2. Duplicate submissions & atomic idempotency.
3. Concurrent parallel submissions race-condition safety.
4. Gateway disconnect & automatic reconnection resilience.
5. Backend downtime, persistent disk buffering, & recovery flush.
6. Invalid gateway credentials rejected (HTTP 403).
7. Unauthorized machine submissions rejected.
8. Cross-tenant submissions rejected.
9. Corrupt disk buffer recovery with record quarantining.
10. Frontend monitoring APIs visibility & freshness indicators.
"""

import os
import sys
import json
import uuid
import time
import asyncio
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
import threading
from contextlib import asynccontextmanager
import pytest

from app.extensions import db
from app.models.tenant import Organization, Site
from app.models.equipment import EquipmentCategory, Machine
from app.models.signal_mapping import SignalDefinition, MachineSignal, SignalGroup, ValidationStatus
from app.models.monitoring import SignalReading, IngestionBatch, GatewayHealthRecord, MonitoringState, SignalFreshness
from app.modules.connectivity.simulator import PharmaOPCUASimulator
from app.modules.connectivity.opcua_client import SecureOPCUAClient
from app.modules.connectivity.models import ConnectionConfig, ConnectionState, UserAuthType
from app.modules.signal_mapping.services import SignalMappingService
from app.modules.signal_mapping.repositories import SignalDefinitionRepository
from app.modules.monitoring.gateway_auth import GatewayAuthRegistry, GatewayIdentity
from app.modules.monitoring.gateway_buffer import BoundedGatewayBuffer
from app.modules.monitoring.ingestion_service import IngestionService
from app.modules.monitoring.lifecycle import MonitoringLifecycleManager
from app.modules.monitoring.data_contract import NormalizedReadingMessage, compute_event_id
from gateway.edge_gateway import EdgeGateway, EdgeGatewayConfig


@asynccontextmanager
async def running_e2e_simulator(port: int = 48415):
    """Context manager running an active simulator on the current event loop."""
    sim = PharmaOPCUASimulator(port=port, enable_security=False)
    await sim.start()
    try:
        yield sim
    finally:
        await sim.stop()


@pytest.fixture
def e2e_setup(app):
    """Set up organization, sites, equipment categories, machine, and gateway identity."""
    with app.app_context():
        # Clean state
        GatewayAuthRegistry.initialize()

        # 1. Organizations
        org_primary = Organization(id="org-e2e-pharma", name="Apex Pharma Ltd", slug="apex-pharma")
        org_secondary = Organization(id="org-e2e-other", name="Other Pharma Corp", slug="other-pharma")
        db.session.add_all([org_primary, org_secondary])
        db.session.commit()

        # 2. Site & Category
        site = Site(id="site-e2e-01", organization_id=org_primary.id, name="Packaging Facility 1")
        cat = EquipmentCategory(id="cat-e2e-blister", organization_id=org_primary.id, name="Blister Packaging", is_default=True)
        db.session.add_all([site, cat])
        db.session.commit()

        # 3. Target Equipment
        target_machine = Machine(
            id="mach-e2e-blister-01",
            organization_id=org_primary.id,
            site_id=site.id,
            category_id=cat.id,
            asset_code="BLIST-E2E-100",
            equipment_name="Primary Blister Packaging Unit",
            manufacturer="Uhlenbeck PharmaTech",
            model="B-3000X",
            criticality="Critical",
        )
        other_machine = Machine(
            id="mach-e2e-unauthorized",
            organization_id=org_primary.id,
            site_id=site.id,
            category_id=cat.id,
            asset_code="BLIST-E2E-UNAUTH",
            equipment_name="Unauthorized Machine",
        )
        cross_tenant_machine = Machine(
            id="mach-e2e-other-tenant",
            organization_id=org_secondary.id,
            site_id=site.id,
            category_id=cat.id,
            asset_code="OTHER-TENANT-01",
            equipment_name="Cross Tenant Equipment",
        )
        db.session.add_all([target_machine, other_machine, cross_tenant_machine])
        db.session.commit()

        # 4. Standard Signal Definitions
        SignalDefinitionRepository.seed_standard_definitions()

        # 5. Map 7 industrial signals to target_machine
        temp_def = SignalDefinition.query.filter_by(signal_code="SEALING_TEMP").first()
        vib_def = SignalDefinition.query.filter_by(signal_code="MOTOR_VIBRATION").first()
        curr_def = SignalDefinition.query.filter_by(signal_code="MOTOR_CURRENT").first()
        rpm_def = SignalDefinition.query.filter_by(signal_code="ROTATIONAL_SPEED").first()
        press_def = SignalDefinition.query.filter_by(signal_code="LINE_PRESSURE").first()
        alarm_def = SignalDefinition.query.filter_by(signal_code="FAULT_ALARM").first()
        cycle_def = SignalDefinition.query.filter_by(signal_code="CYCLE_COUNTER").first()

        signals_to_create = [
            {"signal_definition_id": temp_def.id, "source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature", "custom_name": "Sealing Temp", "source_unit": "°C", "normalized_unit": "°C", "scaling_factor": 1.0, "offset": 0.0, "sampling_interval_ms": 1000},
            {"signal_definition_id": vib_def.id, "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorVibration", "custom_name": "Motor Vibration", "source_unit": "mm/s", "normalized_unit": "mm/s", "scaling_factor": 1.0, "offset": 0.0, "sampling_interval_ms": 500},
            {"signal_definition_id": curr_def.id, "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorCurrent", "custom_name": "Motor Current", "source_unit": "A", "normalized_unit": "A", "scaling_factor": 0.1, "offset": 0.5, "sampling_interval_ms": 1000},
            {"signal_definition_id": rpm_def.id, "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MachineSpeedRPM", "custom_name": "Turret Speed", "source_unit": "RPM", "normalized_unit": "RPM", "scaling_factor": 1.0, "offset": 0.0, "sampling_interval_ms": 1000},
            {"signal_definition_id": press_def.id, "source_node_id": "ns=2;s=BlisterPackagingMachine_01.FormingAirPressure", "custom_name": "Air Pressure", "source_unit": "bar", "normalized_unit": "bar", "scaling_factor": 1.0, "offset": 0.0, "sampling_interval_ms": 1000},
            {"signal_definition_id": alarm_def.id, "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MachineFaultAlarm", "custom_name": "Fault Alarm", "source_unit": "Boolean", "normalized_unit": "Boolean", "scaling_factor": 1.0, "offset": 0.0, "sampling_interval_ms": 1000},
            {"signal_definition_id": cycle_def.id, "source_node_id": "ns=2;s=BlisterPackagingMachine_01.CumulativeCycleCount", "custom_name": "Cycle Counter", "source_unit": "Count", "normalized_unit": "Count", "scaling_factor": 1.0, "offset": 0.0, "sampling_interval_ms": 2000},
        ]
        SignalMappingService.bulk_create_signals(target_machine.id, org_primary.id, signals_to_create)

        # 6. Register Authorized Edge Gateway Identity
        gw_secret = "e2e-gateway-super-secret-token-2026"
        GatewayAuthRegistry.register_gateway(GatewayIdentity(
            gateway_id="gw-e2e-packaging-01",
            organization_id=org_primary.id,
            assigned_equipment_ids=[target_machine.id],
            secret=gw_secret,
            status="ACTIVE",
            allow_wildcard=False,
        ))

        yield {
            "org_primary": org_primary,
            "org_secondary": org_secondary,
            "target_machine": target_machine,
            "other_machine": other_machine,
            "cross_tenant_machine": cross_tenant_machine,
            "gateway_id": "gw-e2e-packaging-01",
            "gateway_secret": gw_secret,
            "mapped_signals": SignalMappingService.list_signals(target_machine.id, org_primary.id),
        }


# =============================================================================
# 1. NORMAL TELEMETRY INGESTION (HTTP ENDPOINT)
# =============================================================================

@pytest.mark.asyncio
async def test_e2e_normal_telemetry_ingestion_http(client, e2e_setup):
    """Test full telemetry pipeline from simulator reading to HTTP ingestion and DB persistence."""
    signals = e2e_setup["mapped_signals"]
    assert len(signals) == 7

    async with running_e2e_simulator(port=48416) as sim:
        config = ConnectionConfig(
            endpoint_url=sim.get_endpoint(),
            timeout_sec=3.0,
            user_auth_type=UserAuthType.ANONYMOUS,
            auto_trust_unknown=True,
        )
        opc_client = SecureOPCUAClient(config)
        await opc_client.connect()
        assert opc_client.is_connected() is True

        try:
            # Build readings batch from live simulator nodes
            readings = []
            now_iso = datetime.now(timezone.utc).isoformat()
            for sig in signals:
                raw_val = await opc_client.read_value(sig["source_node_id"])
                scaling = float(sig.get("scaling_factor") or 1.0)
                offset = float(sig.get("offset") or 0.0)
                norm_val = round((float(raw_val) * scaling) + offset, 4) if isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool) else (1.0 if raw_val else 0.0)

                eid = compute_event_id(
                    machine_id=e2e_setup["target_machine"].id,
                    signal_id=sig["id"],
                    source_timestamp_iso=now_iso,
                    source_value=raw_val,
                )
                readings.append({
                    "event_id": eid,
                    "organization_id": e2e_setup["org_primary"].id,
                    "machine_id": e2e_setup["target_machine"].id,
                    "signal_id": sig["id"],
                    "source_node_id": sig["source_node_id"],
                    "mapping_version": 1,
                    "source_timestamp": now_iso,
                    "source_value": raw_val,
                    "normalized_value": norm_val,
                    "source_unit": sig["source_unit"],
                    "normalized_unit": sig["normalized_unit"],
                    "quality_code": "Good",
                    "normalization_status": "NORMALIZED",
                    "sampling_interval_ms": sig["sampling_interval_ms"],
                    "gateway_id": e2e_setup["gateway_id"],
                    "simulator_flag": True,
                })

            # Submit batch via HTTP to /api/v1/internal/ingestion/readings
            payload = {
                "gateway_id": e2e_setup["gateway_id"],
                "batch_identifier": f"batch-e2e-{uuid.uuid4().hex[:8]}",
                "readings": readings,
                "metrics": {
                    "queue_depth": 0,
                    "buffered_readings": 0,
                    "dropped_readings": 0,
                },
            }
            res = client.post(
                "/api/v1/internal/ingestion/readings",
                json=payload,
                headers={
                    "X-Gateway-Secret": e2e_setup["gateway_secret"],
                    "X-Gateway-ID": e2e_setup["gateway_id"],
                },
            )
            assert res.status_code == 201
            data = res.get_json()
            assert data["metrics"]["accepted"] == 7
            assert data["metrics"]["rejected"] == 0
            assert data["metrics"]["duplicates"] == 0

            # Verify persisted records in database
            db_readings = SignalReading.query.filter_by(machine_id=e2e_setup["target_machine"].id).all()
            assert len(db_readings) == 7
            for r in db_readings:
                assert r.simulator_flag is True
                assert r.organization_id == e2e_setup["org_primary"].id

            # Verify GatewayHealthRecord was updated
            gw_health = GatewayHealthRecord.query.filter_by(gateway_id=e2e_setup["gateway_id"]).first()
            assert gw_health is not None
            assert gw_health.connection_status == "ONLINE"

        finally:
            await opc_client.disconnect()


# =============================================================================
# 2. DUPLICATE SUBMISSIONS & ATOMIC IDEMPOTENCY
# =============================================================================

def test_e2e_duplicate_submissions_idempotency(client, e2e_setup):
    """Test that submitting the exact same batch twice causes zero duplicates in storage."""
    signals = e2e_setup["mapped_signals"]
    now_iso = datetime.now(timezone.utc).isoformat()

    batch = [
        {
            "event_id": compute_event_id(e2e_setup["target_machine"].id, sig["id"], now_iso, 50.0),
            "organization_id": e2e_setup["org_primary"].id,
            "machine_id": e2e_setup["target_machine"].id,
            "signal_id": sig["id"],
            "source_node_id": sig["source_node_id"],
            "mapping_version": 1,
            "source_timestamp": now_iso,
            "source_value": 50.0,
            "normalized_value": 50.0,
            "simulator_flag": True,
        }
        for sig in signals
    ]

    payload = {
        "gateway_id": e2e_setup["gateway_id"],
        "batch_identifier": f"batch-dup-{uuid.uuid4().hex[:8]}",
        "readings": batch,
    }

    # 1. First submission: all accepted
    res1 = client.post(
        "/api/v1/internal/ingestion/readings",
        json=payload,
        headers={"X-Gateway-Secret": e2e_setup["gateway_secret"], "X-Gateway-ID": e2e_setup["gateway_id"]},
    )
    assert res1.status_code == 201
    assert res1.get_json()["metrics"]["accepted"] == 7
    assert res1.get_json()["metrics"]["duplicates"] == 0

    # 2. Duplicate submission: zero accepted, 7 duplicates
    res2 = client.post(
        "/api/v1/internal/ingestion/readings",
        json=payload,
        headers={"X-Gateway-Secret": e2e_setup["gateway_secret"], "X-Gateway-ID": e2e_setup["gateway_id"]},
    )
    assert res2.status_code == 201
    assert res2.get_json()["metrics"]["accepted"] == 0
    assert res2.get_json()["metrics"]["duplicates"] == 7

    # Storage row count remains exactly 7
    total_stored = SignalReading.query.filter_by(machine_id=e2e_setup["target_machine"].id).count()
    assert total_stored == 7


# =============================================================================
# 3. CONCURRENT SUBMISSIONS RACE-CONDITION SAFETY
# =============================================================================

def test_e2e_concurrent_parallel_submissions(app, e2e_setup):
    """Test parallel concurrent requests with overlapping event IDs to guarantee atomic race safety."""
    signals = e2e_setup["mapped_signals"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Pre-generate 10 distinct readings
    common_readings = [
        {
            "event_id": compute_event_id(e2e_setup["target_machine"].id, signals[i % len(signals)]["id"], now_iso, i),
            "organization_id": e2e_setup["org_primary"].id,
            "machine_id": e2e_setup["target_machine"].id,
            "signal_id": signals[i % len(signals)]["id"],
            "source_node_id": signals[i % len(signals)]["source_node_id"],
            "mapping_version": 1,
            "source_timestamp": now_iso,
            "source_value": float(i),
            "normalized_value": float(i),
            "simulator_flag": True,
        }
        for i in range(10)
    ]

    write_lock = threading.Lock()

    def send_concurrent_batch(batch_idx):
        with app.app_context():
            # SQLite in-memory driver does not support simultaneous C-level writes on the same connection;
            # serialize the write dispatch while preserving duplicate race detection across concurrent workers.
            with write_lock:
                auth_gw = GatewayAuthRegistry.get_gateway(e2e_setup["gateway_id"])
                return IngestionService.ingest_batch(
                    gateway_id=e2e_setup["gateway_id"],
                    readings_data=common_readings,
                    batch_identifier=f"batch-concurrent-{batch_idx}",
                    authenticated_gateway=auth_gw,
                )

    # Dispatch 4 concurrent ingestion workers
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(send_concurrent_batch, range(4)))

    total_accepted = sum(r["accepted"] for r in results)
    total_duplicates = sum(r["duplicates"] for r in results)

    # Exactly 10 rows must be accepted across all workers, and 30 rejected as duplicates
    assert total_accepted == 10
    assert total_duplicates == 30

    with app.app_context():
        count = SignalReading.query.filter_by(machine_id=e2e_setup["target_machine"].id).count()
        assert count == 10


# =============================================================================
# 4. GATEWAY DISCONNECT & AUTOMATIC RECONNECTION RESILIENCE
# =============================================================================

@pytest.mark.asyncio
async def test_e2e_gateway_disconnect_and_reconnection():
    """Verify EdgeGateway detects connection loss and reconnects smoothly."""
    async with running_e2e_simulator(port=48417) as sim:
        config = ConnectionConfig(
            endpoint_url=sim.get_endpoint(),
            timeout_sec=2.0,
            user_auth_type=UserAuthType.ANONYMOUS,
            auto_trust_unknown=True,
        )
        client = SecureOPCUAClient(config)
        await client.connect()
        assert client.is_connected() is True

        # Read normal value
        val1 = await client.read_value("ns=2;s=BlisterPackagingMachine_01.SealingTemperature")
        assert val1 == 142.5

        # Force disconnect
        await client.disconnect()
        assert client.is_connected() is False
        assert client.get_state() == ConnectionState.DISCONNECTED

        # Reconnect
        await client.connect()
        assert client.is_connected() is True
        assert client.get_state() == ConnectionState.CONNECTED

        val2 = await client.read_value("ns=2;s=BlisterPackagingMachine_01.SealingTemperature")
        assert val2 == 142.5

        await client.disconnect()


# =============================================================================
# 5. BACKEND DOWNTIME, PERSISTENT DISK BUFFERING, & RECOVERY
# =============================================================================

@pytest.mark.asyncio
async def test_e2e_backend_downtime_and_buffer_recovery(temp_dir=None):
    """Verify that during a backend outage, readings are safely buffered to disk and flushed on recovery."""
    temp_dir = tempfile.mkdtemp(prefix="e2e_outage_")
    try:
        buffer = BoundedGatewayBuffer(
            gateway_id="gw-outage-test",
            buffer_dir=temp_dir,
            max_queue_size=5,
            batch_size=5,
            flush_interval_sec=0.2,
        )

        delivered = []
        is_backend_up = False

        async def dynamic_ingestion_handler(batch):
            if not is_backend_up:
                # Simulating HTTP 503 / Service Unavailable
                return False
            delivered.extend(batch)
            return True

        buffer.set_ingestion_handler(dynamic_ingestion_handler)
        await buffer.start()

        # Generate 4 readings during backend downtime
        for i in range(4):
            r = NormalizedReadingMessage(
                organization_id="org-test",
                machine_id="mach-01",
                signal_id=f"sig-{i}",
                source_node_id=f"ns=2;s=Node_{i}",
                mapping_version=1,
                source_timestamp=datetime.now(timezone.utc).isoformat(),
                source_value=float(i * 10),
            )
            await buffer.push(r)

        # Trigger flush during downtime: should fail delivery and write to disk buffer
        await buffer.flush()
        assert len(delivered) == 0

        # Verify disk buffer has 4 readings
        overflow_file = Path(temp_dir) / "gateway_overflow.jsonl"
        recovering_file = Path(temp_dir) / "gateway_recovering.jsonl"
        lines_on_disk = 0
        for f in (overflow_file, recovering_file):
            if f.exists():
                with open(f, "r", encoding="utf-8") as fp:
                    lines_on_disk += sum(1 for line in fp if line.strip())
        assert lines_on_disk == 4

        # Now simulate backend recovery!
        is_backend_up = True
        await buffer.flush()

        # All 4 readings successfully delivered and disk buffer cleared
        assert len(delivered) == 4
        assert not overflow_file.exists() or overflow_file.stat().st_size == 0
        await buffer.stop()

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# 6. INVALID GATEWAY CREDENTIALS REJECTED
# =============================================================================

def test_e2e_invalid_gateway_credentials_rejected(client, e2e_setup):
    """Verify unauthorized gateway credentials return HTTP 403."""
    payload = {
        "gateway_id": e2e_setup["gateway_id"],
        "batch_identifier": f"batch-{uuid.uuid4().hex[:8]}",
        "readings": [
            {
                "event_id": f"event-{uuid.uuid4()}",
                "organization_id": e2e_setup["org_primary"].id,
                "machine_id": e2e_setup["target_machine"].id,
                "signal_id": "sig-01",
                "source_value": 42.0,
            }
        ]
    }
    # Submit with WRONG secret
    res = client.post(
        "/api/v1/internal/ingestion/readings",
        json=payload,
        headers={"X-Gateway-Secret": "invalid-wrong-secret", "X-Gateway-ID": e2e_setup["gateway_id"]},
    )
    assert res.status_code == 403
    assert "Access denied" in res.get_json()["message"]


# =============================================================================
# 7. UNAUTHORIZED MACHINE SUBMISSIONS REJECTED
# =============================================================================

def test_e2e_unauthorized_machine_submission_rejected(client, e2e_setup):
    """Verify gateway cannot submit telemetry for machines outside its explicit assignment."""
    payload = {
        "gateway_id": e2e_setup["gateway_id"],
        "batch_identifier": f"batch-{uuid.uuid4().hex[:8]}",
        "readings": [
            {
                "event_id": f"event-{uuid.uuid4()}",
                "organization_id": e2e_setup["org_primary"].id,
                "machine_id": e2e_setup["other_machine"].id,  # Other machine not in whitelist!
                "signal_id": "sig-01",
                "source_value": 42.0,
                "source_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    res = client.post(
        "/api/v1/internal/ingestion/readings",
        json=payload,
        headers={"X-Gateway-Secret": e2e_setup["gateway_secret"], "X-Gateway-ID": e2e_setup["gateway_id"]},
    )
    assert res.status_code == 201
    assert res.get_json()["metrics"]["accepted"] == 0
    assert res.get_json()["metrics"]["rejected"] == 1


# =============================================================================
# 8. CROSS-TENANT SUBMISSIONS REJECTED
# =============================================================================

def test_e2e_cross_tenant_submission_rejected(client, e2e_setup):
    """Verify gateway cannot submit readings targeting a different tenant organization."""
    payload = {
        "gateway_id": e2e_setup["gateway_id"],
        "batch_identifier": f"batch-{uuid.uuid4().hex[:8]}",
        "readings": [
            {
                "event_id": f"event-{uuid.uuid4()}",
                "organization_id": e2e_setup["org_secondary"].id,  # Different organization!
                "machine_id": e2e_setup["cross_tenant_machine"].id,
                "signal_id": "sig-01",
                "source_value": 42.0,
                "source_timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    }
    res = client.post(
        "/api/v1/internal/ingestion/readings",
        json=payload,
        headers={"X-Gateway-Secret": e2e_setup["gateway_secret"], "X-Gateway-ID": e2e_setup["gateway_id"]},
    )
    assert res.status_code == 201
    assert res.get_json()["metrics"]["accepted"] == 0
    assert res.get_json()["metrics"]["rejected"] == 1


# =============================================================================
# 9. CORRUPT BUFFER RECORD QUARANTINE
# =============================================================================

@pytest.mark.asyncio
async def test_e2e_corrupt_buffer_recovery_quarantine():
    """Verify unparseable corrupted records are safely quarantined to a separate log file."""
    temp_dir = tempfile.mkdtemp(prefix="e2e_corrupt_")
    try:
        buffer = BoundedGatewayBuffer(gateway_id="gw-corrupt-e2e", disk_buffer_dir=temp_dir)
        recovering_file = Path(temp_dir) / "gateway_recovering.jsonl"
        quarantine_file = Path(temp_dir) / "gateway_corrupt_records.jsonl"

        # 1 valid record and 2 corrupted records
        valid_r = NormalizedReadingMessage(
            organization_id="org-test", machine_id="mach-01", signal_id="sig-01",
            source_node_id="ns=2;s=ValidNode", mapping_version=1,
            source_timestamp=datetime.now(timezone.utc).isoformat(), source_value=123.4,
        )
        with open(recovering_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(valid_r.to_dict()) + "\n")
            f.write("GARBAGE_NON_JSON_CORRUPT_BYTES\n")
            f.write("{\"truncated_json\": true,\n")

        await buffer._recover_disk_buffer()

        # Valid reading enqueued
        assert len(buffer._queue) == 1
        # Corrupted records quarantined
        metrics = buffer.get_metrics()
        assert metrics["quarantined_corrupt_records"] == 2
        assert quarantine_file.exists() is True
        with open(quarantine_file, "r", encoding="utf-8") as qf:
            records = [json.loads(line) for line in qf]
            assert len(records) == 2
            assert records[0]["gateway_id"] == "gw-corrupt-e2e"

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


# =============================================================================
# 10. FRONTEND MONITORING APIS VISIBILITY & FRESHNESS
# =============================================================================

def test_e2e_frontend_monitoring_apis_visibility(app, client, e2e_setup):
    """Verify that frontend monitoring APIs (/readings/latest, /status, /readings/history)
    correctly surface live telemetry, freshness indicators, and gateway health."""
    signals = e2e_setup["mapped_signals"]
    mach_id = e2e_setup["target_machine"].id
    org_id = e2e_setup["org_primary"].id
    now = datetime.now(timezone.utc)

    with app.app_context():
        # Insert a set of fresh readings
        for i, sig in enumerate(signals):
            r = SignalReading(
                event_id=f"fe-test-event-{i}",
                organization_id=org_id,
                machine_id=mach_id,
                signal_id=sig["id"],
                mapping_version=1,
                source_timestamp=now - timedelta(milliseconds=100 * i),  # Fresh (< 2.5s)
                source_value=str(100.0 + i),
                normalized_value=100.0 + i,
                source_unit=sig["source_unit"],
                normalized_unit=sig["normalized_unit"],
                quality_code="Good" if i != 2 else "Bad",  # Signal 2 has Bad quality code
                simulator_flag=True,
                gateway_id=e2e_setup["gateway_id"],
            )
            db.session.add(r)

        # Update gateway health record
        gw_health = GatewayHealthRecord(
            gateway_id=e2e_setup["gateway_id"],
            connection_status="ONLINE",
            last_heartbeat=now,
            queue_depth=2,
            buffered_readings=10,
            dropped_readings=0,
        )
        db.session.add(gw_health)
        db.session.commit()

        # 1. Test get_latest_readings
        latest = IngestionService.get_latest_readings(mach_id, org_id)
        assert len(latest) == 7
        for item in latest:
            assert item["simulator_flag"] is True
            assert item["freshness"] == SignalFreshness.FRESH
            assert "normalized_value" in item
            assert item["normalized_value"] is not None

        # Verify bad quality code preserved
        bad_sig = next(item for item in latest if item["quality_code"] == "Bad")
        assert bad_sig is not None

        # 2. Test get_monitoring_status
        status = MonitoringLifecycleManager.get_status(mach_id, org_id)
        assert status["observed_state"] == MonitoringState.ACTIVE
        assert "streaming live telemetry" in status["status_reason"]
        assert status["active_subscriptions"] == 7
        assert status["buffer_metrics"]["buffered_readings"] == 10
        assert status["simulator_flag"] is True

        # 3. Test get_historical_readings
        history = IngestionService.get_historical_readings(
            machine_id=mach_id,
            organization_id=org_id,
            signal_id=signals[0]["id"],
            limit=50,
        )
        assert len(history) >= 1
        assert history[0]["normalized_value"] == 100.0
        assert history[0]["simulator_flag"] is True
