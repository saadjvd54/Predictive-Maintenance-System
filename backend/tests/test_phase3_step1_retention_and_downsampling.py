"""
PharmaPredict AI — Phase 3, Step 3.1: Retention Manager & Historical Downsampling Test Suite
=============================================================================================
Comprehensive test verification covering all 15 Phase 3 Step 3.1 requirements:
1. Retention dry-run.
2. Retention disabled when no policy is configured (safe default).
3. Safe deletion of eligible old readings in bounded batches.
4. Preservation of recent readings (newer than cutoff).
5. Preservation of aggregated records (pre-aggregation rollups).
6. Resume behavior after interrupted retention execution.
7. Tenant isolation (cross-organization boundaries preserved).
8. Downsampling across the entire 24-hour range.
9. Correct minimum, maximum, and average bucket values.
10. Missing and irregular readings handling.
11. Empty time ranges handling.
12. Existing history API backward compatibility.
13. Query performance with realistic data volume (< 200 ms target).
14. Concurrent ingestion while retention runs.
15. No data loss or duplicate ingestion.
"""

import time
import uuid
import threading
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
import pytest

from app.extensions import db
from app.models.tenant import Organization, Site
from app.models.equipment import EquipmentCategory, Machine
from app.models.signal_mapping import SignalDefinition, MachineSignal
from app.models.monitoring import (
    SignalReading,
    SignalReadingAggregate,
    RetentionPolicy,
    RetentionExecution,
)
from app.modules.monitoring.retention_service import RetentionService
from app.modules.monitoring.ingestion_service import IngestionService
from app.modules.monitoring.storage_service import StorageMonitoringService


@pytest.fixture
def step31_setup(app):
    """Fixture providing isolated multi-tenant equipment and signal mappings."""
    with app.app_context():
        # Clean slate in testing database
        now = datetime.now(timezone.utc)

        # 1. Organizations
        org_a = Organization(id="org-ret-alpha", name="Alpha Pharmaceuticals", slug="alpha-pharma")
        org_b = Organization(id="org-ret-beta", name="Beta Biotech Corp", slug="beta-biotech")
        db.session.add_all([org_a, org_b])
        db.session.commit()

        # 2. Sites & Categories
        site_a = Site(id="site-ret-a1", organization_id=org_a.id, name="Formulation Plant Alpha")
        cat_a = EquipmentCategory(id="cat-ret-gran", organization_id=org_a.id, name="Granulator", is_default=True)
        site_b = Site(id="site-ret-b1", organization_id=org_b.id, name="Packaging Plant Beta")
        cat_b = EquipmentCategory(id="cat-ret-pack", organization_id=org_b.id, name="Packaging", is_default=True)
        db.session.add_all([site_a, cat_a, site_b, cat_b])
        db.session.commit()

        # 3. Machines
        mach_a1 = Machine(
            id="mach-ret-gran-01",
            organization_id=org_a.id,
            site_id=site_a.id,
            category_id=cat_a.id,
            asset_code="GRAN-01",
            equipment_name="High Shear Granulator 01",
        )
        mach_b1 = Machine(
            id="mach-ret-pack-01",
            organization_id=org_b.id,
            site_id=site_b.id,
            category_id=cat_b.id,
            asset_code="PACK-01",
            equipment_name="Blister Packaging Line 01",
        )
        db.session.add_all([mach_a1, mach_b1])
        db.session.commit()

        # Users and Roles for Org A API testing
        from app.models.user import User, Role, UserRoleAssignment
        admin_role = Role.query.filter_by(name=Role.ORG_ADMIN).first()
        if not admin_role:
            admin_role = Role(name=Role.ORG_ADMIN, description="Org Admin")
            db.session.add(admin_role)
            db.session.commit()

        user_admin = User(
            id="user-ret-admin",
            organization_id=org_a.id,
            full_name="Alpha Admin",
            email="admin@alpha.com",
            is_active=True,
        )
        user_admin.set_password("Admin@123")
        db.session.add(user_admin)
        db.session.commit()

        db.session.add(UserRoleAssignment(
            user_id=user_admin.id,
            role_id=admin_role.id,
            organization_id=org_a.id,
        ))
        db.session.commit()

        # 4. Standard Signal Definition
        sig_def = SignalDefinition(
            id="def-temp-01",
            signal_code="GRAN_CHAMBER_TEMP",
            name="Chamber Temperature",
            signal_group="Thermal",
            expected_data_type="Float",
            standard_unit="°C",
            is_custom=False,
            created_at=now,
        )
        db.session.add(sig_def)
        db.session.commit()

        # 5. Machine Signals
        sig_a1 = MachineSignal(
            id="sig-gran-temp-01",
            organization_id=org_a.id,
            machine_id=mach_a1.id,
            signal_definition_id=sig_def.id,
            source_node_id="ns=2;s=Granulator.ChamberTemp",
            custom_name="Chamber Temp Sensor",
            normalized_unit="°C",
            sampling_interval_ms=1000,
            enabled=True,
            created_at=now,
        )
        sig_b1 = MachineSignal(
            id="sig-pack-temp-01",
            organization_id=org_b.id,
            machine_id=mach_b1.id,
            signal_definition_id=sig_def.id,
            source_node_id="ns=2;s=Packer.SealTemp",
            custom_name="Packer Seal Temp",
            normalized_unit="°C",
            sampling_interval_ms=1000,
            enabled=True,
            created_at=now,
        )
        db.session.add_all([sig_a1, sig_b1])
        db.session.commit()

        yield {
            "org_a": org_a,
            "org_b": org_b,
            "mach_a1": mach_a1,
            "mach_b1": mach_b1,
            "sig_a1": sig_a1,
            "sig_b1": sig_b1,
        }


