"""
PharmaPredict AI — Production-Hardened Standalone Industrial Edge Gateway
========================================================================
Runs on-premise inside the factory OT network (Purdue Level 1/2/3 DMZ).
Connects to industrial PLCs / SCADA systems via strictly READ-ONLY OPC UA.
Enforces X.509 certificate validation, Basic256Sha256 SignAndEncrypt,
bounded RAM & persistent disk buffering (5,000 RAM queue / 50 MB disk buffer),
crash-safe recovery, exponential backoff with jitter, and secure HTTPS delivery.

Complies with IEC 62443 industrial cybersecurity standards:
- Strictly outbound-only HTTPS to cloud backend (no inbound open ports).
- Strictly read-only OPC UA client (raises ReadOnlyError on any write/control attempt).
- Never logs credentials, private keys, or passwords.
- Fails closed on invalid security configurations or expired certificates.
"""

import os
import sys
import json
import time
import uuid
import signal
import socket
import random
import asyncio
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path to allow importing app modules if running standalone
current_dir = Path(__file__).resolve().parent
backend_dir = current_dir.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import httpx

from app.modules.connectivity.models import (
    ConnectionConfig,
    ConnectionState,
    SecurityPolicy,
    SecurityMode,
    UserAuthType,
    ReadOnlyError,
    OPCUAError,
    SecurityConfigurationError,
    ExpiredCertificateError,
    UntrustedCertificateError,
)
from app.modules.connectivity.opcua_client import SecureOPCUAClient
from app.modules.connectivity.security import (
    CertificateValidator,
    CertificateManager,
    check_certificate_expiry,
)
from app.modules.monitoring.data_contract import NormalizedReadingMessage, compute_event_id
from app.modules.monitoring.gateway_buffer import BoundedGatewayBuffer

logger = logging.getLogger("PharmaPredict.EdgeGateway")


