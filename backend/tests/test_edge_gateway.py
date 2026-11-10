import os
import sys
import json
import uuid
import shutil
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytest
import httpx

from app.modules.connectivity.models import ReadOnlyError, ConnectionState
from app.modules.connectivity.simulator import PharmaOPCUASimulator
from app.modules.monitoring.data_contract import NormalizedReadingMessage, compute_event_id
from gateway.edge_gateway import EdgeGateway, EdgeGatewayConfig


@pytest.fixture
def temp_buffer_dir():
    """Create a temporary directory for buffer testing and clean up afterward."""
    tmp = tempfile.mkdtemp(prefix="pharmapredict_test_buf_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def base_config(temp_buffer_dir):
    """Return a baseline EdgeGatewayConfig for testing."""
    return EdgeGatewayConfig(
        gateway_id="gw-test-01",
        organization_id="org-test-uuid",
        equipment_id="mach-test-uuid",
        opcua_endpoint_url="opc.tcp://127.0.0.1:48401/pharmapredict/server/",
        cloud_ingestion_url="http://127.0.0.1:5000/api/v1/internal/ingestion/readings",
        gateway_secret="test-secret-key-12345",
        buffer_dir=temp_buffer_dir,
        max_queue_size=100,
        batch_size=10,
        flush_interval_sec=0.2,
        request_timeout_sec=2.0,
    )


# =============================================================================
# 1. CONFIGURATION & SECRET MASKING TESTS
# =============================================================================

def test_edge_gateway_config_from_env_and_secret_masking(monkeypatch):
    """Ensure environment loading works and secrets are NEVER exposed in repr/logs."""
    monkeypatch.setenv("GATEWAY_ID", "gw-env-unit-99")
    monkeypatch.setenv("ORGANIZATION_ID", "org-pharma-secure")
    monkeypatch.setenv("EQUIPMENT_ID", "mach-blister-05")
    monkeypatch.setenv("GATEWAY_INTERNAL_SECRET", "super-secret-key-never-leak")
    monkeypatch.setenv("OPCUA_PASSWORD", "operator-secret-pwd")

    cfg = EdgeGatewayConfig.from_env()

    assert cfg.gateway_id == "gw-env-unit-99"
    assert cfg.organization_id == "org-pharma-secure"
    assert cfg.equipment_id == "mach-blister-05"
    assert cfg.gateway_secret == "super-secret-key-never-leak"
    assert cfg.opcua_password == "operator-secret-pwd"

    # CRITICAL: Verify repr masking
    repr_str = repr(cfg)
    assert "super-secret-key-never-leak" not in repr_str
    assert "operator-secret-pwd" not in repr_str
    assert "***REDACTED***" in repr_str


# =============================================================================
# 2. READ-ONLY ENFORCEMENT TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_edge_gateway_read_only_enforcement(base_config):
    """Enforce that edge gateway strictly prohibits PLC writes and setpoint changes."""
    gateway = EdgeGateway(base_config)

    # 1. Gateway level write rejection
    with pytest.raises(ReadOnlyError) as exc_gw:
        await gateway.write_plc_value("ns=2;s=MachineSpeed", 120.0)
    assert "strictly read-only" in str(exc_gw.value)

    # 2. Underlying OPC UA client level write rejection
    with pytest.raises(ReadOnlyError) as exc_client:
        await gateway.opcua_client.write_value("ns=2;s=MachineSpeed", 120.0)
    assert "strictly disallowed" in str(exc_client.value)

    with pytest.raises(ReadOnlyError):
        await gateway.opcua_client.write_attribute("ns=2;s=MachineSpeed", 13, 100)


# =============================================================================
# 3. IDENTITY PROTECTION & TENANT ISOLATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_edge_gateway_identity_protection(base_config):
    """Ensure gateway rejects telemetry spoofed with incorrect org or machine IDs."""
    gateway = EdgeGateway(base_config)

    # A: Reading with wrong organization_id
    bad_org_reading = NormalizedReadingMessage(
        organization_id="wrong-hacker-org",
        machine_id=base_config.equipment_id,
        signal_id="sig-01",
        source_node_id="ns=2;s=Speed",
        mapping_version=1,
        source_timestamp=datetime.now(timezone.utc).isoformat(),
        source_value=45.0,
    )
    result_org = await gateway.ingest_reading(bad_org_reading)
    assert result_org is False
    assert gateway._rejected_identity_violations == 1

    # B: Reading with wrong machine_id
    bad_mach_reading = NormalizedReadingMessage(
        organization_id=base_config.organization_id,
        machine_id="wrong-machine-target",
        signal_id="sig-01",
        source_node_id="ns=2;s=Speed",
        mapping_version=1,
        source_timestamp=datetime.now(timezone.utc).isoformat(),
        source_value=45.0,
    )
    result_mach = await gateway.ingest_reading(bad_mach_reading)
    assert result_mach is False
    assert gateway._rejected_identity_violations == 2

    # C: Legitimate reading matching configured identity
    good_reading = NormalizedReadingMessage(
        organization_id=base_config.organization_id,
        machine_id=base_config.equipment_id,
        signal_id="sig-01",
        source_node_id="ns=2;s=Speed",
        mapping_version=1,
        source_timestamp=datetime.now(timezone.utc).isoformat(),
        source_value=45.0,
    )
    result_good = await gateway.ingest_reading(good_reading)
    assert result_good is True
    assert gateway._rejected_identity_violations == 2
    assert gateway.buffer.get_metrics()["queue_depth"] == 1


# =============================================================================
# 4. DETERMINISTIC EVENT ID PRESERVATION TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_edge_gateway_event_id_preservation(base_config):
    """Verify event IDs are deterministically generated and preserved for idempotent ingestion."""
    gateway = EdgeGateway(base_config)

    ts = "2026-11-11T00:00:00+00:00"
    reading = NormalizedReadingMessage(
        organization_id=base_config.organization_id,
        machine_id=base_config.equipment_id,
        signal_id="sig-speed",
        source_node_id="ns=2;s=Speed",
        mapping_version=1,
        source_timestamp=ts,
        source_value=120.5,
    )

    expected_eid = compute_event_id(
        machine_id=base_config.equipment_id,
        signal_id="sig-speed",
        source_timestamp_iso=ts,
        source_value=120.5,
    )

    assert reading.event_id == expected_eid
    await gateway.ingest_reading(reading)

    metrics = gateway.buffer.get_metrics()
    assert metrics["queue_depth"] == 1


# =============================================================================
# 5. RAM BUFFERING & PERSISTENT DISK FALLBACK TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_edge_gateway_disk_buffering_on_queue_overflow(temp_buffer_dir):
    """Test RAM queue bounds and automatic overflow spilling to disk buffer."""
    cfg = EdgeGatewayConfig(
        gateway_id="gw-overflow-test",
        organization_id="org-test",
        equipment_id="mach-test",
        buffer_dir=temp_buffer_dir,
        max_queue_size=3,  # Strict small queue
        max_disk_buffer_bytes=50 * 1024 * 1024,
    )
    gateway = EdgeGateway(cfg)

    # Ingest 5 readings (3 fit in RAM, 2 must spill to disk)
    for i in range(5):
        reading = NormalizedReadingMessage(
            organization_id="org-test",
            machine_id="mach-test",
            signal_id=f"sig-{i}",
            source_node_id=f"ns=2;s=Node_{i}",
            mapping_version=1,
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            source_value=i * 10.0,
        )
        pushed = await gateway.ingest_reading(reading)
        assert pushed is True

    metrics = gateway.get_metrics()
    assert metrics["queue_depth"] == 3
    assert metrics["buffered_disk_readings"] == 2

    # Check disk file exists
    overflow_file = Path(temp_buffer_dir) / "gateway_overflow.jsonl"
    assert overflow_file.exists()
    with open(overflow_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 2


# =============================================================================
# 6. BUFFER SURVIVES GATEWAY RESTARTS TEST
# =============================================================================

@pytest.mark.asyncio
async def test_edge_gateway_disk_buffer_survives_restart(temp_buffer_dir):
    """Verify that persisted disk events survive a complete gateway restart and are drained."""
    overflow_file = Path(temp_buffer_dir) / "gateway_overflow.jsonl"
    
    # Pre-populate disk overflow file as if written before a crash/restart
    test_readings = [
        NormalizedReadingMessage(
            organization_id="org-restart",
            machine_id="mach-restart",
            signal_id=f"sig-disk-{i}",
            source_node_id=f"ns=2;s=Sensor_{i}",
            mapping_version=1,
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            source_value=float(i),
        )
        for i in range(4)
    ]
    with open(overflow_file, "w", encoding="utf-8") as f:
        for r in test_readings:
            f.write(json.dumps(r.to_dict()) + "\n")

    cfg = EdgeGatewayConfig(
        gateway_id="gw-restart-test",
        organization_id="org-restart",
        equipment_id="mach-restart",
        buffer_dir=temp_buffer_dir,
        max_queue_size=100,
        batch_size=10,
    )

    # Initialize new gateway instance
    gateway = EdgeGateway(cfg)
    assert gateway.buffer._buffered_disk_count == 4

    # Mock delivery handler
    delivered_batches = []
    async def mock_delivery(batch):
        delivered_batches.append(batch)
        return True

    gateway.buffer.set_ingestion_handler(mock_delivery)

    # Flush should recover disk buffer into queue and deliver it
    flushed = await gateway.buffer.flush()
    assert flushed == 4
    assert len(delivered_batches) == 1
    assert len(delivered_batches[0]) == 4
    assert gateway.buffer._buffered_disk_count == 0


# =============================================================================
# 7. OUTBOUND HTTPS DELIVERY WITH AUTH HEADER TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_edge_gateway_outbound_delivery_auth_and_retry(base_config):
    """Verify outbound delivery includes X-Gateway-Secret and handles HTTP responses."""
    gateway = EdgeGateway(base_config)

    test_batch = [
        NormalizedReadingMessage(
            organization_id=base_config.organization_id,
            machine_id=base_config.equipment_id,
            signal_id="sig-temp",
            source_node_id="ns=2;s=Temp",
            mapping_version=1,
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            source_value=65.2,
        )
    ]

    # Test 1: Successful delivery (HTTP 201)
    def mock_handler_success(request: httpx.Request):
        assert request.headers.get("X-Gateway-Secret") == base_config.gateway_secret
        assert request.headers.get("Content-Type") == "application/json"
        data = json.loads(request.content)
        assert data["gateway_id"] == base_config.gateway_id
        assert len(data["readings"]) == 1
        return httpx.Response(201, json={"message": "Batch ingested successfully."})

    transport_success = httpx.MockTransport(mock_handler_success)
    gateway._http_client = httpx.AsyncClient(transport=transport_success)

    ok = await gateway._deliver_batch_to_cloud(test_batch)
    assert ok is True
    assert gateway._delivered_batches == 1
    assert gateway._delivered_readings == 1

    # Test 2: Authentication failure (HTTP 403)
    def mock_handler_auth_fail(request: httpx.Request):
        return httpx.Response(403, json={"error": "Forbidden", "message": "Access denied."})

    transport_auth_fail = httpx.MockTransport(mock_handler_auth_fail)
    gateway._http_client = httpx.AsyncClient(transport=transport_auth_fail)

    ok_auth_fail = await gateway._deliver_batch_to_cloud(test_batch)
    assert ok_auth_fail is False
    assert gateway._failed_deliveries == 1


# =============================================================================
# 8. INTEGRATION WITH REAL OPC UA SIMULATOR TEST
# =============================================================================

@pytest.mark.asyncio
async def test_edge_gateway_integration_with_simulator(temp_buffer_dir):
    """End-to-end integration test connecting EdgeGateway to PharmaOPCUASimulator."""
    sim_port = 48408
    simulator = PharmaOPCUASimulator(port=sim_port, enable_security=False)
    await simulator.start()

    cfg = EdgeGatewayConfig(
        gateway_id="gw-sim-integration",
        organization_id="org-sim-test",
        equipment_id="mach-blister-01",
        opcua_endpoint_url=f"opc.tcp://127.0.0.1:{sim_port}/pharmapredict/server/",
        cloud_ingestion_url="http://127.0.0.1:5000/api/v1/internal/ingestion/readings",
        gateway_secret="test-sim-secret",
        buffer_dir=temp_buffer_dir,
        max_queue_size=50,
        batch_size=5,
        flush_interval_sec=0.1,
    )

    gateway = EdgeGateway(cfg)

    # Mock cloud ingestion so batches don't need real backend container running
    ingested_batches = []
    async def mock_cloud_ingest(batch):
        ingested_batches.append(batch)
        return True

    gateway.buffer.set_ingestion_handler(mock_cloud_ingest)

    try:
        # Start gateway (connects to OPC UA simulator)
        await gateway.start()
        await asyncio.sleep(0.5)

        assert gateway.opcua_client.is_connected() is True
        assert gateway.opcua_client.get_state() == ConnectionState.CONNECTED

        # Read directly from simulated node using gateway client (READ ONLY)
        node_id = simulator.blister_speed_node.nodeid.to_string()
        val = await gateway.opcua_client.read_value(node_id)
        assert isinstance(val, (int, float))

        # Ingest reading through gateway
        reading = NormalizedReadingMessage(
            organization_id=cfg.organization_id,
            machine_id=cfg.equipment_id,
            signal_id="sig-speed",
            source_node_id=node_id,
            mapping_version=1,
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            source_value=val,
        )
        await gateway.ingest_reading(reading)

        # Trigger buffer flush
        await gateway.buffer.flush()
        assert len(ingested_batches) >= 1
        assert ingested_batches[0][0].source_value == val

    finally:
        await gateway.stop()
        if simulator.server:
            await simulator.server.stop()

    assert gateway.opcua_client.is_connected() is False
    assert gateway._is_running is False
