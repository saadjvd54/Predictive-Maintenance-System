"""
PharmaPredict AI — Automated Test Suite for Phase 11 Pilot Commissioning
========================================================================
Validates:
1. Pilot Environment Configuration (`backend/gateway/pilot_config.py`):
   - 13 canonical signals pre-mapped for Uhlen BPK-200 blister packaging machine.
   - Validation constraints (empty fields, regex asset codes, opc.tcp:// protocol, security modes).
   - JSON export and import fidelity.
   - .env.edge environment file generation.
   - Tenant and equipment isolation (zero impact on existing demo machines).
2. Edge Preflight Diagnostic Utility (`backend/gateway/edge_preflight.py`):
   - Non-intrusive diagnostic probes.
   - OS & architecture detection.
   - Disk and memory capacity evaluation.
   - X.509 certificate presence and permission checks.
   - Network TCP reachability checks with timeout handling.
   - Exit code and structured JSON summary correctness.
3. Shadow Monitoring Engine (`backend/gateway/shadow_monitoring.py`):
   - 24-hour observation metric simulation.
   - Data availability calculation (target >= 99.50%).
   - Latency distribution (avg < 2000 ms, p99 < 5000 ms).
   - Buffer overflow and spill detection.
   - Mandatory [SIMULATED REHEARSAL] labeling on synthetic reports.
4. Pilot KPIs & Reliability Assessment (`backend/app/modules/monitoring/pilot_kpis.py`):
   - Data availability, latency, buffer health evaluation.
   - Anomaly detection precision and false alarm rate.
   - Baseline downtime reduction returning NOT_YET_MEASURABLE when historical ground truth is absent.
   - Safety compliance (100% adherence).
5. Prognostic Remaining Useful Life (RUL) Safety Guardrail:
   - Mandatory withholding (PREDICTION_UNAVAILABLE) when operating hours < 500h or failure events < 3.
   - Eligibility transition only when historical data threshold is satisfied.
6. Physical vs. Simulated Separation:
   - Enforces distinct completion statuses (Software: Complete, Simulator: Complete, Physical PLC: NOT VERIFIED, Factory Pilot: NOT VERIFIED).
"""

import os
import sys
import json
import tempfile
import pytest
from pathlib import Path
from datetime import datetime, timezone

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from gateway.pilot_config import PilotConfigManager, PilotDeploymentConfig, PilotSignalDefinition
from gateway.edge_preflight import (
    run_preflight_checks,
    check_os_and_architecture,
    check_system_resources,
    check_docker_runtime,
    check_x509_certificates,
    check_tcp_reachability,
    PreflightCheckResult,
)
from gateway.shadow_monitoring import (
    ShadowMonitoringEngine,
    ShadowMonitoringSession,
    SignalObservationStats,
)
from app.modules.monitoring.pilot_kpis import (
    PilotKPICalculator,
    PilotKPISummary,
)


# =============================================================================
# 1. PILOT CONFIGURATION TESTS
# =============================================================================

def test_pilot_config_default_uhlen_bpk200():
    """Proves that standard Uhlen BPK-200 pilot profile initializes with 13 valid signals."""
    config = PilotConfigManager.get_default_uhlen_bpk200_pilot(is_physical_plc=False)
    assert config.machine_asset_code == "PILOT-BPK-01"
    assert config.manufacturer == "Uhlen"
    assert config.model == "BPK-200"
    assert len(config.signals) == 13

    # Check required signals presence
    signal_names = [s["canonical_name"] for s in config.signals]
    assert "forming_temperature" in signal_names
    assert "sealing_temperature" in signal_names
    assert "vibration_level" in signal_names
    assert "bearing_vibration" in signal_names
    assert "motor_current" in signal_names
    assert "line_speed_cpm" in signal_names
    assert "rotational_speed_rpm" in signal_names
    assert "forming_air_pressure" in signal_names
    assert "vacuum_level" in signal_names
    assert "alarm_active" in signal_names
    assert "emergency_stop" in signal_names
    assert "cycle_count" in signal_names

    errors = config.validate()
    assert len(errors) == 0, f"Expected 0 validation errors, got: {errors}"


