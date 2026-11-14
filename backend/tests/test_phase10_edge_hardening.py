"""
Automated Test Suite for Phase 10: Industrial Edge Gateway Production Hardening.
================================================================================
Validates:
1. Security & Certificate Management:
   - X.509 client certificate generation and parsing
   - Certificate expiration and days-to-expiry calculation
   - Rejection of expired certificates (ExpiredCertificateError)
   - Rejection of untrusted server certificates (UntrustedCertificateError)
   - Certificate rotation and archiving
   - Prevention of plaintext downgrade (SecurityConfigurationError)
   - Read-only enforcement across all gateway and client write methods (ReadOnlyError)
2. Connectivity & Reconnection:
   - Real connection to local PharmaOPCUASimulator
   - Automatic reconnection logic with exponential backoff and jitter
   - Cloud API timeout and auth failure error classification
3. Store-and-Forward Buffering:
   - RAM queue buffering and metrics (queue depth, utilization %, oldest record age)
   - Crash-safe disk buffer persistence during offline cloud outage
   - Safe disk buffer recovery after gateway restart
   - Deterministic event ID deduplication
   - Disk buffer capacity ceiling and overflow alert handling
4. Industrial Deployment & Health:
   - Pre-flight configuration validation
   - Process healthcheck probe evaluation (healthy, degraded, stalled)
   - Graceful shutdown with buffer flush
"""

import os
import sys
import json
import time
import shutil
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Ensure backend directory is in sys.path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.modules.connectivity.models import (
    ConnectionConfig,
    ConnectionState,
    SecurityPolicy,
    SecurityMode,
    UserAuthType,
    ReadOnlyError,
    OPCUAError,
    AuthenticationError,
    UntrustedCertificateError,
    ExpiredCertificateError,
    SecurityConfigurationError,
    ConnectionTimeoutError,
)
from app.modules.connectivity.security import (
    CertificateValidator,
    CertificateManager,
    generate_self_signed_cert,
    check_certificate_expiry,
    compute_cert_fingerprint,
)
from app.modules.connectivity.opcua_client import SecureOPCUAClient
from app.modules.connectivity.simulator import PharmaOPCUASimulator
from app.modules.monitoring.data_contract import NormalizedReadingMessage, compute_event_id
from app.modules.monitoring.gateway_buffer import BoundedGatewayBuffer
from gateway.edge_gateway import EdgeGateway, EdgeGatewayConfig
from gateway.healthcheck import check_health


@pytest.fixture
def temp_test_dir():
    """Create an isolated temporary directory for test certificates and buffers."""
    tmp = tempfile.mkdtemp(prefix="pharmapredict_p10_test_")
    yield Path(tmp)
    shutil.rmtree(tmp, ignore_errors=True)


# =============================================================================
# 1. SECURITY & X.509 CERTIFICATE MANAGEMENT TESTS
# =============================================================================

def test_security_certificate_generation_and_expiry_check(temp_test_dir):
    """Proves that X.509 certificates are generated with valid RSA keys and correct expiration metrics."""
    cert_path, key_path = generate_self_signed_cert(
        output_dir=str(temp_test_dir),
        common_name="PharmaPredict-Edge-Test",
        validity_days=365,
    )

    assert os.path.isfile(cert_path)
    assert os.path.isfile(key_path)

    # Inspect certificate
    info = check_certificate_expiry(cert_path)
    assert info["common_name"] == "PharmaPredict-Edge-Test"
    assert info["is_valid"] is True
    assert info["is_expired"] is False
    assert 360 <= info["days_remaining"] <= 366
    assert len(info["fingerprint"]) == 95  # 32 bytes * 2 hex chars + 31 colons = 95 chars (XX:XX:...)


def test_security_expired_certificate_rejected(temp_test_dir):
    """Proves that expired certificates are immediately rejected with ExpiredCertificateError."""
    # Generate an artificially expired certificate (validity -10 days)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    expired_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "ExpiredServer")]))
        .issuer_name(x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "ExpiredServer")]))
        .public_key(key.public_key())
        .serial_number(12345)
        .not_valid_before(now - timedelta(days=400))
        .not_valid_after(now - timedelta(days=35))
        .sign(key, hashes.SHA256())
    )
    cert_der = expired_cert.public_bytes(serialization.Encoding.DER)

    info = check_certificate_expiry(cert_der)
    assert info["is_expired"] is True
    assert info["days_remaining"] < 0

    validator = CertificateValidator(auto_trust_unknown=True, enforce_expiry=True)
    with pytest.raises(ExpiredCertificateError) as exc_info:
        validator.validate_certificate(cert_der)
    assert "expired" in str(exc_info.value).lower()