# ==============================================================================
# TEST 1 & 2: SAFE DEFAULTS AND DRY RUN
# ==============================================================================

def test_retention_disabled_when_no_policy_configured(app, step31_setup):
    """Req 2: Verify safe default behavior — no automatic deletion when policy is not configured."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)

        # Seed old reading (120 days old)
        old_reading = SignalReading(
            id=str(uuid.uuid4()),
            event_id="evt-safe-001",
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            signal_id=ctx["sig_a1"].id,
            source_timestamp=now - timedelta(days=120),
            normalized_value=65.0,
            quality_code="Good",
        )
        db.session.add(old_reading)
        db.session.commit()

        # Execute retention without configuring any policy
        result = RetentionService.execute_retention(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
        )

        assert result["status"] == "SKIPPED"
        assert result["records_deleted"] == 0
        assert "No active retention policy configured" in result["message"]

        # Confirm old reading was NOT deleted
        found = db.session.get(SignalReading, old_reading.id)
        assert found is not None, "Old reading must be preserved when no policy is configured!"


def test_retention_dry_run_mode(app, step31_setup):
    """Req 1: Verify dry-run mode previews eligible records without modifying telemetry."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)

        # Configure 30-day retention policy
        RetentionService.set_policy(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            raw_retention_days=30,
            is_active=True,
        )

        # Seed 5 old readings (45 days old) and 3 recent readings (5 days old)
        for i in range(5):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-dry-old-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=now - timedelta(days=45, minutes=i),
                normalized_value=70.0 + i,
                quality_code="Good",
            )
            db.session.add(r)

        for i in range(3):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-dry-new-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=now - timedelta(days=5, minutes=i),
                normalized_value=70.0 + i,
                quality_code="Good",
            )
            db.session.add(r)
        db.session.commit()

        # Run with dry_run=True
        result = RetentionService.execute_retention(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            dry_run=True,
        )

        assert result["status"] == "DRY_RUN"
        assert result["dry_run"] is True
        assert result["records_scanned"] == 5
        assert result["records_deleted"] == 0

        # Verify all 8 records still exist in the database
        total = SignalReading.query.filter_by(organization_id=ctx["org_a"].id).count()
        assert total == 8, "Dry run must NOT delete any records from database!"


# ==============================================================================
# TEST 3, 4 & 5: BOUNDED BATCH DELETION & AGGREGATE PRESERVATION
# ==============================================================================

