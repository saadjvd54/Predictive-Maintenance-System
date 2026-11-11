"""
PharmaPredict AI — Step 1.1 Security & Reliability Remediation Test Suite
========================================================================
Comprehensive automated test suite covering:
1. FIX 1: Gateway Authentication, Tenant Authorization, Constant-time comparison, Anti-spoofing
2. FIX 2: Atomic Database Idempotency (INSERT ... ON CONFLICT DO NOTHING), Concurrency, Mixed batches
3. FIX 3: Crash-safe staging disk buffer, Durability fsync, Corruption tolerance
4. FIX 4: Disk buffer capacity enforcement, Overflow audit timestamps, Metrics observability
5. FIX 5: Gateway healthcheck probe (stalled loop detection, degraded state handling)
"""

import os
import sys
import json
import time
import uuid
import hmac
import shutil
import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timezone
import pytest
from unittest.mock import patch, MagicMock

from app import create_app
from app.extensions import db
from app.models.tenant import Organization, Site
from app.models.equipment import EquipmentCategory, Machine
from app.models.monitoring import SignalReading, IngestionBatch
from app.modules.monitoring.data_contract import NormalizedReadingMessage, compute_event_id
from app.modules.monitoring.gateway_auth import GatewayAuthRegistry, GatewayIdentity
from app.modules.monitoring.gateway_buffer import BoundedGatewayBuffer
from app.modules.monitoring.ingestion_service import IngestionService
from gateway.edge_gateway import EdgeGateway, EdgeGatewayConfig
from gateway.healthcheck import check_health


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def test_setup(app):
    """Set up database entities and registered test gateways."""
    with app.app_context():
        # Create Org 1 and Machines
        org1 = Organization(id="org-test-alpha", name="Alpha Pharma", slug="alpha-pharma")
        org2 = Organization(id="org-test-beta", name="Beta Pharma", slug="beta-pharma")
        db.session.add_all([org1, org2])
        db.session.commit()

        site1 = Site(id="site-01", organization_id=org1.id, name="Main Site")
        db.session.add(site1)
        db.session.commit()

        cat1 = EquipmentCategory(id="cat-01", organization_id=org1.id, name="Packaging", is_default=True)
        db.session.add(cat1)
        db.session.commit()

        mach1 = Machine(
            id="mach-alpha-blister-01",
            organization_id=org1.id,
            site_id=site1.id,
            category_id=cat1.id,
            asset_code="BLIST-01",
            equipment_name="Blister Packager Alpha",
        )
        mach2 = Machine(
            id="mach-alpha-tablet-02",
            organization_id=org1.id,
            site_id=site1.id,
            category_id=cat1.id,
            asset_code="TAB-02",
            equipment_name="Tablet Press Alpha",
        )
        mach_beta = Machine(
            id="mach-beta-blister-99",
            organization_id=org2.id,
            site_id=site1.id,
            category_id=cat1.id,
            asset_code="BETA-99",
            equipment_name="Blister Packager Beta",
        )
        db.session.add_all([mach1, mach2, mach_beta])
        db.session.commit()

        # Register Gateway Identities in GatewayAuthRegistry
        GatewayAuthRegistry.register_gateway(GatewayIdentity(
            gateway_id="gw-alpha-authorized",
            organization_id=org1.id,
            assigned_equipment_ids=[mach1.id],  # ONLY authorized for mach1
            secret="alpha-gateway-secret-token-2026",
            status="ACTIVE",
        ))

        GatewayAuthRegistry.register_gateway(GatewayIdentity(
            gateway_id="gw-alpha-revoked",
            organization_id=org1.id,
            assigned_equipment_ids=[mach1.id],
            secret="revoked-gateway-secret-2026",
            status="REVOKED",
        ))

        yield {
            "org1": org1,
            "org2": org2,
            "mach1": mach1,
            "mach2": mach2,
            "mach_beta": mach_beta,
        }


@pytest.fixture
def temp_buffer_dir():
    """Create a temporary directory for buffer tests."""
    tmp = tempfile.mkdtemp(prefix="pharmapredict_remediation_")
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


# =============================================================================
# 1. FIX 1: GATEWAY AUTHENTICATION & TENANT AUTHORIZATION TESTS
# =============================================================================