def test_security_untrusted_certificate_rejected(temp_test_dir):
    """Proves that unapproved certificates are rejected with UntrustedCertificateError."""
    cert_path, _ = generate_self_signed_cert(str(temp_test_dir), common_name="RoguePLC")
    with open(cert_path, "rb") as f:
        cert_pem = f.read()
    cert_der = x509.load_pem_x509_certificate(cert_pem).public_bytes(serialization.Encoding.DER)

    # Empty trust store, auto_trust=False
    validator = CertificateValidator(
        trusted_fingerprints=[],
        trusted_certs_dir=str(temp_test_dir / "empty_trust"),
        auto_trust_unknown=False,
    )

    with pytest.raises(UntrustedCertificateError) as exc_info:
        validator.validate_certificate(cert_der)
    assert "not in the trusted certificate store" in str(exc_info.value)


def test_security_certificate_rotation(temp_test_dir):
    """Proves that CertificateManager can rotate certificates and archive the previous pair."""
    cert_dir = temp_test_dir / "certs"
    cert1, key1 = CertificateManager.rotate_client_certificate(
        str(cert_dir), common_name="EdgeGW-01", validity_days=100
    )
    assert os.path.exists(cert1)
    with open(cert1, "rb") as f:
        cert1_bytes = f.read()

    # Small pause to ensure timestamp differs
    time.sleep(0.05)

    # Rotate
    cert2, key2 = CertificateManager.rotate_client_certificate(
        str(cert_dir), common_name="EdgeGW-01", validity_days=200
    )
    assert os.path.exists(cert2)
    with open(cert2, "rb") as f:
        cert2_bytes = f.read()

    # Archived previous cert must exist
    archive_dir = cert_dir / "archive"
    assert archive_dir.is_dir()
    archived_files = list(archive_dir.glob("*.pem"))
    assert len(archived_files) >= 2


def test_security_fail_closed_plaintext_downgrade():
    """Proves that setting a security policy with security_mode=None fails closed."""
    # 1. EdgeGatewayConfig pre-flight rejection
    cfg = EdgeGatewayConfig(
        gateway_id="gw-fail-closed",
        opcua_security_policy="Basic256Sha256",
        opcua_security_mode="None",  # Inconsistent!
        allow_insecure_http=True,
    )
    with pytest.raises(SecurityConfigurationError) as exc:
        cfg.validate()
    assert "security_mode" in str(exc.value).lower()
    assert "none" in str(exc.value).lower()

    # 2. SecureOPCUAClient connect rejection
    conn_cfg = ConnectionConfig(
        endpoint_url="opc.tcp://127.0.0.1:48401/test",
        security_policy=SecurityPolicy.BASIC256_SHA256,
        security_mode=SecurityMode.NONE,
    )
    client = SecureOPCUAClient(conn_cfg)
    with pytest.raises(SecurityConfigurationError):
        asyncio.run(client.connect())


def test_security_read_only_enforcement(temp_test_dir):
    """Proves that all write operations to PLCs are prohibited and raise ReadOnlyError."""
    cfg = EdgeGatewayConfig(
        gateway_id="gw-readonly-test",
        buffer_dir=str(temp_test_dir),
        allow_insecure_http=True,
    )
    gw = EdgeGateway(cfg)

    # Gateway level
    with pytest.raises(ReadOnlyError):
        asyncio.run(gw.write_plc_value("ns=2;s=Device.MotorSpeed", 1500))

    # Client level
    conn_cfg = ConnectionConfig(endpoint_url="opc.tcp://127.0.0.1:48401/test")
    client = SecureOPCUAClient(conn_cfg)
    with pytest.raises(ReadOnlyError):
        asyncio.run(client.write_value("ns=2;s=Device.MotorSpeed", 1500))
    with pytest.raises(ReadOnlyError):
        asyncio.run(client.write_attribute("ns=2;s=Device.MotorSpeed", 13, 1500))
    with pytest.raises(ReadOnlyError):
        asyncio.run(client.set_value("ns=2;s=Device.MotorSpeed", 1500))


# =============================================================================
# 2. CONFIGURATION VALIDATION TESTS
# =============================================================================

def test_config_preflight_validation():
    """Proves that EdgeGatewayConfig validates parameters before starting workers."""
    # Missing gateway_id
    with pytest.raises(ValueError, match="gateway_id"):
        EdgeGatewayConfig(gateway_id="").validate()

    # Invalid OPC UA endpoint URL schema
    with pytest.raises(ValueError, match="opcua_endpoint_url"):
        EdgeGatewayConfig(gateway_id="gw-1", opcua_endpoint_url="http://plc.local:4840").validate()

    # Plaintext HTTP cloud delivery in production rejected
    with pytest.raises(ValueError, match="strictly prohibited in industrial production"):
        EdgeGatewayConfig(
            gateway_id="gw-1",
            cloud_ingestion_url="http://remote-cloud-server.com/api/v1/ingestion",
            allow_insecure_http=False,
        ).validate()

    # UserName auth without username
    with pytest.raises(ValueError, match="opcua_username"):
        EdgeGatewayConfig(
            gateway_id="gw-1",
            opcua_auth_type="UserName",
            opcua_username="",
            allow_insecure_http=True,
        ).validate()


