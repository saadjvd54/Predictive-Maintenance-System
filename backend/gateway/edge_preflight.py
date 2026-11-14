"""
PharmaPredict AI — Edge Gateway Preflight Diagnostic Utility
============================================================
Phase 11: Non-intrusive pre-commissioning environment validation.

Performs read-only environmental, network, security, and hardware checks before
launching the edge gateway on an industrial edge computer or IPC.
Strictly non-intrusive: does NOT modify firewall rules, route tables, or PLC tags.
"""

import os
import sys
import json
import time
import socket
import platform
import shutil
import argparse
import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from urllib.parse import urlparse

# Ensure backend directory is importable
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from gateway.pilot_config import PilotConfigManager, PilotDeploymentConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PharmaPredict.EdgePreflight")


# =============================================================================
# PREFLIGHT CHECK DEFINITIONS
# =============================================================================

class PreflightCheckResult:
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"


def check_os_and_architecture() -> Dict[str, Any]:
    """Inspects host OS, platform, and architecture."""
    os_name = platform.system()
    os_release = platform.release()
    os_version = platform.version()
    cpu_arch = platform.machine()
    cpu_count = os.cpu_count() or 1

    status = PreflightCheckResult.PASSED
    messages = []

    # Production targets Linux (Ubuntu, Debian, RedHat, Alpine)
    if os_name.lower() != "linux":
        status = PreflightCheckResult.WARNING
        messages.append(
            f"Host operating system is '{os_name}'. Production factory deployments require an industrial Linux distribution (Ubuntu 22.04 LTS or Debian 12 recommended)."
        )

    # Architecture check: x86_64 / amd64 / aarch64 / arm64
    valid_archs = ["x86_64", "amd64", "aarch64", "arm64", "armv7l"]
    if cpu_arch.lower() not in valid_archs:
        status = PreflightCheckResult.WARNING
        messages.append(f"CPU architecture '{cpu_arch}' is uncommon for industrial edge gateways.")

    if cpu_count < 2:
        status = PreflightCheckResult.WARNING
        messages.append(f"System has only {cpu_count} CPU core(s). Minimum 2 cores recommended for high-frequency telemetry buffering.")

    return {
        "check": "os_and_architecture",
        "status": status,
        "details": {
            "os": os_name,
            "release": os_release,
            "version": os_version,
            "arch": cpu_arch,
            "cpu_cores": cpu_count,
        },
        "messages": messages,
    }


def check_system_resources(buffer_path: str = "./buffer") -> Dict[str, Any]:
    """Inspects available memory and disk space for telemetry buffering."""
    status = PreflightCheckResult.PASSED
    messages = []

    # Disk space check
    p = Path(buffer_path).resolve()
    p.mkdir(parents=True, exist_ok=True)
    total, used, free = shutil.disk_usage(str(p))

    free_mb = free / (1024 * 1024)
    min_disk_mb = 500.0  # 500 MB minimum absolute floor
    rec_disk_mb = 5000.0  # 5 GB recommended

    if free_mb < min_disk_mb:
        status = PreflightCheckResult.FAILED
        messages.append(f"Insufficient disk space in buffer directory ({free_mb:.1f} MB available, minimum {min_disk_mb} MB required).")
    elif free_mb < rec_disk_mb:
        status = PreflightCheckResult.WARNING
        messages.append(f"Free disk space is low ({free_mb:.1f} MB available, {rec_disk_mb} MB recommended for 7-day offline buffer).")

    # RAM estimation (cross-platform check via psutil or /proc/meminfo or fallback)
    ram_mb = 0.0
    try:
        import psutil
        ram_mb = psutil.virtual_memory().total / (1024 * 1024)
    except ImportError:
        # Fallback for Linux /proc/meminfo
        if os.path.exists("/proc/meminfo"):
            try:
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            parts = line.split()
                            ram_mb = float(parts[1]) / 1024.0
                            break
            except Exception:
                pass

    if ram_mb > 0:
        if ram_mb < 512.0:
            status = PreflightCheckResult.FAILED
            messages.append(f"System RAM ({ram_mb:.0f} MB) is below the minimum 512 MB required for async gateway operations.")
        elif ram_mb < 1500.0:
            if status != PreflightCheckResult.FAILED:
                status = PreflightCheckResult.WARNING
            messages.append(f"System RAM ({ram_mb:.0f} MB) is below the 2048 MB recommended.")

    return {
        "check": "system_resources",
        "status": status,
        "details": {
            "buffer_path": str(p),
            "free_disk_mb": round(free_mb, 1),
            "total_disk_mb": round(total / (1024 * 1024), 1),
            "estimated_ram_mb": round(ram_mb, 1) if ram_mb > 0 else "N/A",
        },
        "messages": messages,
    }


