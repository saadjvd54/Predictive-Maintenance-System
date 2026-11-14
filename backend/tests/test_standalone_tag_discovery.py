"""
Automated Test Suite for Standalone OPC UA PLC Tag Discovery Utility (Phase 8)
==============================================================================
Validates:
1. Signal classification across all 11 industrial telemetry categories.
2. Tokenization and negative context handling (anti-false-positive guards).
3. JSON template generation matching PharmaPredict AI canonical schema.
4. Strictly read-only enforcement (proves write operations are prevented).
5. Security downgrade rejection and certificate error handling.
6. Connection failure handling against unreachable endpoints.
7. Full recursive discovery against live PharmaOPCUASimulator (13/13 signals).
"""

import os
import sys
import json
import asyncio
import pytest
import pytest_asyncio
from pathlib import Path

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.modules.connectivity.simulator import PharmaOPCUASimulator
from gateway.tag_discovery import (
    TagDiscoveryConfig,
    OPCUATagDiscovery,
    SignalClassifier,
    SignalClassificationCategory,
    ClassificationResult,
    ReadOnlyViolationError,
    SecurityDowngradeError,
    ConnectionFailedError,
    DiscoveryError,
)


# =============================================================================
# 1. FIXTURES
# =============================================================================

@pytest_asyncio.fixture
async def standalone_simulator():
    """Start an isolated OPC UA simulator with pharmaceutical address space on port 48435."""
    simulator = PharmaOPCUASimulator(port=48435, enable_security=False)
    await simulator.start()
    yield simulator
    await simulator.stop()


# =============================================================================
# 2. UNIT TESTS: SIGNAL CLASSIFIER (11 CATEGORIES & TOKENIZATION)
# =============================================================================

def test_classifier_temperature():
    res = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
        browse_name="2:SealingTemperature",
        display_name="SealingTemperature",
        data_type="Double",
        unit="°C"
    )
    assert res.category == SignalClassificationCategory.TEMPERATURE
    assert res.suggested_signal_code == "SEALING_TEMPERATURE"
    assert res.confidence_level == "HIGH"
    assert res.suggested_unit == "°C"


def test_classifier_vibration():
    res1 = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.MainDriveMotorVibration",
        browse_name="2:MainDriveMotorVibration",
        display_name="MainDriveMotorVibration",
        data_type="Double",
        unit="mm/s"
    )
    assert res1.category == SignalClassificationCategory.VIBRATION
    assert res1.suggested_signal_code == "MOTOR_VIBRATION"
    assert res1.confidence_level == "HIGH"

    res2 = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.BearingVibration",
        browse_name="2:BearingVibration",
        display_name="BearingVibration",
        data_type="Double",
        unit="mm/s"
    )
    assert res2.category == SignalClassificationCategory.VIBRATION
    assert res2.suggested_signal_code == "BEARING_VIBRATION"
    assert res2.confidence_level == "HIGH"


def test_classifier_motor_current():
    res = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.MainDriveMotorCurrent",
        browse_name="2:MainDriveMotorCurrent",
        display_name="MainDriveMotorCurrent",
        data_type="Double",
        unit="A"
    )
    assert res.category == SignalClassificationCategory.MOTOR_CURRENT
    assert res.suggested_signal_code == "MOTOR_CURRENT"
    assert res.confidence_level == "HIGH"


def test_classifier_rotational_speed():
    res = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.MachineSpeedRPM",
        browse_name="2:MachineSpeedRPM",
        display_name="MachineSpeedRPM",
        data_type="Double",
        unit="RPM"
    )
    assert res.category == SignalClassificationCategory.ROTATIONAL_SPEED
    assert res.suggested_signal_code == "ROTATIONAL_SPEED_RPM"
    assert res.confidence_level == "HIGH"


def test_classifier_line_speed():
    res = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.Speed_CPM",
        browse_name="2:Speed_CPM",
        display_name="Speed_CPM",
        data_type="Double",
        unit="CPM"
    )
    assert res.category == SignalClassificationCategory.LINE_SPEED
    assert res.suggested_signal_code == "LINE_SPEED_CPM"
    assert res.confidence_level == "HIGH"