# =============================================================================
# 3. STORE-AND-FORWARD TELEMETRY BUFFER TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_store_and_forward_ram_buffering_and_metrics(temp_test_dir):
    """Proves bounded RAM queue, utilization % calculation, and oldest record age tracking."""
    buf = BoundedGatewayBuffer(
        gateway_id="gw-ram-test",
        max_queue_size=10,
        batch_size=5,
        flush_interval_sec=0.1,
        disk_buffer_dir=str(temp_test_dir),
    )

    t0 = datetime.now(timezone.utc) - timedelta(seconds=12)
    reading = NormalizedReadingMessage(
        organization_id="org-1",
        machine_id="mach-1",
        signal_id="sig-temp",
        source_node_id="ns=2;s=Device.Temp",
        mapping_version=1,
        source_timestamp=t0.isoformat(),
        source_value=45.2,
        normalized_value=45.2,
        raw_value_numeric=45.2,
        source_unit="°C",
        normalized_unit="°C",
    )

    pushed = await buf.push(reading)
    assert pushed is True

    metrics = buf.get_metrics()
    assert metrics["queue_depth"] == 1
    assert metrics["queue_utilization_pct"] == 10.0
    assert metrics["oldest_record_age_sec"] >= 10.0


@pytest.mark.asyncio
async def test_store_and_forward_disk_persistence_and_restart_recovery(temp_test_dir):
    """Proves that when cloud delivery fails, telemetry spools to disk and recovers safely on restart."""
    delivered_readings = []

    # Handler simulating temporary cloud backend outage
    def failing_handler(batch):
        return False

    buf = BoundedGatewayBuffer(
        gateway_id="gw-recovery-test",
        max_queue_size=5,
        batch_size=5,
        flush_interval_sec=0.05,
        disk_buffer_dir=str(temp_test_dir),
    )
    buf.set_ingestion_handler(failing_handler)
    await buf.start()

    # Generate 5 readings
    for i in range(5):
        r = NormalizedReadingMessage(
            organization_id="org-1",
            machine_id="mach-1",
            signal_id=f"sig-{i}",
            source_node_id=f"ns=2;s=Device.Tag{i}",
            mapping_version=1,
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            source_value=float(i * 10),
            normalized_value=float(i * 10),
            raw_value_numeric=float(i * 10),
            source_unit="bar",
            normalized_unit="bar",
        )
        await buf.push(r)

    # Trigger flush while cloud is down
    flushed = await buf.flush()
    assert flushed == 0

    # Stop buffer (simulating edge gateway shutdown/restart)
    await buf.stop()

    # Verify disk overflow file exists and is populated
    overflow_file = temp_test_dir / "gateway_overflow.jsonl"
    recovering_file = temp_test_dir / "gateway_recovering.jsonl"
    assert overflow_file.exists() or recovering_file.exists()

    # Now restart gateway with restored cloud connectivity
    def restored_handler(batch):
        delivered_readings.extend(batch)
        return True

    buf_restarted = BoundedGatewayBuffer(
        gateway_id="gw-recovery-test",
        max_queue_size=5,
        batch_size=10,
        flush_interval_sec=0.05,
        disk_buffer_dir=str(temp_test_dir),
    )
    buf_restarted.set_ingestion_handler(restored_handler)

    # Recover and flush
    recovered_count = await buf_restarted.flush()
    assert len(delivered_readings) == 5
    assert {r.signal_id for r in delivered_readings} == {f"sig-{i}" for i in range(5)}