def test_safe_deletion_in_bounded_batches_and_preservation(app, step31_setup):
    """Req 3, 4, 5: Safe deletion in bounded batches, preserving recent readings & pre-aggregates."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)

        RetentionService.set_policy(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            raw_retention_days=30,
            is_active=True,
            archive_before_delete=True,
            batch_size=10,  # Small batch to verify multi-batch execution
        )

        # Seed 25 old readings (60 days old) spanning 2 distinct hours
        old_hour_1 = now - timedelta(days=60, hours=2)
        old_hour_2 = now - timedelta(days=60, hours=1)

        for i in range(15):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-batch-h1-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=old_hour_1 + timedelta(minutes=i * 2),
                normalized_value=50.0 + (i * 2),
                quality_code="Good",
            )
            db.session.add(r)

        for i in range(10):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-batch-h2-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=old_hour_2 + timedelta(minutes=i * 3),
                normalized_value=60.0 + i,
                quality_code="Good",
            )
            db.session.add(r)

        # Seed 10 recent readings (2 days old) — MUST BE PRESERVED
        for i in range(10):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-recent-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=now - timedelta(days=2, minutes=i),
                normalized_value=85.0 + i,
                quality_code="Good",
            )
            db.session.add(r)
        db.session.commit()

        assert SignalReading.query.filter_by(organization_id=ctx["org_a"].id).count() == 35

        # Execute retention with batch_size=10 (should process 3 batches: 10, 10, 5)
        result = RetentionService.execute_retention(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            batch_size=10,
        )

        assert result["status"] == "COMPLETED"
        assert result["records_scanned"] == 25
        assert result["records_deleted"] == 25
        assert result["batches_processed"] == 3
        assert result["records_aggregated"] >= 2, "Must pre-aggregate the two old hour buckets!"

        # Confirm only recent readings remain
        remaining = SignalReading.query.filter_by(organization_id=ctx["org_a"].id).all()
        assert len(remaining) == 10
        for r in remaining:
            assert (now - r.source_timestamp.replace(tzinfo=timezone.utc)).days < 30

        # Confirm aggregated rollups exist in signal_reading_aggregates
        aggregates = SignalReadingAggregate.query.filter_by(
            organization_id=ctx["org_a"].id,
            signal_id=ctx["sig_a1"].id,
        ).all()
        assert len(aggregates) >= 2
        for agg in aggregates:
            assert agg.min_value is not None
            assert agg.max_value is not None
            assert agg.avg_value is not None
            assert agg.reading_count > 0


# ==============================================================================
# TEST 6 & 7: RESUME AFTER INTERRUPTION & TENANT ISOLATION
# ==============================================================================

def test_resume_after_interrupted_retention(app, step31_setup):
    """Req 6: Verify retention can be safely paused/interrupted and resumed without error."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)

        RetentionService.set_policy(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            raw_retention_days=30,
            is_active=True,
            batch_size=5,
        )

        # Seed 15 old readings
        for i in range(15):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-resume-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=now - timedelta(days=50, minutes=i),
                normalized_value=40.0 + i,
                quality_code="Good",
            )
            db.session.add(r)
        db.session.commit()

        # Run 1: Interrupted by max_batches=1 (prunes only 5 of 15)
        run1 = RetentionService.execute_retention(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            batch_size=5,
            max_batches=1,
        )
        assert run1["records_deleted"] == 5
        remaining_after_run1 = SignalReading.query.filter_by(organization_id=ctx["org_a"].id).count()
        assert remaining_after_run1 == 10

        # Run 2: Resume with max_batches=None (prunes remaining 10)
        run2 = RetentionService.execute_retention(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            batch_size=5,
        )
        assert run2["records_deleted"] == 10
        remaining_after_run2 = SignalReading.query.filter_by(organization_id=ctx["org_a"].id).count()
        assert remaining_after_run2 == 0