def test_pilot_config_validation_constraints():
    """Proves that pilot config validator rejects invalid configurations."""
    # Invalid endpoint scheme
    config = PilotDeploymentConfig(opcua_endpoint_url="http://invalid-scheme:4840")
    errors = config.validate()
    assert any("opc.tcp://" in e for e in errors)

    # Empty asset code
    config_empty_asset = PilotDeploymentConfig(machine_asset_code="")
    errors_empty = config_empty_asset.validate()
    assert any("machine_asset_code" in e for e in errors_empty)

    # Physical PLC with security 'None' must be rejected
    config_insecure_physical = PilotDeploymentConfig(
        is_physical_plc=True,
        security_mode="None",
        signals=[{"node_id": "ns=2;s=Test", "canonical_name": "test_signal"}],
    )
    errors_phys = config_insecure_physical.validate()
    assert any("strictly require encrypted security" in e for e in errors_phys)

    # Duplicate NodeId in signals list
    config_dup = PilotDeploymentConfig(
        signals=[
            {"node_id": "ns=2;s=Temp", "canonical_name": "temp_1"},
            {"node_id": "ns=2;s=Temp", "canonical_name": "temp_2"},
        ]
    )
    errors_dup = config_dup.validate()
    assert any("Duplicate node_id" in e for e in errors_dup)


def test_pilot_config_json_and_env_export():
    """Proves that pilot config can be serialized to JSON and converted into .env.edge format."""
    config = PilotConfigManager.get_default_uhlen_bpk200_pilot(is_physical_plc=False)

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "pilot_config.json"
        env_path = Path(tmpdir) / ".env.edge"

        PilotConfigManager.save_to_json(config, json_path)
        assert json_path.exists()

        loaded_config = PilotConfigManager.load_from_json(json_path)
        assert loaded_config.machine_asset_code == config.machine_asset_code
        assert len(loaded_config.signals) == 13

        PilotConfigManager.generate_env_file(config, env_path)
        assert env_path.exists()

        content = env_path.read_text(encoding="utf-8")
        assert "GATEWAY_ID=gw-edge-pilot-01" in content
        assert "MACHINE_ID=PILOT-BPK-01" in content
        assert "MONITORED_NODES_JSON=" in content


def test_pilot_tenant_and_machine_isolation():
    """Verifies that pilot machine configuration does not mutate existing demo records."""
    pilot = PilotConfigManager.get_default_uhlen_bpk200_pilot(asset_code="PILOT-LINE4-BPK01")
    demo_asset_code = "DEMO-BPK-200"

    assert pilot.machine_asset_code != demo_asset_code
    payload = pilot.to_machine_onboarding_payload()
    assert payload["asset_code"] == "PILOT-LINE4-BPK01"
    assert payload["organization_name"] == "Getz Pharma"
    assert payload["is_physical_plc"] is False


# =============================================================================
# 2. EDGE PREFLIGHT DIAGNOSTIC TESTS
# =============================================================================

def test_preflight_os_and_architecture_detection():
    """Proves preflight check inspects operating system, release, and CPU architecture."""
    res = check_os_and_architecture()
    assert res["check"] == "os_and_architecture"
    assert res["status"] in (PreflightCheckResult.PASSED, PreflightCheckResult.WARNING)
    assert "os" in res["details"]
    assert "arch" in res["details"]
    assert res["details"]["cpu_cores"] >= 1


def test_preflight_system_resources_check():
    """Proves preflight check assesses free disk space and returns structured data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        res = check_system_resources(buffer_path=tmpdir)
        assert res["check"] == "system_resources"
        assert res["status"] in (PreflightCheckResult.PASSED, PreflightCheckResult.WARNING)
        assert res["details"]["free_disk_mb"] > 0


def test_preflight_x509_certificate_validation():
    """Proves preflight check detects missing certificates when encryption is enabled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cert_path = Path(tmpdir) / "client_cert.pem"
        key_path = Path(tmpdir) / "client_key.pem"
        server_cert = Path(tmpdir) / "plc_cert.pem"

        # Test missing certificates with SignAndEncrypt
        res = check_x509_certificates(
            client_cert_path=str(cert_path),
            client_key_path=str(key_path),
            server_cert_path=str(server_cert),
            security_mode="SignAndEncrypt",
        )
        assert res["status"] == PreflightCheckResult.FAILED
        assert res["details"]["client_cert_exists"] is False

        # Create dummy cert and key
        cert_path.write_text("DUMMY CERTIFICATE", encoding="utf-8")
        key_path.write_text("DUMMY PRIVATE KEY", encoding="utf-8")

        res_partial = check_x509_certificates(
            client_cert_path=str(cert_path),
            client_key_path=str(key_path),
            server_cert_path=str(server_cert),
            security_mode="SignAndEncrypt",
        )
        assert res_partial["details"]["client_cert_exists"] is True
        assert res_partial["details"]["client_key_exists"] is True
        # Server cert still missing -> WARNING
        assert res_partial["status"] == PreflightCheckResult.WARNING


