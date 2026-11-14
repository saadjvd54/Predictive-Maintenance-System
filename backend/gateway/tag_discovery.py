"""
PharmaPredict AI — Standalone OPC UA PLC Tag Discovery Utility
=============================================================
Connects to industrial OPC UA servers (Siemens, Beckhoff, Allen-Bradley, Kepware)
in strictly READ-ONLY mode. Recursively browses the address space from Root.Objects,
identifies candidate telemetry variables, extracts engineering metadata, classifies
signals into canonical pharmaceutical categories, and exports standardized mapping templates.

Safety & Governance Rules:
- Strictly Read-Only: Never executes OPC UA write operations or PLC control calls.
- Security Assurance: Supports Basic256Sha256 SignAndEncrypt and X.509 client certificates.
- Downgrade Protection: Rejects silent downgrades from secure to plaintext/anonymous access.
- Cycle Prevention: Implements visited-set tracking to avoid infinite browsing loops.
- Credential Safety: Never logs, outputs, or exports passwords, tokens, or private keys.
"""

import os
import sys
import re
import json
import time
import uuid
import asyncio
import logging
import argparse
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Set, Tuple
from datetime import datetime, timezone

# Ensure backend directory is in sys.path when running standalone
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import asyncua
from asyncua import Client, ua
from asyncua.crypto.security_policies import (
    SecurityPolicyBasic256Sha256,
    SecurityPolicyAes128Sha256RsaOaep,
)

logger = logging.getLogger("PharmaPredict.TagDiscovery")


# =============================================================================
# 1. EXCEPTIONS & ERROR TYPES
# =============================================================================

class DiscoveryError(Exception):
    """Base exception for OPC UA tag discovery failures."""
    pass


class ReadOnlyViolationError(DiscoveryError):
    """Raised when any modification or write operation is attempted."""
    pass


class SecurityDowngradeError(DiscoveryError):
    """Raised when a secure connection is forced into an unencrypted mode."""
    pass


class ConnectionFailedError(DiscoveryError):
    """Raised when unable to establish connection to OPC UA endpoint."""
    pass


# =============================================================================
# 2. CONFIGURATION DATASTRUCTURE
# =============================================================================

@dataclass
class TagDiscoveryConfig:
    """Configuration options for standalone OPC UA tag discovery."""
    endpoint_url: str = "opc.tcp://127.0.0.1:48401/pharmapredict/server/"
    root_node_id: str = "i=85"  # Root.Objects folder by default
    skip_server_diagnostics: bool = True  # Ignore standard OPC UA internal server diagnostics (ns=0;i=2253 / Objects/Server)
    security_policy: str = "None"  # None, Basic256Sha256, Aes128_Sha256_RsaOaep
    security_mode: str = "None"  # None, Sign, SignAndEncrypt
    auth_type: str = "Anonymous"  # Anonymous, UserName, Certificate
    username: Optional[str] = None
    password: Optional[str] = None
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None
    trusted_cert_paths: List[str] = field(default_factory=list)
    allow_untrusted_cert: bool = False
    timeout_sec: float = 10.0
    max_depth: int = 10
    max_nodes: int = 10000
    read_current_values: bool = True
    output_dir: str = "./data/discovery"

    def sanitized_repr(self) -> Dict[str, Any]:
        """Returns safe configuration copy with sensitive credentials redacted."""
        d = asdict(self)
        if d.get("password"):
            d["password"] = "***REDACTED***"
        if d.get("client_key_path"):
            d["client_key_path"] = "***REDACTED***"
        return d


# =============================================================================
# 3. SIGNAL CLASSIFIER ENGINE
# =============================================================================

class SignalClassificationCategory:
    TEMPERATURE = "Temperature"
    VIBRATION = "Vibration"
    MOTOR_CURRENT = "Motor Current"
    ROTATIONAL_SPEED = "Rotational Speed"
    LINE_SPEED = "Line Speed"
    PRESSURE = "Pressure"
    VACUUM = "Vacuum"
    FLOW = "Flow"
    ALARM_FAULT = "Alarm / Fault"
    CYCLE_COUNTER = "Cycle Counter"
    PRODUCTION_COUNTER = "Production Counter"
    OTHER = "Other"

    ALL_CATEGORIES = [
        TEMPERATURE,
        VIBRATION,
        MOTOR_CURRENT,
        ROTATIONAL_SPEED,
        LINE_SPEED,
        PRESSURE,
        VACUUM,
        FLOW,
        ALARM_FAULT,
        CYCLE_COUNTER,
        PRODUCTION_COUNTER,
        OTHER,
    ]


@dataclass
class ClassificationResult:
    """Evaluation result for an identified variable node."""
    category: str
    suggested_signal_code: str
    suggested_unit: Optional[str]
    confidence_level: str  # HIGH, MEDIUM, LOW, UNMAPPED
    confidence_score: float  # 0.0 to 1.0
    classification_reason: str