def check_docker_runtime() -> Dict[str, Any]:
    """Inspects if Docker daemon / CLI is available on the system."""
    docker_path = shutil.which("docker")
    compose_path = shutil.which("docker-compose")

    if not docker_path:
        return {
            "check": "docker_runtime",
            "status": PreflightCheckResult.WARNING,
            "details": {"docker_available": False, "compose_available": False},
            "messages": [
                "Docker binary not found on PATH. Containerized edge gateway deployment will not be available. Standalone Python / systemd mode will be used."
            ],
        }

    return {
        "check": "docker_runtime",
        "status": PreflightCheckResult.PASSED,
        "details": {
            "docker_available": True,
            "docker_path": docker_path,
            "compose_available": bool(compose_path),
        },
        "messages": [],
    }


def check_x509_certificates(
    client_cert_path: Optional[str] = None,
    client_key_path: Optional[str] = None,
    server_cert_path: Optional[str] = None,
    security_mode: str = "SignAndEncrypt",
) -> Dict[str, Any]:
    """Verifies existence, permissions, and validity of edge gateway X.509 certificates."""
    status = PreflightCheckResult.PASSED
    messages = []
    details: Dict[str, Any] = {
        "security_mode": security_mode,
        "client_cert_exists": False,
        "client_key_exists": False,
        "server_cert_exists": False,
    }

    if security_mode == "None":
        return {
            "check": "x509_certificates",
            "status": PreflightCheckResult.WARNING,
            "details": details,
            "messages": ["OPC UA security_mode is set to 'None'. X.509 certificates will not be enforced. Only acceptable in simulated rehearsal."],
        }

    # Verify Client Certificate
    if client_cert_path and os.path.isfile(client_cert_path):
        details["client_cert_exists"] = True
        details["client_cert_path"] = client_cert_path
    else:
        status = PreflightCheckResult.FAILED
        messages.append(f"Client certificate not found at '{client_cert_path}'. Generate using 'python -m app.modules.connectivity.security'.")

    # Verify Client Private Key
    if client_key_path and os.path.isfile(client_key_path):
        details["client_key_exists"] = True
        details["client_key_path"] = client_key_path
        # On POSIX, check permissions
        if hasattr(os, "stat") and platform.system().lower() == "linux":
            mode = os.stat(client_key_path).st_mode & 0o777
            if mode not in (0o600, 0o400):
                status = PreflightCheckResult.WARNING
                messages.append(f"Client key permissions {oct(mode)} are too open. Should be 0600 or 0400.")
    else:
        status = PreflightCheckResult.FAILED
        messages.append(f"Client private key not found at '{client_key_path}'.")

    # Verify Server / Trusted Certificate
    if server_cert_path and os.path.isfile(server_cert_path):
        details["server_cert_exists"] = True
        details["server_cert_path"] = server_cert_path
    else:
        # In strict pilot mode, server cert must be pre-trusted
        if status != PreflightCheckResult.FAILED:
            status = PreflightCheckResult.WARNING
        messages.append(f"PLC server certificate not found at '{server_cert_path}'. Pre-trust certificate exchange is pending.")

    return {
        "check": "x509_certificates",
        "status": status,
        "details": details,
        "messages": messages,
    }


