"""
PharmaPredict AI — Pilot Environment Configuration Manager
===========================================================
Phase 11: Controlled Pharmaceutical Factory Pilot Commissioning.

Provides structured configuration management for physical or simulated pilot
deployments without altering or disrupting existing demonstration or production lines.
Supports isolated tenant configuration, multi-PLC vendor parameters, canonical signal
manifests, and automatic .env.edge generation.
"""

import os
import re
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("PharmaPredict.PilotConfig")


# =============================================================================
# 1. PILOT SIGNAL & DEPLOYMENT DATA STRUCTURES
# =============================================================================

@dataclass
class PilotSignalDefinition:
    """Canonical signal definition for pilot commissioning."""
    canonical_name: str
    node_id: str
    data_type: str = "Double"
    engineering_units: Optional[str] = None
    sampling_interval_ms: int = 1000
    criticality: str = "MEDIUM"  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    description: Optional[str] = None
    warning_min: Optional[float] = None
    warning_max: Optional[float] = None
    critical_min: Optional[float] = None
    critical_max: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PilotDeploymentConfig:
    """Complete deployment specification for a pilot commissioning site."""
    # Organization & Hierarchy
    organization_name: str = "Getz Pharma"
    organization_slug: str = "getz-pharma"
    site_name: str = "Karachi Manufacturing Facility"
    site_code: str = "KHI-01"
    production_area: str = "Secondary Packaging Hall"
    production_line: str = "Packaging Line 4"
    line_code: str = "LINE-04"

    # Equipment Under Commissioning
    machine_asset_code: str = "PILOT-BPK-01"
    machine_name: str = "Uhlen Blister Packaging Machine BPK-200 (Pilot)"
    manufacturer: str = "Uhlen"
    model: str = "BPK-200"
    equipment_category: str = "Blister Packaging"

    # PLC & OT Specifications
    plc_manufacturer: str = "Siemens"  # "Siemens", "Beckhoff", "Rockwell", "Kepware", "Other"
    plc_model: str = "S7-1500 (CPU 1516F-3 PN/DP)"
    opcua_endpoint_url: str = "opc.tcp://192.168.10.50:4840"
    is_physical_plc: bool = False  # Explicitly False until physical verification on factory floor

    # Gateway Parameters
    gateway_id: str = "gw-edge-pilot-01"
    engineer_name: str = "Lead Automation Engineer"
    security_mode: str = "SignAndEncrypt"  # "SignAndEncrypt", "Sign", "None"
    security_policy: str = "Basic256Sha256"
    client_cert_path: str = "/var/lib/pharmapredict/certs/client_cert.pem"
    client_key_path: str = "/var/lib/pharmapredict/certs/client_key.pem"
    server_cert_path: str = "/var/lib/pharmapredict/trusted_certs/plc_cert.pem"

    # Cloud & Network Parameters
    cloud_ingestion_url: str = "https://predictive-maintenance-system-bay.vercel.app/api/v1/telemetry/ingest"
    batch_size: int = 50
    flush_interval_sec: float = 1.0
    heartbeat_interval_sec: float = 30.0

    # Signals
    signals: List[Dict[str, Any]] = field(default_factory=list)

    # Metadata & Timestamps
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def validate(self) -> List[str]:
        """Validates configuration parameters and returns a list of error strings."""
        errors: List[str] = []

        if not self.organization_name or not self.organization_name.strip():
            errors.append("organization_name must not be empty.")
        if not self.site_name or not self.site_name.strip():
            errors.append("site_name must not be empty.")
        if not self.machine_asset_code or not self.machine_asset_code.strip():
            errors.append("machine_asset_code must not be empty.")
        if not self.machine_name or not self.machine_name.strip():
            errors.append("machine_name must not be empty.")

        # Asset code format check (alphanumeric with hyphens/underscores)
        if not re.match(r"^[A-Za-z0-9_-]+$", self.machine_asset_code):
            errors.append(f"machine_asset_code '{self.machine_asset_code}' contains invalid characters.")

        # OPC UA Endpoint validation
        if not self.opcua_endpoint_url or not self.opcua_endpoint_url.startswith("opc.tcp://"):
            errors.append(f"opcua_endpoint_url must start with 'opc.tcp://', got '{self.opcua_endpoint_url}'.")

        # Security mode validation
        valid_security_modes = ["None", "Sign", "SignAndEncrypt"]
        if self.security_mode not in valid_security_modes:
            errors.append(f"security_mode must be one of {valid_security_modes}, got '{self.security_mode}'.")

        # Physical PLC security constraint: physical pilots must never use 'None'
        if self.is_physical_plc and self.security_mode == "None":
            errors.append("Physical PLC pilots strictly require encrypted security ('SignAndEncrypt' or 'Sign'). 'None' is prohibited.")

        # Ingestion URL validation
        if not self.cloud_ingestion_url.startswith(("http://", "https://")):
            errors.append(f"cloud_ingestion_url must be an HTTP/HTTPS URL, got '{self.cloud_ingestion_url}'.")

        # Signals validation
        if not self.signals:
            errors.append("Pilot configuration must contain at least one mapped signal.")
        else:
            seen_nodes = set()
            seen_canonicals = set()
            for idx, sig in enumerate(self.signals):
                nid = sig.get("node_id")
                cname = sig.get("canonical_name")
                if not nid:
                    errors.append(f"Signal #{idx} missing required 'node_id'.")
                elif nid in seen_nodes:
                    errors.append(f"Duplicate node_id '{nid}' detected in signal configuration.")
                else:
                    seen_nodes.add(nid)

                if not cname:
                    errors.append(f"Signal #{idx} missing required 'canonical_name'.")
                elif cname in seen_canonicals:
                    errors.append(f"Duplicate canonical_name '{cname}' detected in signal configuration.")
                else:
                    seen_canonicals.add(cname)

        return errors

    def to_dict(self) -> Dict[str, Any]:
        """Converts configuration to JSON-serializable dictionary."""
        return asdict(self)

    def to_env_edge_format(self) -> str:
        """Generates ready-to-use .env.edge file content for the edge gateway container."""
        lines = [
            "# =============================================================================",
            "# PharmaPredict AI — Edge Gateway Production Environment Configuration",
            f"# Generated for Pilot: {self.machine_asset_code} ({self.organization_name})",
            f"# Generated at: {datetime.now(timezone.utc).isoformat()}",
            "# =============================================================================",
            "",
            f"GATEWAY_ID={self.gateway_id}",
            f"MACHINE_ID={self.machine_asset_code}",
            f"OPCUA_ENDPOINT_URL={self.opcua_endpoint_url}",
            f"OPCUA_SECURITY_MODE={self.security_mode}",
            f"OPCUA_SECURITY_POLICY={self.security_policy}",
            f"CLIENT_CERT_PATH={self.client_cert_path}",
            f"CLIENT_KEY_PATH={self.client_key_path}",
            f"SERVER_CERT_PATH={self.server_cert_path}",
            f"CLOUD_INGESTION_URL={self.cloud_ingestion_url}",
            f"BATCH_SIZE={self.batch_size}",
            f"FLUSH_INTERVAL_SEC={self.flush_interval_sec}",
            f"HEARTBEAT_INTERVAL_SEC={self.heartbeat_interval_sec}",
            "MAX_QUEUE_SIZE=5000",
            "MAX_DISK_BUFFER_BYTES=52428800",
            "DISK_BUFFER_DIR=/var/lib/pharmapredict/buffer",
            "LOG_LEVEL=INFO",
            "STRUCTURED_LOGS=true",
            "",
            "# Mapped Signals JSON",
            f"MONITORED_NODES_JSON={json.dumps(self.signals)}",
        ]
        return "\n".join(lines) + "\n"

    def to_machine_onboarding_payload(self) -> Dict[str, Any]:
        """Generates equipment onboarding payload for the cloud backend API."""
        return {
            "organization_name": self.organization_name,
            "organization_slug": self.organization_slug,
            "site_name": self.site_name,
            "site_code": self.site_code,
            "production_area": self.production_area,
            "production_line": self.production_line,
            "line_code": self.line_code,
            "machine_name": self.machine_name,
            "asset_code": self.machine_asset_code,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "equipment_category": self.equipment_category,
            "plc_manufacturer": self.plc_manufacturer,
            "plc_model": self.plc_model,
            "gateway_id": self.gateway_id,
            "signals": self.signals,
            "is_physical_plc": self.is_physical_plc,
        }