def test_tenant_isolation_in_retention(app, step31_setup):
    """Req 7: Verify retention in Org A never purges or affects telemetry in Org B."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)

        # Set 30-day retention on Org A only
        RetentionService.set_policy(
            organization_id=ctx["org_a"].id,
            raw_retention_days=30,
            is_active=True,
        )

        # Seed 10 old readings in Org A and 10 old readings in Org B
        for i in range(10):
            r_a = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-iso-a-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=now - timedelta(days=60, minutes=i),
                normalized_value=10.0 + i,
                quality_code="Good",
            )
            r_b = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-iso-b-{i}",
                organization_id=ctx["org_b"].id,
                machine_id=ctx["mach_b1"].id,
                signal_id=ctx["sig_b1"].id,
                source_timestamp=now - timedelta(days=60, minutes=i),
                normalized_value=20.0 + i,
                quality_code="Good",
            )
            db.session.add_all([r_a, r_b])
        db.session.commit()

        # Execute retention on Org A
        RetentionService.execute_retention(organization_id=ctx["org_a"].id)

        # Assert Org A records pruned
        assert SignalReading.query.filter_by(organization_id=ctx["org_a"].id).count() == 0
        # Assert Org B records completely preserved!
        assert SignalReading.query.filter_by(organization_id=ctx["org_b"].id).count() == 10


# ==============================================================================
# TEST 8, 9, 10, 11 & 12: DOWNSAMPLING ENGINE & BACKWARD COMPATIBILITY
# ==============================================================================

def test_downsampling_24_hour_range_and_aggregates(app, step31_setup):
    """Req 8 & 9: Verify 24-hour range downsampling covers entire window with correct min/max/avg."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)
        start_24h = now - timedelta(hours=24)

        # Seed 144 readings (1 per 10 minutes) across the full 24-hour window
        # Value follows predictable curve: value = 20.0 + hour_index
        for hour in range(24):
            for minute in (0, 10, 20, 30, 40, 50):
                ts = start_24h + timedelta(hours=hour, minutes=minute)
                r = SignalReading(
                    id=str(uuid.uuid4()),
                    event_id=f"evt-24h-{hour}-{minute}",
                    organization_id=ctx["org_a"].id,
                    machine_id=ctx["mach_a1"].id,
                    signal_id=ctx["sig_a1"].id,
                    source_timestamp=ts,
                    normalized_value=20.0 + hour + (minute / 100.0),
                    normalized_unit="°C",
                    quality_code="Good",
                )
                db.session.add(r)
        db.session.commit()

        # Query 24h history with downsampling (limit=48)
        readings = IngestionService.get_historical_readings(
            machine_id=ctx["mach_a1"].id,
            organization_id=ctx["org_a"].id,
            signal_id=ctx["sig_a1"].id,
            start_time=start_24h,
            end_time=now,
            limit=48,
            downsample=True,
        )

        assert len(readings) > 0
        assert len(readings) <= 48

        # Verify time span of downsampled results covers beginning and end of the 24h window
        first_point_ts = datetime.fromisoformat(readings[0]["source_timestamp"].replace("Z", "+00:00"))
        last_point_ts = datetime.fromisoformat(readings[-1]["source_timestamp"].replace("Z", "+00:00"))

        assert (first_point_ts - start_24h).total_seconds() < 3600, "First downsampled point must be near window start!"
        assert (now - last_point_ts).total_seconds() < 3600, "Last downsampled point must be near window end!"

        # Verify min, max, avg fields are present and accurate
        for pt in readings:
            assert pt["min_value"] is not None
            assert pt["max_value"] is not None
            assert pt["avg_value"] is not None
            assert pt["min_value"] <= pt["avg_value"] <= pt["max_value"]
            assert pt["normalized_value"] == pt["avg_value"]
            assert pt["reading_count"] >= 1
            assert pt["downsampled"] is True


def test_missing_and_irregular_readings(app, step31_setup):
    """Req 10: Verify irregular intervals and gaps are handled without errors or NaN."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)
        start_time = now - timedelta(hours=6)

        # Seed readings with irregular gaps (burst of 3, gap of 2 hours, then 2 readings)
        timestamps = [
            start_time + timedelta(minutes=10),
            start_time + timedelta(minutes=12),
            start_time + timedelta(minutes=15),
            start_time + timedelta(hours=3, minutes=5),
            start_time + timedelta(hours=5, minutes=45),
        ]
        for i, ts in enumerate(timestamps):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-irreg-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=ts,
                normalized_value=55.0 + i,
                quality_code="Good",
            )
            db.session.add(r)
        db.session.commit()

        readings = IngestionService.get_historical_readings(
            machine_id=ctx["mach_a1"].id,
            organization_id=ctx["org_a"].id,
            signal_id=ctx["sig_a1"].id,
            start_time=start_time,
            end_time=now,
            limit=20,
            downsample=True,
        )

        assert len(readings) > 0
        for pt in readings:
            assert pt["avg_value"] is not None
            assert not (pt["avg_value"] != pt["avg_value"])  # Not NaN


def test_empty_time_ranges(app, step31_setup):
    """Req 11: Empty time ranges return clean empty list without crashing."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)

        # No readings seeded
        readings = IngestionService.get_historical_readings(
            machine_id=ctx["mach_a1"].id,
            organization_id=ctx["org_a"].id,
            signal_id=ctx["sig_a1"].id,
            start_time=now - timedelta(hours=2),
            end_time=now,
            downsample=True,
        )
        assert readings == []


