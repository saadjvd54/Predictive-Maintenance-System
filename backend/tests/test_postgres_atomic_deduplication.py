"""
PharmaPredict AI — PostgreSQL Native Atomic Deduplication Verification
======================================================================
Tests native PostgreSQL ON CONFLICT (event_id) DO NOTHING against a real
isolated PostgreSQL database to guarantee race condition immunity and
accurate inserted vs duplicate accounting.
"""

import os
import uuid
import pytest
import dotenv
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import create_engine, Table, Column, String, Float, MetaData, text
from sqlalchemy.dialects.postgresql import insert as pg_insert


@pytest.fixture(scope="module")
def postgres_engine():
    """Establish connection to real PostgreSQL database from environment / .env.local."""
    env_vals = dotenv.dotenv_values(".env.local")
    db_url = os.getenv("DATABASE_URL_UNPOOLED") or os.getenv("DATABASE_URL") or env_vals.get("DATABASE_URL_UNPOOLED") or env_vals.get("DATABASE_URL")
    
    if not db_url:
        pytest.skip("No PostgreSQL DATABASE_URL found for real PostgreSQL verification.")
        
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            # Verify it's actually PostgreSQL
            if engine.dialect.name != "postgresql":
                pytest.skip(f"Target database is {engine.dialect.name}, not PostgreSQL.")
            version_row = conn.execute(text("SELECT version()")).fetchone()
            print(f"\n[Real PostgreSQL Connected]: {version_row[0][:60]}")
        return engine
    except Exception as exc:
        pytest.skip(f"Could not connect to PostgreSQL instance: {exc}")


@pytest.fixture(scope="module")
def isolated_dedup_table(postgres_engine):
    """Create an isolated temporary table for deduplication testing and tear it down cleanly."""
    table_name = f"_test_dedup_{uuid.uuid4().hex[:8]}"
    metadata = MetaData()
    test_table = Table(
        table_name,
        metadata,
        Column("id", String(36), primary_key=True),
        Column("event_id", String(128), unique=True, nullable=False),
        Column("val", Float, nullable=True),
    )
    
    # Create table
    test_table.create(postgres_engine)
    
    try:
        yield test_table
    finally:
        # Tear down test table completely
        test_table.drop(postgres_engine, checkfirst=True)


def test_postgres_atomic_insert_new_records(postgres_engine, isolated_dedup_table):
    """Verify that new distinct event IDs insert cleanly and return exact rowcount."""
    records = [
        {"id": str(uuid.uuid4()), "event_id": f"evt-pg-01-{uuid.uuid4().hex[:6]}", "val": 23.4},
        {"id": str(uuid.uuid4()), "event_id": f"evt-pg-02-{uuid.uuid4().hex[:6]}", "val": 45.6},
    ]
    
    stmt = pg_insert(isolated_dedup_table).values(records)
    stmt = stmt.on_conflict_do_nothing(index_elements=["event_id"])
    
    with postgres_engine.connect() as conn:
        result = conn.execute(stmt)
        conn.commit()
        assert result.rowcount == 2, f"Expected 2 rows inserted, got {result.rowcount}"


def test_postgres_atomic_duplicate_records_ignored_without_error(postgres_engine, isolated_dedup_table):
    """Verify that re-inserting identical event IDs is ignored without IntegrityError and returns rowcount == 0."""
    same_event_id = f"evt-duplicate-{uuid.uuid4().hex[:6]}"
    record_initial = {"id": str(uuid.uuid4()), "event_id": same_event_id, "val": 100.0}
    
    stmt1 = pg_insert(isolated_dedup_table).values([record_initial])
    stmt1 = stmt1.on_conflict_do_nothing(index_elements=["event_id"])
    
    with postgres_engine.connect() as conn:
        res1 = conn.execute(stmt1)
        conn.commit()
        assert res1.rowcount == 1
        
        # Second insert with exact same event_id
        record_duplicate = {"id": str(uuid.uuid4()), "event_id": same_event_id, "val": 999.0}
        stmt2 = pg_insert(isolated_dedup_table).values([record_duplicate])
        stmt2 = stmt2.on_conflict_do_nothing(index_elements=["event_id"])
        
        res2 = conn.execute(stmt2)
        conn.commit()
        # MUST return rowcount == 0 and NOT crash
        assert res2.rowcount == 0
        
        # Verify original value was preserved (atomic DO NOTHING)
        row = conn.execute(
            text(f"SELECT val FROM {isolated_dedup_table.name} WHERE event_id = :eid"),
            {"eid": same_event_id}
        ).fetchone()
        assert row[0] == 100.0


def test_postgres_partial_batch_deduplication(postgres_engine, isolated_dedup_table):
    """Verify mixed batch with 1 existing event_id and 1 new event_id."""
    existing_event = f"evt-existing-{uuid.uuid4().hex[:6]}"
    new_event = f"evt-new-{uuid.uuid4().hex[:6]}"
    
    # Pre-insert existing_event
    with postgres_engine.connect() as conn:
        conn.execute(
            pg_insert(isolated_dedup_table)
            .values([{"id": str(uuid.uuid4()), "event_id": existing_event, "val": 10.0}])
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        conn.commit()
        
        # Now submit mixed batch
        batch = [
            {"id": str(uuid.uuid4()), "event_id": existing_event, "val": 20.0},
            {"id": str(uuid.uuid4()), "event_id": new_event, "val": 30.0},
        ]
        result = conn.execute(
            pg_insert(isolated_dedup_table)
            .values(batch)
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        conn.commit()
        
        # 1 new row inserted, 1 duplicate ignored
        assert result.rowcount == 1


def test_postgres_concurrent_duplicate_race_condition(postgres_engine, isolated_dedup_table):
    """Verify that two concurrent worker threads attempting to insert the exact same event_id simultaneously
    both succeed without 500/IntegrityError, with exactly one insert taking effect."""
    race_event_id = f"evt-race-{uuid.uuid4().hex[:8]}"
    
    def insert_worker(worker_id):
        engine = postgres_engine
        stmt = (
            pg_insert(isolated_dedup_table)
            .values([{"id": str(uuid.uuid4()), "event_id": race_event_id, "val": float(worker_id)}])
            .on_conflict_do_nothing(index_elements=["event_id"])
        )
        with engine.connect() as conn:
            res = conn.execute(stmt)
            conn.commit()
            return res.rowcount
            
    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(insert_worker, 1)
        f2 = executor.submit(insert_worker, 2)
        r1 = f1.result()
        r2 = f2.result()
        
    # Exactly one thread inserted the row, the other was safely ignored
    assert (r1 + r2) == 1, f"Expected total 1 insert across concurrent workers, got r1={r1}, r2={r2}"
    
    # Confirm exactly 1 record exists in the table
    with postgres_engine.connect() as conn:
        count = conn.execute(
            text(f"SELECT COUNT(*) FROM {isolated_dedup_table.name} WHERE event_id = :eid"),
            {"eid": race_event_id}
        ).scalar()
        assert count == 1