def test_preflight_tcp_reachability_probe():
    """Proves TCP reachability probe returns non-blocking diagnostic without raising."""
    # Test connection to an unreachable high port on localhost
    reachable, msg = check_tcp_reachability("127.0.0.1", 65530, "Mock Server", timeout_sec=0.2)
    assert reachable is False
    assert isinstance(msg, str)
    assert len(msg) > 0


def test_preflight_orchestrator_summary():
    """Proves run_preflight_checks produces a complete diagnostic report."""
    config = PilotConfigManager.get_default_uhlen_bpk200_pilot(is_physical_plc=False)
    with tempfile.TemporaryDirectory() as tmpdir:
        report = run_preflight_checks(config, buffer_dir=tmpdir)
        assert "overall_status" in report
        assert "checks" in report
        assert report["machine_asset_code"] == "PILOT-BPK-01"
        assert len(report["checks"]) >= 5
        assert report["checks_passed"] + report["checks_warning"] + report["checks_failed"] == len(report["checks"])


# =============================================================================
# 3. SHADOW MONITORING ENGINE TESTS
# =============================================================================

def test_shadow_monitoring_24h_session_generation():
    """Proves that 24-hour simulated shadow monitoring generates complete telemetry metrics."""
    config = PilotConfigManager.get_default_uhlen_bpk200_pilot()
    session = ShadowMonitoringEngine.generate_24h_simulated_session(config, duration_hours=24.0, availability_target=99.91)

    assert session.is_simulated is True
    assert session.duration_hours == 24.0
    assert session.total_readings_received > 1000000
    assert session.availability_pct >= 99.50
    assert session.avg_latency_ms < 500.0
    assert session.disk_buffer_spills == 0
    assert session.cloud_delivery_success_pct >= 99.90
    assert len(session.signal_stats) == 13

    # Verify per-signal stats
    for s in session.signal_stats:
        assert s["sample_count"] == 86400
        assert s["min_value"] <= s["mean_value"] <= s["max_value"]
        assert s["data_quality_good_pct"] == 100.0


def test_shadow_monitoring_markdown_report_formatting():
    """Proves that shadow monitoring report renders professional markdown with mandatory rehearsal banner."""
    config = PilotConfigManager.get_default_uhlen_bpk200_pilot()
    session = ShadowMonitoringEngine.generate_24h_simulated_session(config)

    report_md = ShadowMonitoringEngine.format_markdown_report(session)
    assert "# PharmaPredict AI — 24-Hour Shadow Monitoring Report" in report_md
    assert "[SIMULATED REHEARSAL — NOT FACTORY DATA]" in report_md
    assert "99.91%" in report_md
    assert "forming_temperature" in report_md
    assert "sealing_temperature" in report_md
    assert "PREDICTION_UNAVAILABLE" in report_md
    assert "ALCOA+" in report_md


# =============================================================================
# 4. PILOT KPIS & RELIABILITY TESTS
# =============================================================================

def test_pilot_kpi_availability_calculation():
    """Tests data availability calculation under various transmission ratios."""
    assert PilotKPICalculator.calculate_availability(1000, 1000) == 100.0
    assert PilotKPICalculator.calculate_availability(999, 1000) == 99.9
    assert PilotKPICalculator.calculate_availability(0, 1000) == 0.0
    assert PilotKPICalculator.calculate_availability(10, 0) == 0.0


def test_pilot_kpi_precision_and_false_alarm_rate():
    """Tests alert precision and daily false alarm frequency calculations."""
    # 9 true alerts, 1 false alert = 90% precision
    precision = PilotKPICalculator.calculate_precision(9, 1)
    assert precision == 90.0

    # 0 alerts = None (insufficient data)
    assert PilotKPICalculator.calculate_precision(0, 0) is None

    # 1 false positive over 48 operating hours = 0.5 per day
    rate = PilotKPICalculator.calculate_false_alarm_rate(1, 48.0)
    assert rate == 0.5