def test_classifier_pressure_and_vacuum():
    res_press = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.FormingAirPressure",
        browse_name="2:FormingAirPressure",
        display_name="FormingAirPressure",
        data_type="Double",
        unit="bar"
    )
    assert res_press.category == SignalClassificationCategory.PRESSURE
    assert res_press.suggested_signal_code == "FORMING_PRESSURE"
    assert res_press.confidence_level == "HIGH"

    res_vac = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.VacuumLevel",
        browse_name="2:VacuumLevel",
        display_name="VacuumLevel",
        data_type="Double",
        unit="bar"
    )
    assert res_vac.category == SignalClassificationCategory.VACUUM
    assert res_vac.suggested_signal_code == "VACUUM_LEVEL"
    assert res_vac.confidence_level == "HIGH"


def test_classifier_alarms_and_estop():
    res_alarm = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.MachineFaultAlarm",
        browse_name="2:MachineFaultAlarm",
        display_name="MachineFaultAlarm",
        data_type="Boolean"
    )
    assert res_alarm.category == SignalClassificationCategory.ALARM_FAULT
    assert res_alarm.confidence_level == "HIGH"

    res_estop = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.EmergencyStopActive",
        browse_name="2:EmergencyStopActive",
        display_name="EmergencyStopActive",
        data_type="Boolean"
    )
    assert res_estop.category == SignalClassificationCategory.ALARM_FAULT
    assert res_estop.suggested_signal_code == "EMERGENCY_STOP_ACTIVE"
    assert res_estop.confidence_level == "HIGH"


def test_classifier_cycle_and_production_counters():
    res_cycle = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.CumulativeCycleCount",
        browse_name="2:CumulativeCycleCount",
        display_name="CumulativeCycleCount",
        data_type="Int32"
    )
    assert res_cycle.category == SignalClassificationCategory.CYCLE_COUNTER
    assert res_cycle.suggested_signal_code == "CUMULATIVE_CYCLE_COUNT"
    assert res_cycle.confidence_level == "HIGH"

    res_batch = SignalClassifier.classify(
        node_id="ns=2;s=BlisterPackagingMachine_01.BatchProductionCount",
        browse_name="2:BatchProductionCount",
        display_name="BatchProductionCount",
        data_type="Int32"
    )
    assert res_batch.category == SignalClassificationCategory.PRODUCTION_COUNTER
    assert res_batch.suggested_signal_code == "BATCH_PRODUCTION_COUNT"
    assert res_batch.confidence_level == "HIGH"


def test_classifier_negative_context_and_false_positive_guard():
    """Proves that server status variables like CurrentTime and InsertDataCapability are not falsely classified."""
    # CurrentTime should NOT be classified as MOTOR_CURRENT (blocked by negative context 'time')
    res_time = SignalClassifier.classify(
        node_id="i=2258",
        browse_name="0:CurrentTime",
        display_name="CurrentTime",
        data_type="UtcTime"
    )
    assert res_time.category != SignalClassificationCategory.MOTOR_CURRENT
    assert res_time.confidence_level == "UNMAPPED"

    # InsertDataCapability should NOT be classified as TEMPERATURE (no false 'rtd' token match)
    res_cap = SignalClassifier.classify(
        node_id="i=11200",
        browse_name="0:InsertDataCapability",
        display_name="InsertDataCapability",
        data_type="Boolean"
    )
    assert res_cap.category != SignalClassificationCategory.TEMPERATURE
    assert res_cap.confidence_level == "UNMAPPED"


def test_classifier_unmapped_generic():
    """Unrecognized machine tags are assigned UNMAPPED without fabricated classifications."""
    res = SignalClassifier.classify(
        node_id="ns=2;s=VendorCustomStringBlock",
        browse_name="2:VendorCustomStringBlock",
        display_name="VendorCustomStringBlock",
        data_type="String"
    )
    assert res.category == SignalClassificationCategory.OTHER
    assert res.confidence_level == "UNMAPPED"
    assert res.suggested_signal_code == "UNMAPPED_VARIABLE"


# =============================================================================
# 3. SAFETY & GOVERNANCE TESTS
# =============================================================================

def test_read_only_safety_guard():
    """Proves that the discovery engine strictly prohibits write operations."""
    config = TagDiscoveryConfig()
    discovery = OPCUATagDiscovery(config)
    
    # Attempting to call execute_write must immediately raise ReadOnlyViolationError
    with pytest.raises(ReadOnlyViolationError) as exc_info:
        discovery.execute_write("ns=2;s=BlisterPackagingMachine_01.Speed_CPM", 999.0)
    assert "Tag Discovery is strictly READ-ONLY" in str(exc_info.value)