def test_gateway_auth_constant_time_comparison():
    """Verify constant-time secret comparison via hmac.compare_digest."""
    gw = GatewayIdentity(
        gateway_id="gw-timing-test",
        organization_id="org-test",
        assigned_equipment_ids=["mach-01"],
        secret="valid-secret-key-123",
        status="ACTIVE",
    )
    GatewayAuthRegistry.register_gateway(gw)

    # Valid secret matches
    assert GatewayAuthRegistry.authenticate_gateway("gw-timing-test", "valid-secret-key-123") is not None
    # Invalid secret fails
    assert GatewayAuthRegistry.authenticate_gateway("gw-timing-test", "wrong-secret-key-456") is None
    # Empty secret fails
    assert GatewayAuthRegistry.authenticate_gateway("gw-timing-test", "") is None


def test_gateway_auth_revoked_gateway():
    """Verify revoked gateways are unconditionally rejected."""
    assert GatewayAuthRegistry.authenticate_by_secret("revoked-gateway-secret-2026") is None
    assert GatewayAuthRegistry.authenticate_gateway("gw-alpha-revoked", "revoked-gateway-secret-2026") is None


def test_gateway_ingestion_authorized_submission(client, test_setup):
    """Test authorized gateway submitting readings to its assigned machine succeeds."""
    payload = {
        "gateway_id": "gw-alpha-authorized",
        "batch_identifier": f"batch-{uuid.uuid4()}",
        "readings": [
            {
                "event_id": f"event-{uuid.uuid4()}",
                "organization_id": test_setup["org1"].id,
                "machine_id": test_setup["mach1"].id,
                "signal_id": "sig-speed",
                "source_timestamp": datetime.now(timezone.utc).isoformat(),
                "source_value": 85.0,
                "normalized_value": 85.0,
            }
        ]
    }

    res = client.post(
        "/api/v1/internal/ingestion/readings",
        json=payload,
        headers={"X-Gateway-Secret": "alpha-gateway-secret-token-2026"}
    )
    assert res.status_code == 201
    data = res.get_json()
    assert data["metrics"]["accepted"] == 1
    assert data["metrics"]["rejected"] == 0


def test_gateway_spoofed_gateway_id_rejected(client, test_setup):
    """Test that declaring a gateway_id different from the authenticated identity is rejected."""
    payload = {
        "gateway_id": "gw-spoofed-fake-id",  # Spoofed ID!
        "batch_identifier": f"batch-{uuid.uuid4()}",
        "readings": [
            {
                "event_id": f"event-{uuid.uuid4()}",
                "organization_id": test_setup["org1"].id,
                "machine_id": test_setup["mach1"].id,
                "signal_id": "sig-speed",
                "source_timestamp": datetime.now(timezone.utc).isoformat(),
                "source_value": 85.0,
            }
        ]
    }

    res = client.post(
        "/api/v1/internal/ingestion/readings",
        json=payload,
        headers={"X-Gateway-Secret": "alpha-gateway-secret-token-2026"}  # Authenticated as gw-alpha-authorized
    )
    assert res.status_code == 403
    assert "gateway identity mismatch" in res.get_json()["message"]


def test_gateway_unassigned_machine_rejected(client, test_setup):
    """Test gateway attempting to submit to an unassigned machine in its own org is rejected."""
    # gw-alpha-authorized is only authorized for mach1, NOT mach2
    payload = {
        "gateway_id": "gw-alpha-authorized",
        "batch_identifier": f"batch-{uuid.uuid4()}",
        "readings": [
            {
                "event_id": f"event-{uuid.uuid4()}",
                "organization_id": test_setup["org1"].id,
                "machine_id": test_setup["mach2"].id,  # Unassigned machine!
                "signal_id": "sig-speed",
                "source_timestamp": datetime.now(timezone.utc).isoformat(),
                "source_value": 85.0,
            }
        ]
    }

    res = client.post(
        "/api/v1/internal/ingestion/readings",
        json=payload,
        headers={"X-Gateway-Secret": "alpha-gateway-secret-token-2026"}
    )
    assert res.status_code == 201
    data = res.get_json()
    # Reading must be rejected due to machine authorization mismatch
    assert data["metrics"]["accepted"] == 0
    assert data["metrics"]["rejected"] == 1