def check_tcp_reachability(host: str, port: int, label: str, timeout_sec: float = 2.0) -> Tuple[bool, str]:
    """Performs a non-intrusive TCP socket handshake to verify network reachability."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout_sec)
    start = time.time()
    try:
        sock.connect((host, port))
        sock.close()
        elapsed_ms = (time.time() - start) * 1000
        return True, f"Reachable in {elapsed_ms:.1f}ms"
    except socket.timeout:
        return False, f"Connection timed out after {timeout_sec}s"
    except ConnectionRefusedError:
        return False, "Connection refused (port closed or firewall rejection)"
    except socket.gaierror as e:
        return False, f"DNS resolution failed: {e}"
    except Exception as e:
        return False, f"Network error: {str(e)}"


def check_network_connectivity(
    opcua_endpoint_url: str,
    cloud_ingestion_url: str,
) -> Dict[str, Any]:
    """Tests network paths to PLC endpoint and cloud ingestion backend."""
    status = PreflightCheckResult.PASSED
    messages = []
    details: Dict[str, Any] = {}

    # 1. Parse OPC UA Endpoint
    parsed_opc = urlparse(opcua_endpoint_url)
    opc_host = parsed_opc.hostname or "127.0.0.1"
    opc_port = parsed_opc.port or 4840

    opc_reachable, opc_msg = check_tcp_reachability(opc_host, opc_port, "OPC UA Server")
    details["opcua_endpoint"] = {
        "url": opcua_endpoint_url,
        "host": opc_host,
        "port": opc_port,
        "reachable": opc_reachable,
        "diagnostic": opc_msg,
    }

    if not opc_reachable:
        # Non-fatal if simulated or before physical plug-in, but marked as warning/failure
        status = PreflightCheckResult.WARNING
        messages.append(f"OPC UA Server at {opc_host}:{opc_port} is not reachable ({opc_msg}). Ensure OT network cable is connected and PLC firewall permits port {opc_port}.")

    # 2. Parse Cloud Ingestion URL
    parsed_cloud = urlparse(cloud_ingestion_url)
    cloud_host = parsed_cloud.hostname or "127.0.0.1"
    cloud_port = parsed_cloud.port or (443 if parsed_cloud.scheme == "https" else 80)

    cloud_reachable, cloud_msg = check_tcp_reachability(cloud_host, cloud_port, "Cloud Backend")
    details["cloud_endpoint"] = {
        "url": cloud_ingestion_url,
        "host": cloud_host,
        "port": cloud_port,
        "reachable": cloud_reachable,
        "diagnostic": cloud_msg,
    }

    if not cloud_reachable:
        status = PreflightCheckResult.WARNING
        messages.append(f"Cloud Ingestion endpoint at {cloud_host}:{cloud_port} is not reachable ({cloud_msg}). Gateway will rely on local disk buffering until internet connectivity is established.")

    return {
        "check": "network_connectivity",
        "status": status,
        "details": details,
        "messages": messages,
    }


# =============================================================================
# MAIN PREFLIGHT ORCHESTRATOR
# =============================================================================

def run_preflight_checks(
    config: Optional[PilotDeploymentConfig] = None,
    buffer_dir: str = "./data/buffer",
) -> Dict[str, Any]:
    """Executes all preflight diagnostic checks and aggregates results."""
    if config is None:
        config = PilotConfigManager.get_default_uhlen_bpk200_pilot()

    results: List[Dict[str, Any]] = []

    # 1. Config validation
    config_errors = config.validate()
    config_status = PreflightCheckResult.PASSED if not config_errors else PreflightCheckResult.FAILED
    results.append({
        "check": "configuration_validation",
        "status": config_status,
        "details": {"asset_code": config.machine_asset_code, "signals_count": len(config.signals)},
        "messages": config_errors,
    })

    # 2. OS & Architecture
    results.append(check_os_and_architecture())

    # 3. System Resources
    results.append(check_system_resources(buffer_path=buffer_dir))

    # 4. Docker Runtime
    results.append(check_docker_runtime())

    # 5. X.509 Certificates
    results.append(check_x509_certificates(
        client_cert_path=config.client_cert_path,
        client_key_path=config.client_key_path,
        server_cert_path=config.server_cert_path,
        security_mode=config.security_mode,
    ))

    # 6. Network Reachability
    results.append(check_network_connectivity(
        opcua_endpoint_url=config.opcua_endpoint_url,
        cloud_ingestion_url=config.cloud_ingestion_url,
    ))

    # Overall Status Determination
    overall_status = PreflightCheckResult.PASSED
    for r in results:
        if r["status"] == PreflightCheckResult.FAILED:
            overall_status = PreflightCheckResult.FAILED
            break
        elif r["status"] == PreflightCheckResult.WARNING and overall_status != PreflightCheckResult.FAILED:
            overall_status = PreflightCheckResult.WARNING

    summary = {
        "overall_status": overall_status,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime()),
        "machine_asset_code": config.machine_asset_code,
        "is_physical_plc": config.is_physical_plc,
        "checks_passed": sum(1 for r in results if r["status"] == PreflightCheckResult.PASSED),
        "checks_warning": sum(1 for r in results if r["status"] == PreflightCheckResult.WARNING),
        "checks_failed": sum(1 for r in results if r["status"] == PreflightCheckResult.FAILED),
        "checks": results,
    }

    return summary


def main():
    parser = argparse.ArgumentParser(description="PharmaPredict AI Edge Preflight Diagnostic Utility")
    parser.add_argument("--config", type=str, help="Path to pilot_config.json")
    parser.add_argument("--buffer-dir", type=str, default="./data/buffer", help="Path to telemetry buffer directory")
    parser.add_argument("--json", action="store_true", help="Output results in raw JSON format")
    args = parser.parse_args()

    config = None
    if args.config:
        config = PilotConfigManager.load_from_json(args.config)

    report = run_preflight_checks(config, buffer_dir=args.buffer_dir)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("=" * 70)
        print("PHARMAPREDICT AI — EDGE PREFLIGHT DIAGNOSTIC REPORT")
        print("=" * 70)
        print(f"Overall Status:       {report['overall_status']}")
        print(f"Machine Asset Code:   {report['machine_asset_code']}")
        print(f"Physical PLC Flag:    {report['is_physical_plc']}")
        print(f"Timestamp:            {report['timestamp']}")
        print(f"Passed / Warn / Fail: {report['checks_passed']} / {report['checks_warning']} / {report['checks_failed']}")
        print("-" * 70)
        for c in report["checks"]:
            status_tag = f"[{c['status']}]"
            print(f"{status_tag:<12} {c['check']}")
            for msg in c["messages"]:
                print(f"             - {msg}")
        print("=" * 70)

    # Exit code: 0 if passed or warning, 1 if failed
    sys.exit(1 if report["overall_status"] == PreflightCheckResult.FAILED else 0)


if __name__ == "__main__":
    main()