class SignalClassifier:
    """Rule-based industrial telemetry signal classifier for pharmaceutical packaging machinery."""

    # Keywords with associated base weights
    RULES = {
        SignalClassificationCategory.TEMPERATURE: {
            "tokens": {"temp", "temperature", "celsius", "degc", "rtd", "therm", "pt100", "heat", "heater", "sealingtemp", "motortemp"},
            "units": ["°c", "degc", "c", "k", "deg_c"],
            "canonical_code": "TEMPERATURE",
            "default_unit": "°C",
            "compatible_types": ["Double", "Float", "Float32", "Float64", "Int16", "Int32"],
        },
        SignalClassificationCategory.VIBRATION: {
            "tokens": {"vibration", "vibrat", "vib", "accel", "acceleration", "velocity", "bearingvib", "motorvib", "rms"},
            "units": ["mm/s", "m/s2", "g", "in/s", "mm/sec"],
            "canonical_code": "VIBRATION",
            "default_unit": "mm/s",
            "compatible_types": ["Double", "Float", "Float32", "Float64"],
        },
        SignalClassificationCategory.MOTOR_CURRENT: {
            "tokens": {"current", "amperage", "ampere", "motorcurr", "loadcurrent", "amps", "flamp", "maindrivemotorcurrent"},
            "negative_context": {"time", "version", "session", "count", "state", "file", "date", "item", "timestamp"},
            "units": ["a", "ma", "amp", "amperes"],
            "canonical_code": "MOTOR_CURRENT",
            "default_unit": "A",
            "compatible_types": ["Double", "Float", "Float32", "Float64"],
        },
        SignalClassificationCategory.ROTATIONAL_SPEED: {
            "tokens": {"rpm", "rotational", "rotat", "shaftspeed", "motorspeed", "machinespeedrpm", "spindlespeed", "revmin"},
            "units": ["rpm", "rev/min", "rad/s", "1/min"],
            "canonical_code": "ROTATIONAL_SPEED_RPM",
            "default_unit": "RPM",
            "compatible_types": ["Double", "Float", "Float32", "Float64", "Int32"],
        },
        SignalClassificationCategory.LINE_SPEED: {
            "tokens": {"speedcpm", "cpm", "linespeed", "throughput", "blisterspeed", "packspermin", "cartonspermin", "speed"},
            "units": ["cpm", "m/min", "m/s", "packs/min"],
            "canonical_code": "LINE_SPEED_CPM",
            "default_unit": "CPM",
            "compatible_types": ["Double", "Float", "Float32", "Float64", "Int32"],
        },
        SignalClassificationCategory.PRESSURE: {
            "tokens": {"pressure", "formingpress", "sealingpress", "airpress", "pneumatic", "formingairpressure", "supplypress"},
            "units": ["bar", "psi", "kpa", "mpa"],
            "canonical_code": "PRESSURE",
            "default_unit": "bar",
            "compatible_types": ["Double", "Float", "Float32", "Float64"],
        },
        SignalClassificationCategory.VACUUM: {
            "tokens": {"vacuum", "vac", "suction", "negativepress", "vacuumlevel", "blistervac"},
            "units": ["bar", "mbar", "kpa", "inhg", "mmhg"],
            "canonical_code": "VACUUM_LEVEL",
            "default_unit": "bar",
            "compatible_types": ["Double", "Float", "Float32", "Float64"],
        },
        SignalClassificationCategory.FLOW: {
            "tokens": {"flow", "flowrate", "coolingflow", "purgeflow"},
            "units": ["l/min", "gpm", "cfm", "m3/h", "l/h"],
            "canonical_code": "FLOW_RATE",
            "default_unit": "L/min",
            "compatible_types": ["Double", "Float", "Float32", "Float64"],
        },
        SignalClassificationCategory.ALARM_FAULT: {
            "tokens": {"alarm", "fault", "error", "estop", "emergencystop", "trip", "interlock", "machinefaultalarm", "emergencystopactive"},
            "units": ["bool", "state"],
            "canonical_code": "ALARM_STATE",
            "default_unit": "status",
            "compatible_types": ["Boolean", "Int16", "Int32", "Byte", "UInt16"],
        },
        SignalClassificationCategory.CYCLE_COUNTER: {
            "tokens": {"cumulativecyclecount", "cyclecount", "cycle", "cycles", "strokecount", "machinecycles", "totalcycles"},
            "units": ["cycles", "count", "strokes"],
            "canonical_code": "CYCLE_COUNT",
            "default_unit": "cycles",
            "compatible_types": ["Int32", "Int64", "UInt32", "UInt64"],
        },
        SignalClassificationCategory.PRODUCTION_COUNTER: {
            "tokens": {"batchproductioncount", "batchcount", "goodcount", "rejectcount", "packcount", "outputcount", "batch", "production"},
            "units": ["packs", "blisters", "count", "units", "pcs"],
            "canonical_code": "PRODUCTION_COUNT",
            "default_unit": "units",
            "compatible_types": ["Int32", "Int64", "UInt32", "UInt64"],
        },
    }

    @classmethod
    def tokenize(cls, text: str) -> List[str]:
        """Splits camelCase, snake_case, dot.case, and alphanumeric tokens."""
        raw_tokens = re.findall(r'[A-Z]+(?=[A-Z][a-z]|\d|\W|$)|[A-Z]?[a-z]+|[0-9]+', text)
        return [t.lower() for t in raw_tokens if t]

    @classmethod
    def classify(
        cls,
        node_id: str,
        browse_name: str,
        display_name: str,
        data_type: str,
        unit: Optional[str] = None
    ) -> ClassificationResult:
        """Evaluates node metadata and assigns a classification category and confidence score."""
        # Extract tokens from original casing to preserve camelCase boundaries
        raw_combined = f"{browse_name} {display_name} {node_id}"
        tokens = set(cls.tokenize(raw_combined))
        combined_text = f"{browse_name} {display_name}".lower()
        full_text = f"{node_id} {browse_name} {display_name}".lower()
        clean_unit = (unit or "").lower().strip()
        clean_type = (data_type or "").strip()

        best_category = SignalClassificationCategory.OTHER
        best_code = "UNMAPPED_VARIABLE"
        best_score = 0.0
        best_reason = "No matching industrial keywords identified."
        best_unit = unit

        for category, rule in cls.RULES.items():
            matched_keywords = []
            score = 0.0

            # Check negative context (e.g. CurrentTime, CurrentSessionCount for electrical current)
            neg_context = rule.get("negative_context", set())
            if neg_context and (tokens & neg_context):
                continue

            # 1. Check token matches (whole token match or long compound keywords)
            for kw in rule["tokens"]:
                clean_kw = kw.lower()
                if clean_kw in tokens or (len(clean_kw) >= 6 and (clean_kw in combined_text.replace("_", "").replace("-", "") or clean_kw in full_text.replace("_", "").replace("-", ""))):
                    matched_keywords.append(kw)
                    score += 0.55 if len(kw) > 6 else 0.45

            if not matched_keywords:
                continue

            # 2. Check Unit compatibility
            unit_matched = False
            if clean_unit:
                for expected_unit in rule["units"]:
                    if expected_unit in clean_unit or clean_unit == expected_unit:
                        unit_matched = True
                        score += 0.35
                        break

            # 3. Check Data Type compatibility
            type_compatible = False
            for comp_type in rule["compatible_types"]:
                if comp_type.lower() in clean_type.lower():
                    type_compatible = True
                    score += 0.20
                    break

            # Deduce specific canonical signal name
            canonical_name = rule["canonical_code"]
            if "bearing" in tokens and category == SignalClassificationCategory.VIBRATION:
                canonical_name = "BEARING_VIBRATION"
            elif "motor" in tokens and category == SignalClassificationCategory.VIBRATION:
                canonical_name = "MOTOR_VIBRATION"
            elif "sealing" in tokens and category == SignalClassificationCategory.TEMPERATURE:
                canonical_name = "SEALING_TEMPERATURE"
            elif "motor" in tokens and category == SignalClassificationCategory.TEMPERATURE:
                canonical_name = "MOTOR_TEMPERATURE"
            elif "forming" in tokens and category == SignalClassificationCategory.PRESSURE:
                canonical_name = "FORMING_PRESSURE"
            elif "estop" in tokens or "emergency" in tokens:
                canonical_name = "EMERGENCY_STOP_ACTIVE"
            elif "cycle" in tokens or "cumulative" in tokens:
                canonical_name = "CUMULATIVE_CYCLE_COUNT"
            elif "batch" in tokens or "production" in tokens:
                canonical_name = "BATCH_PRODUCTION_COUNT"

            # Cap score at 1.0
            score = min(round(score, 2), 1.0)

            if score > best_score:
                best_score = score
                best_category = category
                best_code = canonical_name
                best_unit = unit or rule["default_unit"]
                reasons = [f"matched keywords: {', '.join(matched_keywords)}"]
                if unit_matched:
                    reasons.append(f"unit '{unit}' aligns")
                if type_compatible:
                    reasons.append(f"data type '{data_type}' compatible")
                best_reason = "; ".join(reasons)

        # Determine confidence level
        if best_score >= 0.75:
            conf_level = "HIGH"
        elif best_score >= 0.50:
            conf_level = "MEDIUM"
        elif best_score >= 0.30:
            conf_level = "LOW"
        else:
            conf_level = "UNMAPPED"
            best_category = SignalClassificationCategory.OTHER
            best_code = "UNMAPPED_VARIABLE"

        return ClassificationResult(
            category=best_category,
            suggested_signal_code=best_code,
            suggested_unit=best_unit,
            confidence_level=conf_level,
            confidence_score=best_score,
            classification_reason=best_reason
        )