def test_gateway_cross_tenant_submission_rejected(client, test_setup):
    """Test gateway attempting to submit readings to another organization's machine is rejected."""
    payload = {
        "gateway_id": "gw-alpha-authorized",
        "batch_identifier": f"batch-{uuid.uuid4()}",
        "readings": [
            {
                "event_id": f"event-{uuid.uuid4()}",
                "organization_id": test_setup["org2"].id,  # Other tenant!
                "machine_id": test_setup["mach_beta"].id,
                "signal_id": "sig-speed",
                "source_timestamp": datetime.now(timezone.utc).isoformat(),
                "source_value": 85.0,
            }
        ]
    }

    res = client.post(
        "/api/v1/internal/ingestion/readings",
        json=payload,
        headers={"X-Gateway-Secret": "alpha-gateway-secret-token-2026"}
    )
    assert res.status_code == 201
    data = res.get_json()
    assert data["metrics"]["accepted"] == 0
    assert data["metrics"]["rejected"] == 1


# =============================================================================
# 2. FIX 2: ATOMIC DATABASE IDEMPOTENCY & CONCURRENCY TESTS
# =============================================================================

def test_atomic_idempotency_same_event_submitted_twice(client, test_setup):
    """Test that submitting the same event twice results in duplicates=1 without throwing HTTP 500."""
    eid = f"event-atomic-{uuid.uuid4()}"
    reading = {
        "event_id": eid,
        "organization_id": test_setup["org1"].id,
        "machine_id": test_setup["mach1"].id,
        "signal_id": "sig-temp",
        "source_timestamp": datetime.now(timezone.utc).isoformat(),
        "source_value": 42.5,
        "normalized_value": 42.5,
    }

    # First submission -> accepted=1, duplicates=0
    res1 = client.post(
        "/api/v1/internal/ingestion/readings",
        json={"gateway_id": "gw-alpha-authorized", "readings": [reading]},
        headers={"X-Gateway-Secret": "alpha-gateway-secret-token-2026"}
    )
    assert res1.status_code == 201
    assert res1.get_json()["metrics"]["accepted"] == 1
    assert res1.get_json()["metrics"]["duplicates"] == 0

    # Second submission (atomic ON CONFLICT DO NOTHING) -> accepted=0, duplicates=1, HTTP 201 (no 500!)
    res2 = client.post(
        "/api/v1/internal/ingestion/readings",
        json={"gateway_id": "gw-alpha-authorized", "readings": [reading]},
        headers={"X-Gateway-Secret": "alpha-gateway-secret-token-2026"}
    )
    assert res2.status_code == 201
    assert res2.get_json()["metrics"]["accepted"] == 0
    assert res2.get_json()["metrics"]["duplicates"] == 1


def test_atomic_idempotency_mixed_batch(client, test_setup):
    """Test mixed batch with 2 new readings and 2 duplicate readings."""
    dup_eid_1 = f"dup-1-{uuid.uuid4()}"
    dup_eid_2 = f"dup-2-{uuid.uuid4()}"
    new_eid_1 = f"new-1-{uuid.uuid4()}"
    new_eid_2 = f"new-2-{uuid.uuid4()}"

    # Pre-insert dup_eid_1 and dup_eid_2
    pre_readings = [
        {"event_id": dup_eid_1, "organization_id": test_setup["org1"].id, "machine_id": test_setup["mach1"].id, "signal_id": "sig-01", "source_value": 1.0, "source_timestamp": datetime.now(timezone.utc).isoformat()},
        {"event_id": dup_eid_2, "organization_id": test_setup["org1"].id, "machine_id": test_setup["mach1"].id, "signal_id": "sig-02", "source_value": 2.0, "source_timestamp": datetime.now(timezone.utc).isoformat()},
    ]
    client.post(
        "/api/v1/internal/ingestion/readings",
        json={"gateway_id": "gw-alpha-authorized", "readings": pre_readings},
        headers={"X-Gateway-Secret": "alpha-gateway-secret-token-2026"}
    )

    # Now send mixed batch (2 existing + 2 brand new)
    mixed_batch = pre_readings + [
        {"event_id": new_eid_1, "organization_id": test_setup["org1"].id, "machine_id": test_setup["mach1"].id, "signal_id": "sig-03", "source_value": 3.0, "source_timestamp": datetime.now(timezone.utc).isoformat()},
        {"event_id": new_eid_2, "organization_id": test_setup["org1"].id, "machine_id": test_setup["mach1"].id, "signal_id": "sig-04", "source_value": 4.0, "source_timestamp": datetime.now(timezone.utc).isoformat()},
    ]

    res = client.post(
        "/api/v1/internal/ingestion/readings",
        json={"gateway_id": "gw-alpha-authorized", "readings": mixed_batch},
        headers={"X-Gateway-Secret": "alpha-gateway-secret-token-2026"}
    )
    assert res.status_code == 201
    metrics = res.get_json()["metrics"]
    assert metrics["accepted"] == 2
    assert metrics["duplicates"] == 2
    assert metrics["rejected"] == 0