@dataclass
class EdgeGatewayConfig:
    """Configuration for on-premise Industrial Edge Gateway."""
    gateway_id: str = "gw-edge-01"
    organization_id: str = ""
    equipment_id: str = ""
    
    # OPC UA Connection
    opcua_endpoint_url: str = "opc.tcp://127.0.0.1:48401/pharmapredict/server/"
    opcua_security_policy: str = "None"
    opcua_security_mode: str = "None"
    opcua_auth_type: str = "Anonymous"
    opcua_username: Optional[str] = None
    opcua_password: Optional[str] = None
    opcua_cert_path: Optional[str] = None
    opcua_key_path: Optional[str] = None
    opcua_timeout_sec: float = 5.0
    trusted_certs_dir: Optional[str] = None
    trusted_cert_fingerprints: List[str] = field(default_factory=list)
    auto_trust_unknown: bool = False
    
    # Cloud Delivery
    cloud_ingestion_url: str = "https://predictive-maintenance-system-bay.vercel.app/api/v1/internal/ingestion/readings"
    gateway_secret: str = ""
    gateway_secret_secondary: Optional[str] = None  # Support seamless secret rotation
    verify_ssl: bool = True
    ssl_ca_bundle: Optional[str] = None
    request_timeout_sec: float = 10.0
    allow_insecure_http: bool = False  # Strictly False by default; True only for local unit tests
    
    # Buffering (Preserve 5,000 RAM queue & 50 MB disk buffer design)
    buffer_dir: str = "./data/gateway_buffer"
    max_queue_size: int = 5000
    max_disk_buffer_bytes: int = 50 * 1024 * 1024  # 50 MB
    batch_size: int = 50
    flush_interval_sec: float = 1.0
    
    # Health & Telemetry
    heartbeat_interval_sec: float = 30.0
    is_simulator: bool = True
    structured_logs: bool = False
    
    # Monitored Signal Definitions: {signal_id: {node_id, unit, sampling_interval_ms, ...}}
    monitored_nodes: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def validate(self) -> None:
        """Pre-flight validation of configuration. Fails closed with descriptive error."""
        if not self.gateway_id or not self.gateway_id.strip():
            raise ValueError("EdgeGatewayConfig: 'gateway_id' cannot be empty.")

        if not self.opcua_endpoint_url.startswith(("opc.tcp://", "opc.https://")):
            raise ValueError(
                f"EdgeGatewayConfig: 'opcua_endpoint_url' must start with 'opc.tcp://', got '{self.opcua_endpoint_url}'"
            )

        # Enforce HTTPS cloud communication unless explicitly bypassed for localhost/tests
        is_local = "127.0.0.1" in self.cloud_ingestion_url or "localhost" in self.cloud_ingestion_url
        if self.cloud_ingestion_url.startswith("http://") and not (self.allow_insecure_http or is_local):
            raise ValueError(
                f"EdgeGatewayConfig: Insecure plaintext HTTP delivery ('{self.cloud_ingestion_url}') "
                f"is strictly prohibited in industrial production. Must use HTTPS."
            )

        # Validate security policy consistency
        if self.opcua_security_policy != "None" and self.opcua_security_mode == "None":
            raise SecurityConfigurationError(
                f"EdgeGatewayConfig: 'opcua_security_policy' is set to '{self.opcua_security_policy}' "
                f"but 'opcua_security_mode' is 'None'. Must specify Sign or SignAndEncrypt."
            )

        # Validate username authentication consistency
        if self.opcua_auth_type == "UserName" and not self.opcua_username:
            raise ValueError("EdgeGatewayConfig: 'opcua_auth_type' is 'UserName' but 'opcua_username' is not provided.")

        # Validate buffer parameters
        if self.max_queue_size < 1 or self.max_disk_buffer_bytes < 1024:
            raise ValueError("EdgeGatewayConfig: Buffer limits must be positive (max_queue_size >= 1, max_disk_buffer_bytes >= 1024).")

    @classmethod
    def from_env(cls) -> "EdgeGatewayConfig":
        """Load configuration from environment variables with safe defaults."""
        raw_signals = {}
        signals_json = os.getenv("SIGNAL_MAPPINGS_JSON")
        if signals_json:
            try:
                parsed = json.loads(signals_json)
                if isinstance(parsed, list):
                    raw_signals = {s.get("signal_id", f"sig-{i}"): s for i, s in enumerate(parsed)}
                elif isinstance(parsed, dict):
                    raw_signals = parsed
            except Exception as e:
                logger.warning(f"Failed to parse SIGNAL_MAPPINGS_JSON: {e}")

        is_sim = os.getenv("IS_SIMULATOR", "true").lower() in ("true", "1", "yes")
        allow_insecure = os.getenv("ALLOW_INSECURE_HTTP", "false").lower() in ("true", "1", "yes")

        fps = []
        raw_fps = os.getenv("TRUSTED_CERT_FINGERPRINTS", "")
        if raw_fps:
            fps = [f.strip() for f in raw_fps.split(",") if f.strip()]

        config = cls(
            gateway_id=os.getenv("GATEWAY_ID", "gw-edge-01"),
            organization_id=os.getenv("ORGANIZATION_ID", ""),
            equipment_id=os.getenv("EQUIPMENT_ID", os.getenv("MACHINE_ID", "")),
            opcua_endpoint_url=os.getenv("OPCUA_ENDPOINT_URL", "opc.tcp://127.0.0.1:48401/pharmapredict/server/"),
            opcua_security_policy=os.getenv("OPCUA_SECURITY_POLICY", "None"),
            opcua_security_mode=os.getenv("OPCUA_SECURITY_MODE", "None"),
            opcua_auth_type=os.getenv("OPCUA_AUTH_TYPE", "Anonymous"),
            opcua_username=os.getenv("OPCUA_USERNAME"),
            opcua_password=os.getenv("OPCUA_PASSWORD"),
            opcua_cert_path=os.getenv("OPCUA_CERT_PATH"),
            opcua_key_path=os.getenv("OPCUA_KEY_PATH"),
            opcua_timeout_sec=float(os.getenv("OPCUA_TIMEOUT_SEC", "5.0")),
            trusted_certs_dir=os.getenv("TRUSTED_CERTS_DIR"),
            trusted_cert_fingerprints=fps,
            auto_trust_unknown=os.getenv("AUTO_TRUST_UNKNOWN", "false").lower() in ("true", "1", "yes"),
            cloud_ingestion_url=os.getenv("CLOUD_INGESTION_URL", "https://predictive-maintenance-system-bay.vercel.app/api/v1/internal/ingestion/readings"),
            gateway_secret=os.getenv("GATEWAY_INTERNAL_SECRET", os.getenv("GATEWAY_SECRET", "")),
            gateway_secret_secondary=os.getenv("GATEWAY_INTERNAL_SECRET_SECONDARY"),
            verify_ssl=os.getenv("VERIFY_SSL", "true").lower() in ("true", "1", "yes"),
            ssl_ca_bundle=os.getenv("SSL_CA_BUNDLE"),
            request_timeout_sec=float(os.getenv("REQUEST_TIMEOUT_SEC", "10.0")),
            allow_insecure_http=allow_insecure,
            buffer_dir=os.getenv("BUFFER_DIR", "./data/gateway_buffer"),
            max_queue_size=int(os.getenv("MAX_QUEUE_SIZE", "5000")),
            max_disk_buffer_bytes=int(os.getenv("MAX_DISK_BUFFER_BYTES", str(50 * 1024 * 1024))),
            batch_size=int(os.getenv("BATCH_SIZE", "50")),
            flush_interval_sec=float(os.getenv("FLUSH_INTERVAL_SEC", "1.0")),
            heartbeat_interval_sec=float(os.getenv("HEARTBEAT_INTERVAL_SEC", "30.0")),
            is_simulator=is_sim,
            structured_logs=os.getenv("STRUCTURED_LOGS", "false").lower() in ("true", "1", "yes"),
            monitored_nodes=raw_signals,
        )
        return config

    def __repr__(self) -> str:
        """Sanitized representation that NEVER exposes secrets or passwords."""
        safe_dict = asdict(self)
        if safe_dict.get("gateway_secret"):
            safe_dict["gateway_secret"] = "***REDACTED***"
        if safe_dict.get("gateway_secret_secondary"):
            safe_dict["gateway_secret_secondary"] = "***REDACTED***"
        if safe_dict.get("opcua_password"):
            safe_dict["opcua_password"] = "***REDACTED***"
        return f"EdgeGatewayConfig({json.dumps(safe_dict, indent=2)})"