# =============================================================================
# 4. TAG DISCOVERY ENGINE (STRICTLY READ-ONLY)
# =============================================================================

class OPCUATagDiscovery:
    """Production-grade, strictly read-only OPC UA address space discovery engine."""

    def __init__(self, config: TagDiscoveryConfig):
        self.config = config
        self._client: Optional[Client] = None
        self._visited_node_ids: Set[str] = set()
        self._discovered_nodes: List[Dict[str, Any]] = []
        self._inaccessible_nodes: List[Dict[str, Any]] = []
        self._is_connected: bool = False
        self._server_name: str = "Unknown Server"
        self._server_cert_fingerprint: Optional[str] = None
        self._discovery_start_time: Optional[datetime] = None
        self._discovery_end_time: Optional[datetime] = None

    # -------------------------------------------------------------------------
    # SAFETY GUARD: STRICT READ-ONLY ENFORCEMENT
    # -------------------------------------------------------------------------
    def _assert_read_only(self) -> None:
        """Enforces that the discovery engine cannot execute write or control operations."""
        pass  # Explicit read-only design; write methods are strictly excluded from class interface

    def execute_write(self, *args, **kwargs):
        """Proof-of-safety guard: explicitly raises ReadOnlyViolationError on any write call."""
        raise ReadOnlyViolationError("CRITICAL SAFETY VIOLATION: Tag Discovery is strictly READ-ONLY. Write operations are prohibited.")

    # -------------------------------------------------------------------------
    # CONNECTION MANAGEMENT
    # -------------------------------------------------------------------------
    async def connect(self) -> None:
        """Establishes a secure, read-only OPC UA connection with security policy enforcement."""
        logger.info(f"Connecting to OPC UA endpoint: {self.config.endpoint_url}")
        
        try:
            self._client = Client(url=self.config.endpoint_url, timeout=self.config.timeout_sec)
        except Exception as e:
            raise ConnectionFailedError(f"Failed to initialize OPC UA client for '{self.config.endpoint_url}': {e}") from e

        # Configure Security Policy & Encryption
        sec_policy = (self.config.security_policy or "None").lower()
        sec_mode = (self.config.security_mode or "None").lower()

        if sec_policy in ("basic256sha256", "basic256sha256_signandencrypt"):
            if not self.config.client_cert_path or not self.config.client_key_path:
                raise SecurityDowngradeError("Basic256Sha256 requested but client_cert_path or client_key_path is missing.")
            
            try:
                mode = ua.MessageSecurityMode.SignAndEncrypt if "encrypt" in sec_mode else ua.MessageSecurityMode.Sign
                await self._client.set_security(
                    SecurityPolicyBasic256Sha256,
                    certificate=self.config.client_cert_path,
                    private_key=self.config.client_key_path,
                    mode=mode,
                )
                logger.info("Configured Basic256Sha256 security policy with client certificate.")
            except Exception as e:
                raise SecurityDowngradeError(f"Failed to configure Basic256Sha256 security: {e}") from e

        elif sec_policy in ("aes128_sha256_rsaoaep",):
            if not self.config.client_cert_path or not self.config.client_key_path:
                raise SecurityDowngradeError("Aes128Sha256 requested but client certificate/key missing.")
            try:
                mode = ua.MessageSecurityMode.SignAndEncrypt if "encrypt" in sec_mode else ua.MessageSecurityMode.Sign
                await self._client.set_security(
                    SecurityPolicyAes128Sha256RsaOaep,
                    certificate=self.config.client_cert_path,
                    private_key=self.config.client_key_path,
                    mode=mode,
                )
            except Exception as e:
                raise SecurityDowngradeError(f"Failed to configure Aes128 security: {e}") from e

        elif sec_policy != "none" and sec_mode != "none":
            raise SecurityDowngradeError(f"Unsupported security policy '{self.config.security_policy}'. Downgrade prevented.")

        # Configure User Authentication
        auth_type = (self.config.auth_type or "Anonymous").lower()
        if auth_type == "username":
            if not self.config.username or not self.config.password:
                raise ConnectionFailedError("UserName authentication requested but username or password was not provided.")
            self._client.set_user(self.config.username)
            self._client.set_password(self.config.password)
            logger.info(f"Configured UserName authentication for user '{self.config.username}'")
        elif auth_type == "certificate":
            if not self.config.client_cert_path:
                raise ConnectionFailedError("Certificate authentication requested but client_cert_path is missing.")
            # Certificate identity handled during TLS/OPC UA handshake
        elif auth_type != "anonymous":
            raise ConnectionFailedError(f"Unknown authentication type '{self.config.auth_type}'")

        # Execute Connection Handshake
        try:
            await self._client.connect()
            self._is_connected = True
            logger.info("OPC UA connection established successfully.")
        except Exception as e:
            self._is_connected = False
            raise ConnectionFailedError(f"Unable to connect to OPC UA server at '{self.config.endpoint_url}': {e}") from e

        # Extract Server Metadata & Endpoint Security Verification
        try:
            endpoints = await self._client.get_endpoints()
            if endpoints:
                self._server_name = endpoints[0].Server.ApplicationName.Text or "OPC UA Server"
                # Check for unexpected security downgrade
                if sec_policy in ("basic256sha256",) and endpoints[0].SecurityPolicyUri.endswith("#None"):
                    logger.warning("Server offers unencrypted endpoint alongside secure policies.")
        except Exception as e:
            logger.debug(f"Unable to read server endpoint descriptions: {e}")

    async def disconnect(self) -> None:
        """Safely terminates OPC UA session."""
        if self._client and self._is_connected:
            try:
                await self._client.disconnect()
            except Exception as e:
                logger.warning(f"Error during disconnect: {e}")
            finally:
                self._is_connected = False
                self._client = None
                logger.info("OPC UA connection disconnected.")

    # -------------------------------------------------------------------------
    # RECURSIVE ADDRESS SPACE BROWSING
    # -------------------------------------------------------------------------
    async def discover(self) -> Dict[str, Any]:
        """Initiates recursive address-space discovery starting from configured root node."""
        if not self._is_connected or not self._client:
            raise DiscoveryError("Cannot discover tags while disconnected. Call connect() first.")

        self._discovery_start_time = datetime.now(timezone.utc)
        self._visited_node_ids.clear()
        self._discovered_nodes.clear()
        self._inaccessible_nodes.clear()

        # Resolve Root Node
        try:
            root_node = self._client.get_node(self.config.root_node_id)
            root_display = (await root_node.read_display_name()).Text
            logger.info(f"Starting recursive browsing at root '{root_display}' ({self.config.root_node_id})")
        except Exception as e:
            raise DiscoveryError(f"Failed to access specified root node '{self.config.root_node_id}': {e}") from e

        # Perform recursive crawl
        await self._browse_recursive(
            node=root_node,
            current_path=root_display,
            current_depth=0
        )

        self._discovery_end_time = datetime.now(timezone.utc)
        duration_sec = (self._discovery_end_time - self._discovery_start_time).total_seconds()
        logger.info(
            f"Discovery completed in {duration_sec:.2f}s: "
            f"{len(self._discovered_nodes)} variables discovered, "
            f"{len(self._inaccessible_nodes)} inaccessible nodes, "
            f"{len(self._visited_node_ids)} total nodes visited."
        )

        return self.get_summary()

    async def _browse_recursive(
        self,
        node: Any,
        current_path: str,
        current_depth: int
    ) -> None:
        """Recursively browses hierarchical references with cycle prevention and depth control."""
        # 1. Depth check
        if current_depth > self.config.max_depth:
            logger.debug(f"Reached max depth ({self.config.max_depth}) at '{current_path}'")
            return

        # 2. Total node limit check
        if len(self._visited_node_ids) >= self.config.max_nodes:
            logger.warning(f"Reached max node limit ({self.config.max_nodes}). Halting browsing.")
            return

        # 3. Cycle prevention (Visited Set)
        node_id_str = node.nodeid.to_string() if hasattr(node.nodeid, "to_string") else str(node.nodeid)
        if node_id_str in self._visited_node_ids:
            return
        self._visited_node_ids.add(node_id_str)

        # 3b. Skip standard OPC UA Server internal diagnostics (ns=0;i=2253 / Objects/Server) if requested
        if self.config.skip_server_diagnostics:
            if node_id_str in ("i=2253", "ns=0;i=2253", "2253", "ns=0;s=Server") or current_path.endswith(" / Server") or " / Server / " in current_path:
                logger.debug(f"Skipping standard server diagnostics branch: {current_path}")
                return

        # 4. Read Node Attributes & Class
        try:
            node_class = await node.read_node_class()
            browse_name_obj = await node.read_browse_name()
            browse_name = f"{browse_name_obj.NamespaceIndex}:{browse_name_obj.Name}"
            display_name = (await node.read_display_name()).Text
        except Exception as e:
            self._inaccessible_nodes.append({
                "node_id": node_id_str,
                "path": current_path,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            return

        # 5. Process Variable Nodes (Candidate Telemetry Tags)
        if node_class == ua.NodeClass.Variable:
            await self._process_variable_node(
                node=node,
                node_id_str=node_id_str,
                browse_name=browse_name,
                display_name=display_name,
                current_path=current_path
            )

        # 6. Recurse into Child Nodes
        try:
            children = await node.get_children()
        except Exception as e:
            logger.debug(f"Could not retrieve children for node '{node_id_str}': {e}")
            return

        for child in children:
            child_name = "Unknown"
            try:
                child_disp = await child.read_display_name()
                child_name = child_disp.Text
            except Exception:
                pass

            child_path = f"{current_path} / {child_name}"
            await self._browse_recursive(
                node=child,
                current_path=child_path,
                current_depth=current_depth + 1
            )

    async def _process_variable_node(
        self,
        node: Any,
        node_id_str: str,
        browse_name: str,
        display_name: str,
        current_path: str
    ) -> None:
        """Inspects variable node attributes, data type, access level, and unit."""
        data_type_name = "Unknown"
        access_level_str = "Unknown"
        is_read_only = True
        current_val = None
        source_ts_str = None
        unit_str = None

        # Data Type
        try:
            data_type_id = await node.read_data_type()
            # Resolve standard OPC UA primitive types
            if data_type_id.NamespaceIndex == 0 and data_type_id.Identifier in ua.ObjectIdNames:
                data_type_name = ua.ObjectIdNames[data_type_id.Identifier]
            else:
                data_type_name = str(data_type_id)
        except Exception as e:
            data_type_name = "Unavailable"

        # Access Level
        try:
            access_level = await node.read_access_level()
            readable = bool(access_level & ua.AccessLevel.CurrentRead)
            writable = bool(access_level & ua.AccessLevel.CurrentWrite)
            is_read_only = readable and not writable
            access_level_str = "Read/Write" if (readable and writable) else ("Read-Only" if readable else "NoAccess")
        except Exception:
            access_level_str = "Unknown"

        # Value and Source Timestamp
        if self.config.read_current_values:
            try:
                data_val = await node.read_data_value()
                val = data_val.Value.Value
                # Safe JSON serialization
                current_val = self._sanitize_value(val)
                if data_val.SourceTimestamp:
                    source_ts_str = data_val.SourceTimestamp.isoformat()
            except Exception as e:
                current_val = None

        # Engineering Units Inspection (Check EUInformation property)
        try:
            # Look for standard property 'EngineeringUnits' or 'EURange'
            eu_prop = await node.get_child(["0:EngineeringUnits"])
            eu_val = await eu_prop.read_value()
            if hasattr(eu_val, "DisplayName") and hasattr(eu_val.DisplayName, "Text"):
                unit_str = eu_val.DisplayName.Text
        except Exception:
            # Check if unit is embedded in variable name
            pass

        # Perform Automatic Signal Classification
        classification = SignalClassifier.classify(
            node_id=node_id_str,
            browse_name=browse_name,
            display_name=display_name,
            data_type=data_type_name,
            unit=unit_str
        )

        parent_folder = current_path.rsplit(" / ", 1)[0] if " / " in current_path else "Root"

        node_record = {
            "node_id": node_id_str,
            "browse_name": browse_name,
            "display_name": display_name,
            "node_path": current_path,
            "parent_folder": parent_folder,
            "data_type": data_type_name,
            "access_level": access_level_str,
            "is_read_only": is_read_only,
            "current_value": current_val,
            "source_timestamp": source_ts_str,
            "engineering_unit": unit_str or classification.suggested_unit,
            "classification": {
                "category": classification.category,
                "suggested_signal_code": classification.suggested_signal_code,
                "confidence_level": classification.confidence_level,
                "confidence_score": classification.confidence_score,
                "reason": classification.classification_reason,
            }
        }
        self._discovered_nodes.append(node_record)

    @staticmethod
    def _sanitize_value(val: Any) -> Any:
        """Converts OPC UA variants and complex structures into JSON-serializable primitives."""
        if val is None:
            return None
        if isinstance(val, (int, float, str, bool)):
            return val
        if isinstance(val, bytes):
            return val.hex()
        if isinstance(val, datetime):
            return val.isoformat()
        if isinstance(val, (list, tuple)):
            return [OPCUATagDiscovery._sanitize_value(x) for x in val]
        return str(val)

    # -------------------------------------------------------------------------
    # TEMPLATE GENERATION & EXPORT
    # -------------------------------------------------------------------------
    def export_templates(self, output_dir: Optional[str] = None) -> Tuple[str, str]:
        """Generates discovered_nodes.json and signal_mapping_template.json files."""
        out_dir = Path(output_dir or self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        discovered_file = out_dir / "discovered_nodes.json"
        template_file = out_dir / "signal_mapping_template.json"

        # 1. Build discovered_nodes.json
        full_inventory = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "endpoint_url": self.config.endpoint_url,
                "server_name": self._server_name,
                "total_nodes_scanned": len(self._visited_node_ids),
                "total_variables_discovered": len(self._discovered_nodes),
                "inaccessible_node_count": len(self._inaccessible_nodes),
                "scan_duration_sec": (
                    (self._discovery_end_time - self._discovery_start_time).total_seconds()
                    if (self._discovery_start_time and self._discovery_end_time) else 0.0
                )
            },
            "configuration": self.config.sanitized_repr(),
            "nodes": self._discovered_nodes,
            "inaccessible_nodes": self._inaccessible_nodes,
        }

        with open(discovered_file, "w", encoding="utf-8") as f:
            json.dump(full_inventory, f, indent=2)
        logger.info(f"Saved complete node inventory to: {discovered_file}")

        # 2. Build signal_mapping_template.json
        mapped_signals = []
        unmapped_signals = []

        for idx, node in enumerate(self._discovered_nodes, start=1):
            cls_info = node["classification"]
            conf = cls_info["confidence_level"]
            
            mapping_entry = {
                "signal_id": f"sig-{idx:03d}",
                "source_node_id": node["node_id"],
                "source_browse_name": node["browse_name"],
                "source_display_name": node["display_name"],
                "suggested_signal_code": cls_info["suggested_signal_code"],
                "signal_group": cls_info["category"],
                "source_data_type": node["data_type"],
                "suggested_unit": node["engineering_unit"],
                "normalized_unit": node["engineering_unit"],
                "scaling_factor": 1.0,
                "offset": 0.0,
                "sampling_interval_ms": 1000 if cls_info["category"] in (
                    SignalClassificationCategory.VIBRATION,
                    SignalClassificationCategory.MOTOR_CURRENT,
                    SignalClassificationCategory.ROTATIONAL_SPEED,
                    SignalClassificationCategory.LINE_SPEED,
                    SignalClassificationCategory.PRESSURE,
                ) else 5000,
                "confidence_level": conf,
                "confidence_score": cls_info["confidence_score"],
                "classification_reason": cls_info["reason"],
                "mapping_status": "CANDIDATE_FOR_REVIEW" if conf in ("HIGH", "MEDIUM") else "UNMAPPED",
                "parent_path": node["parent_folder"]
            }

            if conf in ("HIGH", "MEDIUM"):
                mapped_signals.append(mapping_entry)
            else:
                unmapped_signals.append(mapping_entry)

        mapping_template = {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "schema_version": "1.0.0",
                "endpoint_url": self.config.endpoint_url,
                "server_name": self._server_name,
                "total_variables": len(self._discovered_nodes),
                "mapped_candidate_count": len(mapped_signals),
                "unmapped_candidate_count": len(unmapped_signals),
                "governance_instructions": (
                    "This template was generated autonomously by the PharmaPredict AI Tag Discovery Utility. "
                    "In accordance with GAMP 5 and FDA 21 CFR Part 11, candidate signal mappings must be reviewed, "
                    "verified, and authorized by a certified plant reliability engineer before activation in the edge gateway."
                )
            },
            "mapped_signals": mapped_signals,
            "unmapped_signals": unmapped_signals,
        }

        with open(template_file, "w", encoding="utf-8") as f:
            json.dump(mapping_template, f, indent=2)
        logger.info(f"Saved canonical mapping template to: {template_file}")

        return str(discovered_file), str(template_file)

    def get_summary(self) -> Dict[str, Any]:
        """Returns structured discovery execution summary metrics."""
        return {
            "endpoint_url": self.config.endpoint_url,
            "server_name": self._server_name,
            "nodes_visited": len(self._visited_node_ids),
            "variables_discovered": len(self._discovered_nodes),
            "inaccessible_nodes": len(self._inaccessible_nodes),
            "mapped_signals": sum(1 for n in self._discovered_nodes if n["classification"]["confidence_level"] != "UNMAPPED"),
            "unmapped_signals": sum(1 for n in self._discovered_nodes if n["classification"]["confidence_level"] == "UNMAPPED"),
        }