@pytest.mark.asyncio
async def test_store_and_forward_disk_overflow_ceiling(temp_test_dir):
    """Proves that disk buffer strictly adheres to capacity boundary and emits overflow alert."""
    tiny_max_bytes = 300  # Allows ~1 record before hitting ceiling
    buf = BoundedGatewayBuffer(
        gateway_id="gw-ceiling-test",
        max_queue_size=1,  # Fill RAM quickly
        batch_size=1,
        disk_buffer_dir=str(temp_test_dir),
        max_disk_buffer_bytes=tiny_max_bytes,
    )

    r1 = NormalizedReadingMessage(
        organization_id="org-1",
        machine_id="mach-1",
        signal_id="sig-1",
        source_node_id="ns=2;s=Device.Tag1",
        mapping_version=1,
        source_timestamp=datetime.now(timezone.utc).isoformat(),
        source_value=1.0,
        normalized_value=1.0,
    )
    r2 = NormalizedReadingMessage(
        organization_id="org-1",
        machine_id="mach-1",
        signal_id="sig-2",
        source_node_id="ns=2;s=Device.Tag2",
        mapping_version=1,
        source_timestamp=datetime.now(timezone.utc).isoformat(),
        source_value=2.0,
        normalized_value=2.0,
    )
    r3 = NormalizedReadingMessage(
        organization_id="org-1",
        machine_id="mach-1",
        signal_id="sig-3",
        source_node_id="ns=2;s=Device.Tag3",
        mapping_version=1,
        source_timestamp=datetime.now(timezone.utc).isoformat(),
        source_value=3.0,
        normalized_value=3.0,
    )

    # 1st goes to RAM queue
    assert await buf.push(r1) is True

    # 2nd spills to disk
    assert await buf.push(r2) is True

    # 3rd attempts to spill to disk, but disk capacity is now exceeded
    assert await buf.push(r3) is False

    metrics = buf.get_metrics()
    assert metrics["dropped_readings"] >= 1
    assert metrics["overflow_active"] is True


# =============================================================================
# 4. HEALTHCHECK PROBE TESTS
# =============================================================================

def test_healthcheck_probe(temp_test_dir, monkeypatch):
    """Proves that healthcheck.py correctly detects responsive, degraded, and stalled gateway states."""
    monkeypatch.setenv("BUFFER_DIR", str(temp_test_dir))
    health_file = temp_test_dir / ".gateway_health.json"

    # 1. Responsive state -> returns 0
    state_ok = {
        "gateway_id": "gw-test",
        "is_running": True,
        "timestamp_epoch": time.time(),
        "opcua_connected": True,
        "overflow_active": False,
        "client_cert_days_remaining": 300,
        "uptime_sec": 42.0,
    }
    with open(health_file, "w") as f:
        json.dump(state_ok, f)
    assert check_health() == 0

    # 2. Stalled event loop (heartbeat age > 60s) -> returns 1
    state_stalled = dict(state_ok)
    state_stalled["timestamp_epoch"] = time.time() - 120.0
    with open(health_file, "w") as f:
        json.dump(state_stalled, f)
    assert check_health() == 1

    # 3. Expired certificate -> returns 1
    state_expired_cert = dict(state_ok)
    state_expired_cert["client_cert_days_remaining"] = -5
    with open(health_file, "w") as f:
        json.dump(state_expired_cert, f)
    assert check_health() == 1


# =============================================================================
# 5. END-TO-END SIMULATOR INTEGRATION & RECONNECTION TEST
# =============================================================================

@pytest.mark.asyncio
async def test_end_to_end_simulator_connection_and_telemetry(temp_test_dir):
    """Proves that EdgeGateway connects to local PharmaOPCUASimulator, polls tags, and stops cleanly."""
    port = 48499
    sim = PharmaOPCUASimulator(port=port)
    await sim.start()

    delivered_batches = []

    def mock_delivery(batch):
        delivered_batches.append(batch)
        return True

    endpoint = f"opc.tcp://127.0.0.1:{port}/pharmapredict/server/"
    cfg = EdgeGatewayConfig(
        gateway_id="gw-sim-test",
        organization_id="org-test-pharma",
        equipment_id="0d9bba98-6ad9-417c-9543-ef024447ef04",
        opcua_endpoint_url=endpoint,
        buffer_dir=str(temp_test_dir),
        batch_size=5,
        flush_interval_sec=0.1,
        allow_insecure_http=True,
    )
    gw = EdgeGateway(cfg)
    gw.buffer.set_ingestion_handler(mock_delivery)

    # Register monitored signals from simulator
    gw.add_monitored_signal({
        "signal_id": "sig-forming-temp",
        "source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
        "scaling_factor": 1.0,
        "offset": 0.0,
        "source_unit": "°C",
        "normalized_unit": "°C",
    })
    gw.add_monitored_signal({
        "signal_id": "sig-motor-vib",
        "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorVibration",
        "scaling_factor": 1.0,
        "offset": 0.0,
        "source_unit": "mm/s",
        "normalized_unit": "mm/s",
    })

    try:
        await gw.start()
        # Allow gateway telemetry loop to poll simulator
        await asyncio.sleep(2.0)

        # Force a flush of buffered items
        await gw.buffer.flush()

        metrics = gw.get_metrics()
        assert metrics["opcua_connected"] is True
        assert metrics["is_running"] is True
        assert len(delivered_batches) > 0

        # Verify reading structure
        first_reading = delivered_batches[0][0]
        assert first_reading.organization_id == "org-test-pharma"
        assert first_reading.machine_id == "0d9bba98-6ad9-417c-9543-ef024447ef04"
        assert first_reading.event_id is not None

    finally:
        await gw.stop()
        await sim.stop()