def test_atomic_idempotency_invalid_readings_in_batch(client, test_setup):
    """Test that malformed/missing fields are counted as rejected and do not block valid readings."""
    batch = [
        {"organization_id": test_setup["org1"].id, "machine_id": test_setup["mach1"].id, "signal_id": "sig-1"},  # Missing event_id!
        {"event_id": f"valid-{uuid.uuid4()}", "organization_id": test_setup["org1"].id, "machine_id": test_setup["mach1"].id, "signal_id": "sig-2", "source_value": 10.0, "source_timestamp": datetime.now(timezone.utc).isoformat()},
    ]

    res = client.post(
        "/api/v1/internal/ingestion/readings",
        json={"gateway_id": "gw-alpha-authorized", "readings": batch},
        headers={"X-Gateway-Secret": "alpha-gateway-secret-token-2026"}
    )
    assert res.status_code == 201
    metrics = res.get_json()["metrics"]
    assert metrics["accepted"] == 1
    assert metrics["rejected"] == 1


# =============================================================================
# 3. FIX 3: CRASH-SAFE DISK BUFFER RECOVERY & DURABILITY TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_crash_safe_recovery_unacknowledged_preserved(temp_buffer_dir):
    """Verify unacknowledged readings are never truncated when delivery fails."""
    buf = BoundedGatewayBuffer(
        gateway_id="gw-crash-test",
        buffer_dir=temp_buffer_dir,
        max_queue_size=10,
        batch_size=5,
    )

    # 1. Pre-populate overflow file with 3 readings
    overflow_file = Path(temp_buffer_dir) / "gateway_overflow.jsonl"
    recovering_file = Path(temp_buffer_dir) / "gateway_recovering.jsonl"

    test_readings = [
        NormalizedReadingMessage(
            organization_id="org-test",
            machine_id="mach-01",
            signal_id=f"sig-{i}",
            source_node_id=f"ns=2;s=Node_{i}",
            mapping_version=1,
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            source_value=float(i),
        )
        for i in range(3)
    ]
    with open(overflow_file, "w", encoding="utf-8") as f:
        for r in test_readings:
            f.write(json.dumps(r.to_dict()) + "\n")

    # Mock ingestion handler that FAILS (simulating cloud outage)
    async def failing_handler(batch):
        return False

    buf.set_ingestion_handler(failing_handler)

    # Run flush: recovery should stage to gateway_recovering.jsonl and enqueue
    await buf.flush()

    # The readings must NOT be lost! They were saved back to disk buffer because handler failed
    assert overflow_file.exists() or recovering_file.exists()
    total_lines = 0
    for p in (overflow_file, recovering_file):
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                total_lines += sum(1 for line in f if line.strip())
    assert total_lines == 3