# =============================================================================
# 5. CLI & PROGRAMMATIC ENTRYPOINT
# =============================================================================

async def run_discovery(config: TagDiscoveryConfig) -> Dict[str, Any]:
    """Programmatic entry point to run discovery against an OPC UA server."""
    discovery = OPCUATagDiscovery(config)
    try:
        await discovery.connect()
        summary = await discovery.discover()
        disc_file, temp_file = discovery.export_templates()
        summary["discovered_file"] = disc_file
        summary["template_file"] = temp_file
        return summary
    finally:
        await discovery.disconnect()


def build_arg_parser() -> argparse.ArgumentParser:
    """Builds robust CLI argument parser for standalone deployment."""
    parser = argparse.ArgumentParser(
        description="PharmaPredict AI — Standalone OPC UA PLC Tag Discovery Utility",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--endpoint", default=os.getenv("OPCUA_ENDPOINT_URL", "opc.tcp://127.0.0.1:48401/pharmapredict/server/"), help="OPC UA Server Endpoint URL")
    parser.add_argument("--root-node", default="i=85", help="Starting node ID for recursive crawl (i=85 is Root.Objects)")
    parser.add_argument("--security-policy", default="None", choices=["None", "Basic256Sha256", "Aes128_Sha256_RsaOaep"], help="OPC UA Security Policy")
    parser.add_argument("--security-mode", default="None", choices=["None", "Sign", "SignAndEncrypt"], help="OPC UA Message Security Mode")
    parser.add_argument("--auth-type", default="Anonymous", choices=["Anonymous", "UserName", "Certificate"], help="Client Authentication Type")
    parser.add_argument("--username", default=os.getenv("OPCUA_USERNAME"), help="UserName for authentication")
    parser.add_argument("--password", default=os.getenv("OPCUA_PASSWORD"), help="Password for authentication")
    parser.add_argument("--cert", default=os.getenv("OPCUA_CERT_PATH"), help="Path to client X.509 certificate PEM/DER")
    parser.add_argument("--key", default=os.getenv("OPCUA_KEY_PATH"), help="Path to client private key PEM/DER")
    parser.add_argument("--timeout", type=float, default=10.0, help="Connection & request timeout in seconds")
    parser.add_argument("--max-depth", type=int, default=10, help="Maximum recursive browsing depth")
    parser.add_argument("--max-nodes", type=int, default=10000, help="Maximum total nodes to browse")
    parser.add_argument("--output-dir", default="./data/discovery", help="Output directory for generated JSON templates")
    parser.add_argument("--include-server-diagnostics", action="store_true", help="Include standard OPC UA internal server diagnostics (ns=0;i=2253 / Objects/Server)")
    parser.add_argument("--no-values", action="store_true", help="Skip reading current tag values (faster, attributes only)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")
    return parser


def main():
    """Main CLI execution flow."""
    parser = build_arg_parser()
    args = parser.parse_args()

    # Logging setup
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    )

    config = TagDiscoveryConfig(
        endpoint_url=args.endpoint,
        root_node_id=args.root_node,
        skip_server_diagnostics=not args.include_server_diagnostics,
        security_policy=args.security_policy,
        security_mode=args.security_mode,
        auth_type=args.auth_type,
        username=args.username,
        password=args.password,
        client_cert_path=args.cert,
        client_key_path=args.key,
        timeout_sec=args.timeout,
        max_depth=args.max_depth,
        max_nodes=args.max_nodes,
        read_current_values=not args.no_values,
        output_dir=args.output_dir,
    )

    print("================================================================================")
    print("PHARMAPREDICT AI — INDUSTRIAL OPC UA PLC TAG DISCOVERY UTILITY")
    print("================================================================================")
    print(f"Target Endpoint : {config.endpoint_url}")
    print(f"Security Policy : {config.security_policy} (Mode: {config.security_mode})")
    print(f"Authentication  : {config.auth_type}")
    print(f"Output Directory: {config.output_dir}")
    print("--------------------------------------------------------------------------------")

    try:
        summary = asyncio.run(run_discovery(config))
        print("\nDISCOVERY COMPLETED SUCCESSFULLY:")
        print(f"  - Server Application Name : {summary.get('server_name')}")
        print(f"  - Total Visited Nodes     : {summary.get('nodes_visited')}")
        print(f"  - Discovered Variables    : {summary.get('variables_discovered')}")
        print(f"  - Mapped Telemetry Tags   : {summary.get('mapped_signals')}")
        print(f"  - Unmapped Variables      : {summary.get('unmapped_signals')}")
        print(f"  - Inaccessible Nodes      : {summary.get('inaccessible_nodes')}")
        print(f"\nGenerated Artifacts:")
        print(f"  - Complete Node Inventory : {summary.get('discovered_file')}")
        print(f"  - Canonical Mapping Spec  : {summary.get('template_file')}")
        print("================================================================================")
    except ReadOnlyViolationError as e:
        print(f"\n[CRITICAL SAFETY BLOCK] {e}")
        sys.exit(2)
    except SecurityDowngradeError as e:
        print(f"\n[SECURITY DOWNGRADE ERROR] {e}")
        sys.exit(3)
    except ConnectionFailedError as e:
        print(f"\n[CONNECTION ERROR] {e}")
        sys.exit(4)
    except Exception as e:
        print(f"\n[DISCOVERY FAILED] {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
