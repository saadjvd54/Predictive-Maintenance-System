#!/usr/bin/env python3
"""
PharmaPredict AI — Edge Gateway Process & Event-Loop Healthcheck
================================================================
Monitors gateway liveness, event loop responsiveness, certificate validity,
and subsystem states. Avoids restart loops during transient factory network drops.
"""

import os
import sys
import json
import time
from pathlib import Path

MAX_HEARTBEAT_AGE_SEC = 60.0
CERT_EXPIRY_WARNING_DAYS = 15


def check_health() -> int:
    """Execute health verification probe.
    
    Returns 0 if healthy/degraded, 1 if fatal/stalled.
    """
    buffer_dir = os.getenv("BUFFER_DIR", "/opt/edge-gateway/data/gateway_buffer")
    health_file = Path(buffer_dir) / ".gateway_health.json"

    if not health_file.exists():
        # Allow grace period during initial container startup (first 30s)
        try:
            uptime_seconds = time.monotonic()
            if uptime_seconds < 30.0:
                print("[Healthcheck] Starting up: health state file not yet created.")
                return 0
        except Exception:
            pass

        print(f"[Healthcheck Error] Health state file not found: {health_file}")
        return 1

    try:
        with open(health_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"[Healthcheck Error] Failed to read health state file: {e}")
        return 1

    # 1. Event Loop Liveness Check (Detect stalled / hung asyncio process)
    timestamp_epoch = data.get("timestamp_epoch", 0.0)
    current_time = time.time()
    heartbeat_age = current_time - timestamp_epoch

    if heartbeat_age > MAX_HEARTBEAT_AGE_SEC:
        print(
            f"[Healthcheck CRITICAL] Gateway event loop stalled! "
            f"Heartbeat age: {heartbeat_age:.1f}s (max allowed: {MAX_HEARTBEAT_AGE_SEC}s). "
            f"Process hung."
        )
        return 1

    # 2. Process Running Flag
    if not data.get("is_running", False):
        print("[Healthcheck Error] Gateway reports is_running=False.")
        return 1

    # 3. Certificate Expiration Warnings
    cert_days = data.get("client_cert_days_remaining")
    if cert_days is not None:
        if cert_days < 0:
            print(f"[Healthcheck CRITICAL] Client certificate is EXPIRED ({abs(cert_days)} days ago)!")
            return 1
        elif cert_days <= CERT_EXPIRY_WARNING_DAYS:
            print(f"[Healthcheck Warning] Client certificate expiring soon: {cert_days} days remaining.")

    # 4. Subsystem Health Diagnostics
    opcua_connected = data.get("opcua_connected", False)
    opcua_state = data.get("opcua_state", "UNKNOWN")
    overflow_active = data.get("overflow_active", False)
    queue_util = data.get("queue_utilization_pct", 0.0)

    if not opcua_connected:
        print(f"[Healthcheck Warning] Gateway running in DEGRADED mode: OPC UA disconnected ({opcua_state}). Retrying...")

    if overflow_active:
        print("[Healthcheck Warning] Gateway running with active DISK BUFFER OVERFLOW.")

    if queue_util > 80.0:
        print(f"[Healthcheck Warning] High queue depth: {queue_util:.1f}% capacity utilized.")

    # Gateway event loop is alive and actively cycling
    print(f"[Healthcheck OK] Gateway '{data.get('gateway_id')}' responsive (age: {heartbeat_age:.1f}s, uptime: {data.get('uptime_sec', 0)}s).")
    return 0


if __name__ == "__main__":
    sys.exit(check_health())