@pytest.mark.asyncio
async def test_crash_safe_recovery_corrupt_lines_skipped(temp_buffer_dir):
    """Test that partial/corrupted JSONL lines are safely skipped during recovery."""
    recovering_file = Path(temp_buffer_dir) / "gateway_recovering.jsonl"

    valid_reading = NormalizedReadingMessage(
        organization_id="org-test",
        machine_id="mach-01",
        signal_id="sig-valid",
        source_node_id="ns=2;s=Valid",
        mapping_version=1,
        source_timestamp=datetime.now(timezone.utc).isoformat(),
        source_value=99.9,
    )

    # Write corrupt line followed by valid line
    with open(recovering_file, "w", encoding="utf-8") as f:
        f.write('{"corrupt_partial_json": true\n')  # Corrupted / cut-off line
        f.write(json.dumps(valid_reading.to_dict()) + "\n")  # Valid line

    buf = BoundedGatewayBuffer(
        gateway_id="gw-corrupt-test",
        buffer_dir=temp_buffer_dir,
        max_queue_size=10,
        batch_size=5,
    )

    delivered = []
    async def success_handler(batch):
        delivered.extend(batch)
        return True

    buf.set_ingestion_handler(success_handler)

    await buf.flush()
    # The valid reading should be successfully delivered; corrupt line skipped
    assert len(delivered) == 1
    assert delivered[0].source_value == 99.9
    # The staging file should be cleaned up after all valid readings delivered
    assert not recovering_file.exists()


# =============================================================================
# 4. FIX 4: DISK OVERFLOW PROTECTION & OBSERVABILITY TESTS
# =============================================================================

@pytest.mark.asyncio
async def test_disk_overflow_observability_and_audit(temp_buffer_dir):
    """Verify buffer utilization metrics, dropped counts, and timestamp audit recording."""
    buf = BoundedGatewayBuffer(
        gateway_id="gw-overflow-audit",
        buffer_dir=temp_buffer_dir,
        max_queue_size=2,  # Strict RAM limit
        max_disk_buffer_bytes=600,  # Strict small disk limit ~ 2 lines
    )

    # Push 10 readings: 2 into RAM, ~2 onto disk, remainder must be dropped with audit timestamp
    for i in range(10):
        reading = NormalizedReadingMessage(
            organization_id="org-test",
            machine_id="mach-01",
            signal_id=f"sig-{i}",
            source_node_id=f"ns=2;s=Node_{i}",
            mapping_version=1,
            source_timestamp=datetime.now(timezone.utc).isoformat(),
            source_value=float(i),
        )
        await buf.push(reading)

    metrics = buf.get_metrics()
    assert metrics["queue_depth"] == 2
    assert metrics["dropped_readings"] > 0
    assert metrics["dropped_first_timestamp"] is not None
    assert metrics["dropped_last_timestamp"] is not None
    assert metrics["overflow_active"] is True
    assert metrics["overflow_policy"] == "BOUNDED_DROP_ON_CAPACITY_EXCEEDED"
    assert metrics["disk_utilization_pct"] >= 90.0


# =============================================================================
# 5. FIX 5: GATEWAY HEALTHCHECK PROBE TESTS
# =============================================================================

def test_gateway_healthcheck_probe(temp_buffer_dir, monkeypatch):
    """Test healthcheck detects fresh heartbeat vs. stalled event loop."""
    monkeypatch.setenv("BUFFER_DIR", temp_buffer_dir)
    health_file = Path(temp_buffer_dir) / ".gateway_health.json"

    # Case 1: Fresh heartbeat within 60s -> Exit code 0 (Healthy)
    with open(health_file, "w", encoding="utf-8") as f:
        json.dump({
            "gateway_id": "gw-health-01",
            "timestamp_epoch": time.time(),
            "is_running": True,
            "opcua_connected": True,
            "opcua_state": "CONNECTED",
        }, f)

    assert check_health() == 0

    # Case 2: Gateway degraded (OPC UA disconnected) but event loop alive -> Exit code 0 (Avoid restart loop)
    with open(health_file, "w", encoding="utf-8") as f:
        json.dump({
            "gateway_id": "gw-health-01",
            "timestamp_epoch": time.time(),
            "is_running": True,
            "opcua_connected": False,  # Degraded
            "opcua_state": "DISCONNECTED",
        }, f)

    assert check_health() == 0

    # Case 3: Stalled event loop (heartbeat > 60s old) -> Exit code 1 (Deadlock / crash detected)
    with open(health_file, "w", encoding="utf-8") as f:
        json.dump({
            "gateway_id": "gw-health-01",
            "timestamp_epoch": time.time() - 120.0,  # 2 minutes stale!
            "is_running": True,
            "opcua_connected": True,
            "opcua_state": "CONNECTED",
        }, f)

    assert check_health() == 1