def test_security_downgrade_rejection():
    """Proves that requesting Basic256Sha256 without credentials raises SecurityDowngradeError."""
    config = TagDiscoveryConfig(
        security_policy="Basic256Sha256",
        security_mode="SignAndEncrypt",
        client_cert_path=None,  # Missing cert
        client_key_path=None,   # Missing key
    )
    discovery = OPCUATagDiscovery(config)
    with pytest.raises(SecurityDowngradeError) as exc_info:
        asyncio.run(discovery.connect())
    assert "client_cert_path or client_key_path is missing" in str(exc_info.value)


def test_credentials_not_in_sanitized_config():
    """Proves passwords and private keys are never exposed in configuration dictionaries."""
    config = TagDiscoveryConfig(
        username="admin_user",
        password="SuperSecretPassword123!",
        client_key_path="/etc/ssl/private/client.key"
    )
    safe = config.sanitized_repr()
    assert safe["password"] == "***REDACTED***"
    assert safe["client_key_path"] == "***REDACTED***"
    assert "SuperSecretPassword123!" not in json.dumps(safe)


@pytest.mark.asyncio
async def test_connection_failure_handling():
    """Verifies that unreachable endpoints fail gracefully with ConnectionFailedError."""
    bad_config = TagDiscoveryConfig(
        endpoint_url="opc.tcp://127.0.0.1:48498/unreachable_port/",
        timeout_sec=1.5
    )
    discovery = OPCUATagDiscovery(bad_config)
    with pytest.raises(ConnectionFailedError) as exc_info:
        await discovery.connect()
    assert "Unable to connect to OPC UA server" in str(exc_info.value)


# =============================================================================
# 4. FULL INTEGRATION DISCOVERY TEST (13/13 DEMO SIGNALS)
# =============================================================================

@pytest.mark.asyncio
async def test_full_discovery_against_simulator(standalone_simulator, tmp_path):
    """End-to-end integration test discovering all 13 signals from live simulator."""
    out_dir = str(tmp_path / "discovery_output")
    config = TagDiscoveryConfig(
        endpoint_url=standalone_simulator.get_endpoint(),
        root_node_id="i=85",
        skip_server_diagnostics=True,
        read_current_values=True,
        output_dir=out_dir,
        timeout_sec=5.0
    )

    discovery = OPCUATagDiscovery(config)
    await discovery.connect()
    summary = await discovery.discover()
    disc_file, temp_file = discovery.export_templates(out_dir)
    await discovery.disconnect()

    # 1. Verify summary metrics
    assert summary["variables_discovered"] >= 13
    assert summary["mapped_signals"] == 13

    # 2. Verify discovered_nodes.json
    assert os.path.exists(disc_file)
    with open(disc_file, "r", encoding="utf-8") as f:
        inv = json.load(f)
    assert inv["metadata"]["endpoint_url"] == standalone_simulator.get_endpoint()
    assert len(inv["nodes"]) >= 13

    # Check that all 13 required signals exist in inventory
    expected_signals = [
        "Speed_CPM",
        "MachineSpeedRPM",
        "SealingTemperature",
        "MotorTemperature",
        "MainDriveMotorVibration",
        "BearingVibration",
        "MainDriveMotorCurrent",
        "VacuumLevel",
        "FormingAirPressure",
        "MachineFaultAlarm",
        "EmergencyStopActive",
        "CumulativeCycleCount",
        "BatchProductionCount"
    ]
    discovered_names = [n["display_name"] for n in inv["nodes"]]
    for exp in expected_signals:
        assert exp in discovered_names, f"Expected signal '{exp}' not discovered!"

    # 3. Verify signal_mapping_template.json
    assert os.path.exists(temp_file)
    with open(temp_file, "r", encoding="utf-8") as f:
        tpl = json.load(f)
    assert tpl["metadata"]["mapped_candidate_count"] == 13
    mapped = tpl["mapped_signals"]
    assert len(mapped) == 13

    for item in mapped:
        assert item["mapping_status"] == "CANDIDATE_FOR_REVIEW"
        assert item["confidence_level"] in ("HIGH", "MEDIUM")
        assert item["confidence_score"] >= 0.50
        assert "suggested_signal_code" in item
        assert "signal_group" in item
        assert item["source_node_id"].startswith("ns=2;s=BlisterPackagingMachine_01")