# =============================================================================
# 2. PILOT CONFIGURATION MANAGER
# =============================================================================

class PilotConfigManager:
    """Manages pilot configuration lifecycle, serialization, and isolation."""

    @staticmethod
    def get_default_uhlen_bpk200_pilot(
        is_physical_plc: bool = False,
        endpoint_url: Optional[str] = None,
        asset_code: str = "PILOT-BPK-01",
    ) -> PilotDeploymentConfig:
        """Returns standard 13-signal configuration for Uhlen BPK-200 blister packaging machine."""
        default_endpoint = (
            "opc.tcp://192.168.10.50:4840" if is_physical_plc
            else "opc.tcp://127.0.0.1:4840/freeopcua/server/"
        )

        # Standard 13-signal mapping for Uhlen BPK-200
        standard_signals = [
            {
                "canonical_name": "forming_temperature",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.FormingTemperature" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"FormingTemp\"",
                "data_type": "Double",
                "engineering_units": "°C",
                "sampling_interval_ms": 1000,
                "criticality": "HIGH",
                "warning_min": 120.0,
                "warning_max": 145.0,
                "critical_min": 115.0,
                "critical_max": 150.0,
            },
            {
                "canonical_name": "sealing_temperature",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"SealingTemp\"",
                "data_type": "Double",
                "engineering_units": "°C",
                "sampling_interval_ms": 1000,
                "criticality": "CRITICAL",
                "warning_min": 170.0,
                "warning_max": 190.0,
                "critical_min": 165.0,
                "critical_max": 195.0,
            },
            {
                "canonical_name": "motor_temperature",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.MotorTemperature" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"MotorTemp\"",
                "data_type": "Double",
                "engineering_units": "°C",
                "sampling_interval_ms": 1000,
                "criticality": "MEDIUM",
                "warning_min": 40.0,
                "warning_max": 75.0,
                "critical_min": 35.0,
                "critical_max": 85.0,
            },
            {
                "canonical_name": "vibration_level",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorVibration" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"MotorVibration\"",
                "data_type": "Double",
                "engineering_units": "mm/s",
                "sampling_interval_ms": 1000,
                "criticality": "HIGH",
                "warning_min": 0.0,
                "warning_max": 4.5,
                "critical_min": 0.0,
                "critical_max": 7.1,
            },
            {
                "canonical_name": "bearing_vibration",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.BearingVibration" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"BearingVibration\"",
                "data_type": "Double",
                "engineering_units": "mm/s",
                "sampling_interval_ms": 1000,
                "criticality": "HIGH",
                "warning_min": 0.0,
                "warning_max": 3.5,
                "critical_min": 0.0,
                "critical_max": 5.5,
            },
            {
                "canonical_name": "motor_current",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorCurrent" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"MotorCurrent\"",
                "data_type": "Double",
                "engineering_units": "A",
                "sampling_interval_ms": 1000,
                "criticality": "MEDIUM",
                "warning_min": 8.0,
                "warning_max": 24.0,
                "critical_min": 5.0,
                "critical_max": 28.0,
            },
            {
                "canonical_name": "line_speed_cpm",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.Speed_CPM" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"SpeedCPM\"",
                "data_type": "Double",
                "engineering_units": "CPM",
                "sampling_interval_ms": 1000,
                "criticality": "MEDIUM",
                "warning_min": 50.0,
                "warning_max": 220.0,
                "critical_min": 0.0,
                "critical_max": 250.0,
            },
            {
                "canonical_name": "rotational_speed_rpm",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.MachineSpeedRPM" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"SpeedRPM\"",
                "data_type": "Double",
                "engineering_units": "RPM",
                "sampling_interval_ms": 1000,
                "criticality": "LOW",
                "warning_min": 500.0,
                "warning_max": 1800.0,
                "critical_min": 0.0,
                "critical_max": 2000.0,
            },
            {
                "canonical_name": "forming_air_pressure",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.FormingAirPressure" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"AirPressure\"",
                "data_type": "Double",
                "engineering_units": "bar",
                "sampling_interval_ms": 1000,
                "criticality": "HIGH",
                "warning_min": 5.5,
                "warning_max": 7.0,
                "critical_min": 5.0,
                "critical_max": 7.5,
            },
            {
                "canonical_name": "vacuum_level",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.VacuumLevel" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"VacuumLevel\"",
                "data_type": "Double",
                "engineering_units": "bar",
                "sampling_interval_ms": 1000,
                "criticality": "HIGH",
                "warning_min": -0.85,
                "warning_max": -0.60,
                "critical_min": -0.95,
                "critical_max": -0.50,
            },
            {
                "canonical_name": "alarm_active",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.MachineFaultAlarm" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"AlarmActive\"",
                "data_type": "Boolean",
                "engineering_units": "status",
                "sampling_interval_ms": 1000,
                "criticality": "CRITICAL",
            },
            {
                "canonical_name": "emergency_stop",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.EmergencyStopActive" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"EStopActive\"",
                "data_type": "Boolean",
                "engineering_units": "status",
                "sampling_interval_ms": 1000,
                "criticality": "CRITICAL",
            },
            {
                "canonical_name": "cycle_count",
                "node_id": "ns=2;s=BlisterPackagingMachine_01.CumulativeCycleCount" if not is_physical_plc else "ns=3;s=\"DB_Telemetry\".\"CycleCount\"",
                "data_type": "Int64",
                "engineering_units": "cycles",
                "sampling_interval_ms": 1000,
                "criticality": "LOW",
            },
        ]

        return PilotDeploymentConfig(
            organization_name="Getz Pharma",
            organization_slug="getz-pharma",
            site_name="Karachi Manufacturing Facility",
            site_code="KHI-01",
            production_area="Secondary Packaging Hall",
            production_line="Packaging Line 4",
            line_code="LINE-04",
            machine_asset_code=asset_code,
            machine_name="Uhlen Blister Packaging Machine BPK-200 (Pilot)",
            manufacturer="Uhlen",
            model="BPK-200",
            equipment_category="Blister Packaging",
            plc_manufacturer="Siemens" if is_physical_plc else "Kepware",
            plc_model="S7-1500 (CPU 1516F-3 PN/DP)" if is_physical_plc else "Simulated Server",
            opcua_endpoint_url=endpoint_url or default_endpoint,
            gateway_id="gw-edge-pilot-01",
            engineer_name="Lead Automation Engineer",
            is_physical_plc=is_physical_plc,
            security_mode="SignAndEncrypt" if is_physical_plc else "None",
            security_policy="Basic256Sha256" if is_physical_plc else "None",
            signals=standard_signals,
        )

    @staticmethod
    def save_to_json(config: PilotDeploymentConfig, filepath: str | Path) -> None:
        """Saves pilot configuration to a JSON file with pretty formatting."""
        p = Path(filepath)
        p.parent.mkdir(parents=True, exist_ok=True)
        config.updated_at = datetime.now(timezone.utc).isoformat()
        with open(p, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2)
        logger.info(f"Pilot configuration saved to {p}")

    @staticmethod
    def load_from_json(filepath: str | Path) -> PilotDeploymentConfig:
        """Loads and parses pilot configuration from a JSON file."""
        p = Path(filepath)
        if not p.exists():
            raise FileNotFoundError(f"Pilot config file not found: {p}")
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return PilotDeploymentConfig(**data)

    @staticmethod
    def generate_env_file(config: PilotDeploymentConfig, output_path: str | Path = ".env.edge") -> None:
        """Generates a populated .env.edge file from the configuration."""
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        content = config.to_env_edge_format()
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Environment file generated at {p}")