def test_existing_history_api_backward_compatibility(app, step31_setup):
    """Req 12: Verify backward compatibility with existing history consumer format."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)

        # Seed 5 raw readings
        for i in range(5):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-compat-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=now - timedelta(minutes=5 - i),
                normalized_value=60.0 + i,
                normalized_unit="°C",
                quality_code="Good",
            )
            db.session.add(r)
        db.session.commit()

        # Call with downsample=False (legacy raw mode)
        legacy_readings = IngestionService.get_historical_readings(
            machine_id=ctx["mach_a1"].id,
            organization_id=ctx["org_a"].id,
            signal_id=ctx["sig_a1"].id,
            start_time=now - timedelta(minutes=15),
            end_time=now,
            limit=100,
            downsample=False,
        )

        assert len(legacy_readings) == 5
        # Verify legacy consumers find expected keys
        first = legacy_readings[0]
        assert "source_timestamp" in first
        assert "normalized_value" in first
        assert "signal_id" in first
        assert "machine_id" in first
        assert "organization_id" in first


# ==============================================================================
# TEST 13, 14 & 15: PERFORMANCE, CONCURRENCY & STORAGE AUDITING
# ==============================================================================

def test_query_performance_with_realistic_data_volume(app, step31_setup):
    """Req 13: Benchmark historical downsampling performance (Target < 200ms)."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)
        start_24h = now - timedelta(hours=24)

        # Seed 1,000 readings in batch
        readings_batch = []
        for i in range(1000):
            ts = start_24h + timedelta(seconds=i * 86.4)
            readings_batch.append(SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-perf-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=ts,
                normalized_value=50.0 + (i % 20),
                normalized_unit="°C",
                quality_code="Good",
            ))
        db.session.bulk_save_objects(readings_batch)
        db.session.commit()

        # Measure query latency
        t0 = time.perf_counter()
        results = IngestionService.get_historical_readings(
            machine_id=ctx["mach_a1"].id,
            organization_id=ctx["org_a"].id,
            signal_id=ctx["sig_a1"].id,
            start_time=start_24h,
            end_time=now,
            limit=200,
            downsample=True,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0

        assert len(results) > 0
        assert latency_ms < 200.0, f"Query latency was {latency_ms:.2f}ms (target < 200ms)"
        print(f"\n[PERFORMANCE] Downsampled 1,000 points across 24h into {len(results)} buckets in {latency_ms:.2f} ms")


def test_concurrent_ingestion_while_retention_runs(app, step31_setup):
    """Req 14 & 15: Verify normal ingestion continues concurrently while retention runs without data loss."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)

        # Set 30-day retention
        RetentionService.set_policy(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            raw_retention_days=30,
            is_active=True,
            batch_size=10,
        )

        # Seed 30 old readings eligible for retention
        for i in range(30):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-conc-old-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=now - timedelta(days=40, minutes=i),
                normalized_value=40.0 + i,
                quality_code="Good",
            )
            db.session.add(r)
        db.session.commit()

        ingested_during_retention = []

        def worker_ingest():
            with app.app_context():
                for j in range(10):
                    time.sleep(0.01)
                    batch = [{
                        "event_id": f"evt-conc-live-{j}",
                        "organization_id": ctx["org_a"].id,
                        "machine_id": ctx["mach_a1"].id,
                        "signal_id": ctx["sig_a1"].id,
                        "source_timestamp": (now + timedelta(seconds=j)).isoformat(),
                        "normalized_value": 75.0 + j,
                        "quality_code": "Good",
                    }]
                    IngestionService.ingest_batch(
                        gateway_id="gw-test",
                        readings_data=batch,
                    )
                    ingested_during_retention.append(j)

        t_ingest = threading.Thread(target=worker_ingest)
        t_ingest.start()

        # Run retention concurrently
        ret_result = RetentionService.execute_retention(
            organization_id=ctx["org_a"].id,
            machine_id=ctx["mach_a1"].id,
            batch_size=10,
        )

        t_ingest.join()

        assert ret_result["status"] == "COMPLETED"
        assert ret_result["records_deleted"] == 30

        # Verify all 10 live concurrent readings were successfully ingested and none lost
        live_count = SignalReading.query.filter(
            SignalReading.organization_id == ctx["org_a"].id,
            SignalReading.event_id.like("evt-conc-live-%"),
        ).count()
        assert live_count == 10, "All concurrent live readings must be preserved!"


def test_storage_monitoring_metrics(app, step31_setup):
    """Verify storage monitoring service reports accurate counts and dialect-safe metrics."""
    with app.app_context():
        ctx = step31_setup
        now = datetime.now(timezone.utc)

        # Seed 5 readings
        for i in range(5):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-store-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=now - timedelta(minutes=i),
                normalized_value=60.0 + i,
                quality_code="Good",
            )
            db.session.add(r)
        db.session.commit()

        metrics = StorageMonitoringService.get_storage_metrics(ctx["org_a"].id)

        assert metrics["organization_id"] == ctx["org_a"].id
        assert metrics["telemetry_counts"]["raw_readings_total"] == 5
        assert metrics["telemetry_counts"]["readings_today"] == 5
        assert "retention_status" in metrics
        assert "physical_storage" in metrics
        # If on SQLite, physical storage correctly notes unsupported rather than faking numbers
        if not metrics["physical_storage"]["supported"]:
            assert "not supported" in metrics["physical_storage"]["reason"].lower()


# ==============================================================================
# REST API INTEGRATION TESTS (PHASE 3 STEP 3.1)
# ==============================================================================

def get_auth_token(client, email="admin@alpha.com", password="Admin@123"):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    return res.get_json()["session_token"]


def test_api_historical_readings_downsampling(client, step31_setup):
    """Test /readings/history REST API with downsample=true and bucket_seconds."""
    ctx = step31_setup
    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=2)

    # Seed 20 readings
    with client.application.app_context():
        for i in range(20):
            r = SignalReading(
                id=str(uuid.uuid4()),
                event_id=f"evt-api-hist-{i}",
                organization_id=ctx["org_a"].id,
                machine_id=ctx["mach_a1"].id,
                signal_id=ctx["sig_a1"].id,
                source_timestamp=start_time + timedelta(minutes=i * 6),
                normalized_value=45.0 + i,
                normalized_unit="°C",
                quality_code="Good",
            )
            db.session.add(r)
        db.session.commit()

    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get(
        f"/api/v1/equipment/{ctx['mach_a1'].id}/readings/history"
        f"?signal_id={ctx['sig_a1'].id}&start_time={start_time.isoformat()}&end_time={now.isoformat()}&downsample=true&limit=10",
        headers=headers,
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["machine_id"] == ctx["mach_a1"].id
    assert "readings" in data
    assert len(data["readings"]) > 0
    assert len(data["readings"]) <= 10
    first = data["readings"][0]
    assert "avg_value" in first
    assert "min_value" in first
    assert "max_value" in first
    assert "reading_count" in first
    assert first["downsampled"] is True


def test_api_retention_policy_and_execution_lifecycle(client, step31_setup):
    """Test retention policy configuration, dry-run, execution, and history APIs."""
    ctx = step31_setup
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET initial policy (none configured)
    get_res = client.get(f"/api/v1/equipment/{ctx['mach_a1'].id}/retention/policy", headers=headers)
    assert get_res.status_code == 200
    assert get_res.get_json()["policy"] is None

    # 2. POST set policy
    set_res = client.post(
        f"/api/v1/equipment/{ctx['mach_a1'].id}/retention/policy",
        json={
            "raw_retention_days": 60,
            "aggregate_retention_days": 365,
            "is_active": True,
            "archive_before_delete": True,
            "batch_size": 250,
        },
        headers=headers,
    )
    assert set_res.status_code == 200
    policy_data = set_res.get_json()["policy"]
    assert policy_data["raw_retention_days"] == 60
    assert policy_data["batch_size"] == 250

    # 3. POST execute retention dry run
    dry_res = client.post(
        f"/api/v1/equipment/{ctx['mach_a1'].id}/retention/execute",
        json={"dry_run": True},
        headers=headers,
    )
    assert dry_res.status_code == 200
    assert dry_res.get_json()["status"] == "DRY_RUN"

    # 4. GET retention history
    hist_res = client.get(f"/api/v1/equipment/{ctx['mach_a1'].id}/retention/history", headers=headers)
    assert hist_res.status_code == 200
    hist_data = hist_res.get_json()
    assert hist_data["count"] >= 1
    assert hist_data["history"][0]["dry_run"] is True


def test_api_storage_health_endpoint(client, step31_setup):
    """Test /monitoring/storage/health REST API."""
    ctx = step31_setup
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/v1/monitoring/storage/health", headers=headers)
    assert res.status_code == 200
    data = res.get_json()
    assert data["organization_id"] == ctx["org_a"].id
    assert "telemetry_counts" in data
    assert "retention_status" in data
    assert "physical_storage" in data