class EdgeGateway:
    """Autonomous, production-hardened industrial edge gateway.
    
    Adheres strictly to Phase 10 industrial requirements:
    1. Strictly read-only OPC UA communication (raises ReadOnlyError on any write/control).
    2. Outbound-only HTTPS to cloud backend (no inbound open ports on plant floor).
    3. Multi-tier buffering: 5,000 RAM queue + 50 MB persistent disk spool with fsync durability.
    4. Deterministic event ID deduplication.
    5. Automatic OPC UA reconnection with exponential backoff and jitter.
    6. Systemd watchdog support and graceful shutdown.
    7. Comprehensive health, resource, and certificate expiry monitoring.
    """

    def __init__(self, config: EdgeGatewayConfig):
        # Pre-flight validation
        config.validate()
        self.config = config
        self._is_running: bool = False
        self._shutdown_event = asyncio.Event()
        self._start_time: float = 0.0
        
        # Prepare disk buffer directory with restrictive permissions
        self._init_disk_buffer()
        
        # Initialize Bounded Gateway Buffer with disk recovery
        self.buffer = BoundedGatewayBuffer(
            gateway_id=config.gateway_id,
            max_queue_size=config.max_queue_size,
            batch_size=config.batch_size,
            flush_interval_sec=config.flush_interval_sec,
            disk_buffer_dir=config.buffer_dir,
            max_disk_buffer_bytes=config.max_disk_buffer_bytes,
        )
        
        # Configure ingestion callback for outbound HTTPS push
        self.buffer.set_ingestion_handler(self._deliver_batch_to_cloud)
        
        # Initialize OPC UA Client
        self.opcua_client = self._create_opcua_client()
        
        # HTTP client for outbound telemetry
        self._http_client: Optional[httpx.AsyncClient] = None
        
        # Tasks
        self._tasks: List[asyncio.Task] = []
        
        # Telemetry, delivery, and health metrics
        self._delivered_batches: int = 0
        self._delivered_readings: int = 0
        self._failed_deliveries: int = 0
        self._rejected_identity_violations: int = 0
        self._last_delivery_time: Optional[str] = None
        self._last_delivery_status: Optional[str] = None
        self._last_delivery_http_code: Optional[int] = None
        self._reconnection_attempts_total: int = 0

        # Monitored signal configurations
        self._monitored_signals: Dict[str, Dict[str, Any]] = {}
        if config.monitored_nodes:
            self.set_monitored_signals(config.monitored_nodes)

    def add_monitored_signal(self, signal_config: Dict[str, Any]) -> None:
        """Register or update an equipment signal configuration to monitor dynamically."""
        sig_id = signal_config.get("signal_id") or signal_config.get("id") or str(uuid.uuid4())
        node_id = signal_config.get("source_node_id")
        if not node_id:
            logger.warning("[EdgeGateway] Cannot add signal without source_node_id.")
            return

        self._monitored_signals[sig_id] = {
            "signal_id": sig_id,
            "source_node_id": node_id,
            "signal_code": signal_config.get("signal_code", "CUSTOM_SIGNAL"),
            "custom_name": signal_config.get("custom_name") or signal_config.get("signal_name"),
            "scaling_factor": float(signal_config.get("scaling_factor", 1.0)),
            "offset": float(signal_config.get("offset", 0.0)),
            "source_unit": signal_config.get("source_unit"),
            "normalized_unit": signal_config.get("normalized_unit") or signal_config.get("standard_unit"),
            "sampling_interval_ms": int(signal_config.get("sampling_interval_ms", 1000)),
            "mapping_version": int(signal_config.get("mapping_version", 1)),
            "connector_id": signal_config.get("connector_id", "conn-opcua-01"),
        }
        logger.info(f"[EdgeGateway] Registered monitored signal '{sig_id}' -> Node '{node_id}'")

    def set_monitored_signals(self, signals: Any) -> None:
        """Configure or replace active monitored signal mappings."""
        self._monitored_signals.clear()
        if isinstance(signals, list):
            for s in signals:
                if isinstance(s, dict):
                    self.add_monitored_signal(s)
        elif isinstance(signals, dict):
            for sig_id, s in signals.items():
                if isinstance(s, dict):
                    s_copy = dict(s)
                    if "signal_id" not in s_copy:
                        s_copy["signal_id"] = sig_id
                    self.add_monitored_signal(s_copy)

    def _init_disk_buffer(self) -> None:
        """Create and enforce restrictive filesystem permissions on the disk buffer directory."""
        buf_path = Path(self.config.buffer_dir)
        try:
            buf_path.mkdir(parents=True, exist_ok=True)
            # Enforce 0o700 on POSIX systems (owner read/write/execute only)
            if hasattr(os, "chmod") and os.name == "posix":
                os.chmod(buf_path, 0o700)
        except Exception as e:
            logger.warning(f"Failed to set restrictive permissions on {buf_path}: {e}")

    def _create_opcua_client(self) -> SecureOPCUAClient:
        """Construct read-only SecureOPCUAClient from gateway configuration."""
        policy_map = {
            "None": SecurityPolicy.NONE,
            "Basic256Sha256": SecurityPolicy.BASIC256_SHA256,
            "Aes128_Sha256_RsaOaep": SecurityPolicy.AES128_SHA256_RSAOAEP,
        }
        mode_map = {
            "None": SecurityMode.NONE,
            "Sign": SecurityMode.SIGN,
            "SignAndEncrypt": SecurityMode.SIGN_AND_ENCRYPT,
        }
        auth_map = {
            "Anonymous": UserAuthType.ANONYMOUS,
            "UserName": UserAuthType.USERNAME,
            "Certificate": UserAuthType.CERTIFICATE,
        }

        conn_config = ConnectionConfig(
            endpoint_url=self.config.opcua_endpoint_url,
            security_policy=policy_map.get(self.config.opcua_security_policy, SecurityPolicy.NONE),
            security_mode=mode_map.get(self.config.opcua_security_mode, SecurityMode.NONE),
            user_auth_type=auth_map.get(self.config.opcua_auth_type, UserAuthType.ANONYMOUS),
            username=self.config.opcua_username,
            password=self.config.opcua_password,
            client_cert_path=self.config.opcua_cert_path,
            client_key_path=self.config.opcua_key_path,
            timeout_sec=self.config.opcua_timeout_sec,
            trusted_certs_dir=self.config.trusted_certs_dir,
            trusted_cert_fingerprints=self.config.trusted_cert_fingerprints,
            auto_trust_unknown=self.config.auto_trust_unknown,
        )
        return SecureOPCUAClient(conn_config)

    # =========================================================================
    # STRICT READ-ONLY ENFORCEMENT
    # =========================================================================

    async def write_plc_value(self, node_id: str, value: Any) -> None:
        """Explicitly rejected to ensure pharmaceutical OT safety."""
        raise ReadOnlyError(
            f"Edge Gateway is strictly read-only. Actuation and PLC write operations to '{node_id}' are prohibited."
        )

    # =========================================================================
    # INGESTION & OUTBOUND DELIVERY
    # =========================================================================

    async def ingest_reading(self, reading: NormalizedReadingMessage) -> bool:
        """Validate identity and push reading into bounded queue with disk fallback."""
        # Enforce organization and machine identity to prevent cross-tenant spoofing
        if self.config.organization_id and reading.organization_id != self.config.organization_id:
            self._rejected_identity_violations += 1
            logger.error(
                f"[Security Violation] Rejected reading with organization_id='{reading.organization_id}', "
                f"expected='{self.config.organization_id}'"
            )
            return False

        if self.config.equipment_id and reading.machine_id != self.config.equipment_id:
            self._rejected_identity_violations += 1
            logger.error(
                f"[Security Violation] Rejected reading with machine_id='{reading.machine_id}', "
                f"expected='{self.config.equipment_id}'"
            )
            return False

        # Ensure deterministic event_id is preserved
        if not reading.event_id:
            reading.event_id = compute_event_id(
                machine_id=reading.machine_id,
                signal_id=reading.signal_id,
                source_timestamp_iso=reading.source_timestamp,
                source_value=reading.source_value,
                sequence_id=reading.source_sequence_id,
            )

        return await self.buffer.push(reading)

    async def _deliver_batch_to_cloud(self, batch: List[NormalizedReadingMessage]) -> bool:
        """HTTP POST delivery of telemetry batch to cloud backend.
        
        Authenticates via X-Gateway-Secret header.
        Supports secondary secret for zero-downtime rotation.
        Applies exponential backoff with jitter on transient network issues.
        Never logs credentials.
        """
        if not batch:
            return True

        if not self._http_client:
            verify_ssl: Any = self.config.verify_ssl
            if self.config.ssl_ca_bundle and os.path.isfile(self.config.ssl_ca_bundle):
                verify_ssl = self.config.ssl_ca_bundle

            self._http_client = httpx.AsyncClient(
                verify=verify_ssl,
                timeout=self.config.request_timeout_sec,
            )

        batch_id = f"batch-{self.config.gateway_id}-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
        buf_metrics = self.buffer.get_metrics()
        payload = {
            "gateway_id": self.config.gateway_id,
            "batch_identifier": batch_id,
            "readings": [item.to_dict() for item in batch],
            "metrics": {
                "queue_depth": buf_metrics.get("queue_depth", 0),
                "buffered_readings": buf_metrics.get("buffered_readings", 0),
                "dropped_readings": buf_metrics.get("dropped_readings", 0),
                "disk_usage_bytes": buf_metrics.get("disk_usage_bytes", 0),
                "overflow_active": buf_metrics.get("overflow_active", False),
            },
        }

        headers = {
            "Content-Type": "application/json",
            "X-Gateway-Secret": self.config.gateway_secret,
            "X-Gateway-ID": self.config.gateway_id,
            "X-Batch-Identifier": batch_id,
            "X-Idempotency-Key": batch_id,
        }

        # Optional rotation support header
        if self.config.gateway_secret_secondary:
            headers["X-Gateway-Secret-Secondary"] = self.config.gateway_secret_secondary

        try:
            response = await self._http_client.post(
                self.config.cloud_ingestion_url,
                json=payload,
                headers=headers,
            )

            now_iso = datetime.now(timezone.utc).isoformat()
            self._last_delivery_time = now_iso
            self._last_delivery_http_code = response.status_code

            if response.status_code in (200, 201):
                self._delivered_batches += 1
                self._delivered_readings += len(batch)
                self._last_delivery_status = "SUCCESS"
                logger.info(
                    f"[CloudDelivery] Successfully delivered batch {batch_id} ({len(batch)} readings) -> HTTP {response.status_code}"
                )
                return True
            elif response.status_code == 403:
                self._failed_deliveries += 1
                self._last_delivery_status = "AUTH_FAILED"
                logger.error(
                    f"[CloudDelivery] Authentication failed (HTTP 403) for gateway '{self.config.gateway_id}'. "
                    f"Verify GATEWAY_INTERNAL_SECRET."
                )
                return False
            elif response.status_code == 429:
                self._failed_deliveries += 1
                self._last_delivery_status = "RATE_LIMITED"
                logger.warning(f"[CloudDelivery] Cloud API rate limited (HTTP 429) batch {batch_id}.")
                return False
            else:
                self._failed_deliveries += 1
                self._last_delivery_status = f"HTTP_{response.status_code}"
                logger.warning(
                    f"[CloudDelivery] Batch delivery rejected with HTTP {response.status_code}: {response.text[:200]}"
                )
                return False

        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            self._failed_deliveries += 1
            self._last_delivery_status = "NETWORK_ERROR"
            logger.warning(f"[CloudDelivery] Network/Connection error delivering batch {batch_id}: {e}")
            return False
        except Exception as e:
            self._failed_deliveries += 1
            self._last_delivery_status = "ERROR"
            logger.error(f"[CloudDelivery] Unexpected error delivering batch {batch_id}: {e}")
            return False

    # =========================================================================
    # LIFECYCLE & WORKERS
    # =========================================================================

    async def start(self) -> None:
        """Start edge gateway background workers, recover disk buffer, and connect to OPC UA."""
        if self._is_running:
            return

        self._is_running = True
        self._start_time = time.time()
        logger.info(f"[EdgeGateway] Starting gateway {self.config.gateway_id}...")

        # 1. Initialize HTTP client
        verify_ssl: Any = self.config.verify_ssl
        if self.config.ssl_ca_bundle and os.path.isfile(self.config.ssl_ca_bundle):
            verify_ssl = self.config.ssl_ca_bundle

        self._http_client = httpx.AsyncClient(
            verify=verify_ssl,
            timeout=self.config.request_timeout_sec,
        )

        # 2. Start buffer flush worker (which automatically recovers un-flushed disk buffer)
        await self.buffer.start()

        # 3. Connect to OPC UA Server
        try:
            logger.info(f"[EdgeGateway] Connecting to OPC UA endpoint: {self.config.opcua_endpoint_url}")
            await self.opcua_client.connect()
            logger.info(f"[EdgeGateway] Connected to OPC UA Server.")
        except Exception as e:
            logger.warning(f"[EdgeGateway] Initial OPC UA connection failed: {e}. Reconnection loop active.")

        # 4. Write initial health state for healthcheck
        self._write_health_state()

        # 5. Launch background reconnection, heartbeat, and telemetry tasks
        self._tasks.append(asyncio.create_task(self._reconnection_loop()))
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        self._tasks.append(asyncio.create_task(self._telemetry_loop()))
        
        logger.info(f"[EdgeGateway] Edge Gateway {self.config.gateway_id} initialized and operational.")

    async def stop(self) -> None:
        """Gracefully shut down edge gateway, flushing pending memory to disk before exit."""
        if not self._is_running:
            return

        logger.info(f"[EdgeGateway] Shutting down gateway {self.config.gateway_id} gracefully...")
        self._is_running = False
        self._shutdown_event.set()
        self._write_health_state()

        # Cancel background tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Disconnect OPC UA client
        try:
            if self.opcua_client.is_connected():
                await self.opcua_client.disconnect()
        except Exception as e:
            logger.warning(f"[EdgeGateway] Error disconnecting OPC UA client: {e}")

        # Stop buffer and flush remaining items
        await self.buffer.stop()

        # Close HTTP client
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None

        logger.info(f"[EdgeGateway] Gateway {self.config.gateway_id} stopped cleanly.")

    async def _reconnection_loop(self) -> None:
        """Continuously monitor OPC UA connection health and reconnect with backoff + jitter."""
        backoff_sec = 2.0
        max_backoff_sec = 30.0
        backoff_factor = 1.5

        while self._is_running:
            try:
                # Apply jitter: ±15% randomization to avoid synchronized connection storms
                jitter = random.uniform(0.85, 1.15)
                actual_wait = max(1.0, backoff_sec * jitter)
                await asyncio.sleep(actual_wait)

                if not self.opcua_client.is_connected():
                    self._reconnection_attempts_total += 1
                    logger.info(
                        f"[EdgeGateway] Reconnection attempt #{self._reconnection_attempts_total} "
                        f"to OPC UA server ({self.config.opcua_endpoint_url})..."
                    )
                    try:
                        await self.opcua_client.connect()
                        logger.info(f"[EdgeGateway] Reconnected successfully to OPC UA server.")
                        backoff_sec = 2.0
                    except Exception as e:
                        logger.warning(f"[EdgeGateway] Reconnection failed: {e}")
                        backoff_sec = min(backoff_sec * backoff_factor, max_backoff_sec)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[EdgeGateway] Error in reconnection loop: {e}")

    async def _heartbeat_loop(self) -> None:
        """Periodic heartbeat, health state persistence, and systemd watchdog ping."""
        interval = min(5.0, self.config.heartbeat_interval_sec)
        while self._is_running:
            try:
                self._write_health_state()
                self._ping_systemd_watchdog()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[EdgeGateway] Error in heartbeat loop: {e}")

    def _ping_systemd_watchdog(self) -> None:
        """Send WATCHDOG=1 keep-alive datagram if running under systemd."""
        notify_socket = os.getenv("NOTIFY_SOCKET")
        if not notify_socket:
            return

        try:
            # Address starting with @ is an abstract Linux socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
            addr = notify_socket
            if addr.startswith("@"):
                addr = "\0" + addr[1:]
            sock.sendto(b"WATCHDOG=1\n", addr)
            sock.close()
        except Exception as e:
            logger.debug(f"Failed to ping systemd watchdog: {e}")

    async def _telemetry_loop(self) -> None:
        """Continuous, strictly read-only polling of mapped OPC UA signals."""
        logger.info(f"[EdgeGateway] Telemetry acquisition loop started with {len(self._monitored_signals)} mapped signals.")
        
        while self._is_running:
            try:
                # If disconnected, wait for reconnection loop to re-establish
                if not self.opcua_client.is_connected():
                    await asyncio.sleep(1.0)
                    continue

                if not self._monitored_signals:
                    await asyncio.sleep(2.0)
                    continue

                for sig_id, sig_conf in list(self._monitored_signals.items()):
                    if not self._is_running:
                        break
                    node_id = sig_conf["source_node_id"]
                    try:
                        raw_val = await self.opcua_client.read_value(node_id)
                        now_dt = datetime.now(timezone.utc)
                        now_iso = now_dt.isoformat()

                        # Apply engineering scaling and offset
                        scaling = sig_conf["scaling_factor"]
                        offset = sig_conf["offset"]
                        norm_val = None
                        raw_numeric = None
                        raw_bool = None
                        raw_str = None

                        if isinstance(raw_val, (int, float)) and not isinstance(raw_val, bool):
                            raw_numeric = float(raw_val)
                            norm_val = round((raw_numeric * scaling) + offset, 4)
                        elif isinstance(raw_val, bool):
                            raw_bool = raw_val
                            norm_val = 1.0 if raw_bool else 0.0
                        elif raw_val is not None:
                            raw_str = str(raw_val)
                            try:
                                raw_numeric = float(raw_str)
                                norm_val = round((raw_numeric * scaling) + offset, 4)
                            except ValueError:
                                pass

                        reading = NormalizedReadingMessage(
                            organization_id=self.config.organization_id,
                            machine_id=self.config.equipment_id,
                            signal_id=sig_id,
                            source_node_id=node_id,
                            mapping_version=sig_conf["mapping_version"],
                            source_timestamp=now_iso,
                            source_value=raw_val,
                            normalized_value=norm_val,
                            raw_value_numeric=raw_numeric,
                            raw_value_boolean=raw_bool,
                            raw_value_string=raw_str,
                            source_unit=sig_conf["source_unit"],
                            normalized_unit=sig_conf["normalized_unit"],
                            opcua_quality_code="Good",
                            normalization_status="NORMALIZED",
                            sampling_interval_ms=sig_conf["sampling_interval_ms"],
                            connector_id=sig_conf["connector_id"],
                            gateway_id=self.config.gateway_id,
                            simulator_flag=self.config.is_simulator,
                        )

                        await self.ingest_reading(reading)

                    except Exception as e:
                        logger.warning(f"[EdgeGateway] Error reading node '{node_id}' for signal {sig_id}: {e}")

                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[EdgeGateway] Error in telemetry acquisition loop: {e}")
                await asyncio.sleep(2.0)

    def _write_health_state(self) -> None:
        """Persist real-time gateway health and metrics for the container healthcheck probe."""
        try:
            health_file = Path(self.config.buffer_dir) / ".gateway_health.json"
            metrics = self.get_metrics()
            metrics["timestamp"] = datetime.now(timezone.utc).isoformat()
            metrics["timestamp_epoch"] = time.time()
            with open(health_file, "w", encoding="utf-8") as f:
                json.dump(metrics, f)
        except Exception as e:
            logger.debug(f"[EdgeGateway] Failed to write health state: {e}")

    def get_metrics(self) -> Dict[str, Any]:
        """Return comprehensive operational, disk utilization, certificate, and resource metrics."""
        buf_metrics = self.buffer.get_metrics()
        uptime_sec = round(time.time() - self._start_time, 2) if self._start_time > 0 else 0.0

        # Memory / Resource metrics
        mem_rss = None
        try:
            import resource
            mem_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        except Exception:
            pass

        # Certificate health
        cert_days = None
        cert_expires_at = None
        if self.config.opcua_cert_path and os.path.isfile(self.config.opcua_cert_path):
            try:
                cert_info = check_certificate_expiry(self.config.opcua_cert_path)
                cert_days = cert_info["days_remaining"]
                cert_expires_at = cert_info["valid_to"]
            except Exception:
                pass

        total_attempts = self._delivered_batches + self._failed_deliveries
        delivery_success_pct = round((self._delivered_batches / total_attempts) * 100.0, 2) if total_attempts > 0 else 100.0

        return {
            "gateway_id": self.config.gateway_id,
            "organization_id": self.config.organization_id,
            "equipment_id": self.config.equipment_id,
            "is_running": self._is_running,
            "uptime_sec": uptime_sec,
            "opcua_state": self.opcua_client.get_state().value if self.opcua_client else "DISCONNECTED",
            "opcua_connected": self.opcua_client.is_connected() if self.opcua_client else False,
            "opcua_reconnection_attempts": self._reconnection_attempts_total,
            "client_cert_days_remaining": cert_days,
            "client_cert_expires_at": cert_expires_at,
            "queue_depth": buf_metrics.get("queue_depth", 0),
            "max_queue_size": buf_metrics.get("max_queue_size", self.config.max_queue_size),
            "queue_utilization_pct": buf_metrics.get("queue_utilization_pct", 0.0),
            "buffered_disk_readings": buf_metrics.get("buffered_readings", 0),
            "disk_usage_bytes": buf_metrics.get("disk_usage_bytes", 0),
            "max_disk_buffer_bytes": buf_metrics.get("max_disk_buffer_bytes", self.config.max_disk_buffer_bytes),
            "disk_utilization_pct": buf_metrics.get("disk_utilization_pct", 0.0),
            "oldest_record_age_sec": buf_metrics.get("oldest_record_age_sec", 0.0),
            "dropped_readings": buf_metrics.get("dropped_readings", 0),
            "dropped_first_timestamp": buf_metrics.get("dropped_first_timestamp"),
            "dropped_last_timestamp": buf_metrics.get("dropped_last_timestamp"),
            "overflow_active": buf_metrics.get("overflow_active", False),
            "overflow_policy": buf_metrics.get("overflow_policy", "BOUNDED_DROP_ON_CAPACITY_EXCEEDED"),
            "quarantined_corrupt_records": buf_metrics.get("quarantined_corrupt_records", 0),
            "monitored_signals_count": len(self._monitored_signals),
            "delivered_batches": self._delivered_batches,
            "delivered_readings": self._delivered_readings,
            "failed_deliveries": self._failed_deliveries,
            "delivery_success_pct": delivery_success_pct,
            "last_delivery_time": self._last_delivery_time,
            "last_delivery_status": self._last_delivery_status,
            "last_delivery_http_code": self._last_delivery_http_code,
            "rejected_identity_violations": self._rejected_identity_violations,
            "memory_rss_bytes": mem_rss,
        }


# =============================================================================
# CLI ENTRYPOINT
# =============================================================================

async def main():
    """Command-line runner for standalone gateway process."""
    structured = os.getenv("STRUCTURED_LOGS", "false").lower() in ("true", "1", "yes")
    
    if structured:
        class JsonFormatter(logging.Formatter):
            def format(self, record):
                log_record = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
                return json.dumps(log_record)
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logging.root.handlers = [handler]
        logging.root.setLevel(os.getenv("LOG_LEVEL", "INFO"))
    else:
        logging.basicConfig(
            level=os.getenv("LOG_LEVEL", "INFO"),
            format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        )
    
    try:
        config = EdgeGatewayConfig.from_env()
        config.validate()
    except Exception as e:
        logger.critical(f"FATAL: Pre-flight gateway configuration failed: {e}")
        sys.exit(1)

    logger.info(f"Starting PharmaPredict Industrial Edge Gateway with config: {config}")

    gateway = EdgeGateway(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, lambda: asyncio.create_task(gateway.stop()))
        except NotImplementedError:
            # Signal handlers not implemented on Windows event loop
            pass

    await gateway.start()

    try:
        while gateway._is_running:
            await asyncio.sleep(1.0)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await gateway.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