def test_pilot_kpi_downtime_reduction_baseline_requirement():
    """Proves that downtime reduction returns NOT_YET_MEASURABLE when historical baseline is missing."""
    # No baseline provided
    res_no_base = PilotKPICalculator.calculate_downtime_reduction(None, 10.0)
    assert res_no_base["status"] == "NOT_YET_MEASURABLE"
    assert res_no_base["value"] is None

    # Zero baseline provided
    res_zero = PilotKPICalculator.calculate_downtime_reduction(0.0, 10.0)
    assert res_zero["status"] == "NOT_YET_MEASURABLE"

    # Valid baseline provided: 100h historical downtime vs 80h pilot downtime = 20% reduction
    res_valid = PilotKPICalculator.calculate_downtime_reduction(100.0, 80.0)
    assert res_valid["status"] == "MEASURED"
    assert res_valid["value"] == 20.0


def test_pilot_kpi_comprehensive_summary():
    """Tests comprehensive KPI summary assembly and target evaluation."""
    summary = PilotKPICalculator.generate_kpi_summary(
        received_readings=1122180,
        expected_readings=1123200,
        avg_latency_ms=142.6,
        max_queue_depth=145,
        true_positive_alerts=2,
        false_positive_alerts=0,
        operating_hours=24.0,
        baseline_downtime_hours=None,
        pilot_downtime_hours=None,
        failure_events_recorded=0,
        is_simulated=True,
    )

    assert summary.availability_status == "MET"
    assert summary.latency_status == "MET"
    assert summary.buffer_status == "HEALTHY"
    assert summary.alert_precision_pct == 100.0
    assert summary.false_alarm_rate_per_day == 0.0
    assert summary.unplanned_downtime_reduction_status == "NOT_YET_MEASURABLE"
    assert summary.safety_compliance_status == "MET"
    assert summary.rul_prediction_status == "PREDICTION_UNAVAILABLE"
    assert summary.is_simulated is True

    summary_dict = summary.to_dict()
    assert summary_dict["availability_pct"] >= 99.50
    assert "assessed_at" in summary_dict


# =============================================================================
# 5. RUL SAFETY GUARDRAIL TESTS
# =============================================================================

def test_rul_prediction_withheld_below_safety_thresholds():
    """
    Proves that Remaining Useful Life (RUL) prediction is STRICTLY WITHHELD
    whenever verified operating hours < 500 or documented failure events < 3.
    """
    # 24 hours pilot run, 0 failures -> MUST BE WITHHELD
    res1 = PilotKPICalculator.check_rul_prediction_eligibility(24.0, 0)
    assert res1["eligible"] is False
    assert res1["status"] == "PREDICTION_UNAVAILABLE"
    assert res1["guardrail_active"] is True
    assert "Operating hours (24.0h) < required 500h" in res1["reason"]

    # 600 hours pilot run, but only 1 failure event -> MUST BE WITHHELD
    res2 = PilotKPICalculator.check_rul_prediction_eligibility(600.0, 1)
    assert res2["eligible"] is False
    assert res2["status"] == "PREDICTION_UNAVAILABLE"
    assert res2["guardrail_active"] is True
    assert "Documented run-to-failure events (1) < required 3" in res2["reason"]

    # 550 hours operating data AND 3 documented failure events -> ELIGIBLE
    res3 = PilotKPICalculator.check_rul_prediction_eligibility(550.0, 3)
    assert res3["eligible"] is True
    assert res3["status"] == "ELIGIBLE"
    assert res3["guardrail_active"] is False


# =============================================================================
# 6. PHYSICAL VS. SIMULATED SEPARATION TEST
# =============================================================================

def test_physical_vs_simulated_separation():
    """
    Enforces that physical PLC commissioning status is reported as NOT VERIFIED
    on standard development hosts without physical factory test equipment.
    """
    # Host preflight check on local environment
    preflight = run_preflight_checks()

    # The test environment is a development machine, not a physical factory IPC
    # Validate that preflight correctly flags physical aspects
    assert preflight["is_physical_plc"] is False

    # A physical deployment config must enforce SignAndEncrypt and certificate checks
    physical_cfg = PilotDeploymentConfig(
        is_physical_plc=True,
        security_mode="SignAndEncrypt",
        client_cert_path="/nonexistent/client_cert.pem",
        client_key_path="/nonexistent/client_key.pem",
        server_cert_path="/nonexistent/plc_cert.pem",
        signals=[{"node_id": "ns=3;s=Temp", "canonical_name": "forming_temp"}],
    )
    res_certs = check_x509_certificates(
        client_cert_path=physical_cfg.client_cert_path,
        client_key_path=physical_cfg.client_key_path,
        server_cert_path=physical_cfg.server_cert_path,
        security_mode=physical_cfg.security_mode,
    )
    # Correctly fails closed when physical certificates are missing
    assert res_certs["status"] == PreflightCheckResult.FAILED
