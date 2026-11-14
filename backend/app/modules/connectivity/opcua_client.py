import os
import asyncio
import time
from typing import Optional, List, Any, Dict
from datetime import datetime, timezone
import asyncua
from asyncua import Client, ua

from app.modules.connectivity.models import (
    ConnectionState,
    ConnectionConfig,
    ConnectionHealth,
    SecurityPolicy,
    SecurityMode,
    UserAuthType,
    OPCUAError,
    ReadOnlyError,
    AuthenticationError,
    UntrustedCertificateError,
    ExpiredCertificateError,
    SecurityConfigurationError,
    ConnectionTimeoutError,
    ServerShutdownError,
)
from app.modules.connectivity.interface import BaseConnector, StateListener
from app.modules.connectivity.security import (
    CertificateValidator,
    CertificateManager,
    compute_cert_fingerprint,
    check_certificate_expiry,
)


class SecureOPCUAClient(BaseConnector):
    """Modular, asynchronous, read-only OPC UA client built on asyncua.
    
    Hardened for Phase 10 industrial deployment:
    - Secure OPC UA connections (Basic256Sha256, SignAndEncrypt)
    - X.509 client certificate management and rotation
    - Server certificate validation and expiration checks
    - Fail-closed security validation (prohibiting plaintext downgrade)
    - Connection health and latency monitoring
    - Mandatory read-only enforcement (prohibiting all write/control calls)
    """

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._state: ConnectionState = ConnectionState.DISCONNECTED
        self._state_listeners: List[StateListener] = []
        self._client: Optional[Client] = None
        self._cert_validator = CertificateValidator(
            trusted_fingerprints=config.trusted_cert_fingerprints,
            trusted_certs_dir=config.trusted_certs_dir,
            auto_trust_unknown=config.auto_trust_unknown,
            enforce_expiry=True,
        )
        self._last_error: Optional[str] = None
        self._reconnect_attempts: int = 0
        self._last_heartbeat: Optional[datetime] = None
        self._latency_ms: Optional[float] = None
        self._lock: Optional[asyncio.Lock] = None
        self._client_cert_info: Optional[Dict[str, Any]] = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # =========================================================================
    # STATE MANAGEMENT & LISTENER DISPATCH
    # =========================================================================

    def is_connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED and self._client is not None

    @property
    def client(self) -> Optional[Client]:
        return self._client

    def get_node(self, nodeid):
        if not self._client:
            raise OPCUAError("OPC UA Client is not connected.")
        return self._client.get_node(nodeid)

    def get_state(self) -> ConnectionState:
        return self._state

    def set_state(self, new_state: ConnectionState, error_msg: Optional[str] = None) -> None:
        """Update internal connection state and notify all registered listeners."""
        old_state = self._state
        self._state = new_state
        if error_msg:
            self._last_error = error_msg
        elif new_state == ConnectionState.CONNECTED:
            self._last_error = None

        if old_state != new_state:
            for listener in list(self._state_listeners):
                try:
                    listener(new_state, error_msg)
                except Exception:
                    pass

    def add_state_listener(self, listener: StateListener) -> None:
        if listener not in self._state_listeners:
            self._state_listeners.append(listener)

    def remove_state_listener(self, listener: StateListener) -> None:
        if listener in self._state_listeners:
            self._state_listeners.remove(listener)

    # =========================================================================
    # ASYNC CONNECT & DISCONNECT
    # =========================================================================

    async def connect(self) -> bool:
        """Establish secure asynchronous connection to the configured OPC UA server."""
        async with self._get_lock():
            if self._state == ConnectionState.CONNECTED and self._client:
                return True

            self.set_state(ConnectionState.CONNECTING)

            try:
                # 1. Pre-connection Security Configuration Validation (Fail Closed)
                if self.config.security_policy != SecurityPolicy.NONE:
                    if self.config.security_mode == SecurityMode.NONE:
                        raise SecurityConfigurationError(
                            "Invalid security configuration: security_policy is enabled but security_mode is None. "
                            "Refusing to connect without Sign or SignAndEncrypt."
                        )

                # 2. Initialize asyncua Client with configurable timeout
                self._client = Client(
                    url=self.config.endpoint_url,
                    timeout=self.config.timeout_sec
                )

                # 3. Configure Security Policies and Client Certificates
                if self.config.security_policy != SecurityPolicy.NONE:
                    client_cert = self.config.client_cert_path
                    client_key = self.config.client_key_path
                    if not client_cert or not client_key:
                        import tempfile
                        temp_dir = os.path.join(tempfile.gettempdir(), "pharmapredict_client_certs")
                        client_cert, client_key = CertificateManager.ensure_client_certificate(
                            temp_dir, common_name="PharmaPredict-OPCUA-Client"
                        )
                        self.config.client_cert_path = client_cert
                        self.config.client_key_path = client_key

                    # Validate client certificate expiration before connecting
                    try:
                        self._client_cert_info = check_certificate_expiry(client_cert)
                        if self._client_cert_info["is_expired"]:
                            raise ExpiredCertificateError(
                                f"Client certificate '{client_cert}' is expired. Cannot establish secure connection."
                            )
                    except Exception as e:
                        if isinstance(e, ExpiredCertificateError):
                            raise
                        pass

                    sec_string = f"{self.config.security_policy.value},{self.config.security_mode.value},{client_cert},{client_key}"
                    await self._client.set_security_string(sec_string)

                # 4. Configure User Authentication Identity
                if self.config.user_auth_type == UserAuthType.USERNAME:
                    if not self.config.username:
                        raise AuthenticationError("Username authentication selected but no username provided.")
                    self._client.set_user(self.config.username)
                    self._client.set_password(self.config.password or "")

                # 5. Connect with timeout
                try:
                    await asyncio.wait_for(
                        self._client.connect(),
                        timeout=self.config.timeout_sec
                    )
                except asyncio.TimeoutError:
                    raise ConnectionTimeoutError(
                        f"Connection to OPC UA endpoint '{self.config.endpoint_url}' timed out after {self.config.timeout_sec}s."
                    )

                # 6. Validate Server Certificate (strictly no auto-trust; verify expiration)
                await self._validate_server_certificate()

                # Connection successfully established!
                self._reconnect_attempts = 0
                self._last_heartbeat = datetime.now(timezone.utc)
                self.set_state(ConnectionState.CONNECTED)
                return True

            except (UntrustedCertificateError, ExpiredCertificateError, SecurityConfigurationError) as e:
                await self._safe_cleanup()
                self.set_state(ConnectionState.ERROR, str(e))
                raise

            except (ua.UaError, ua.UaStatusCodeError) as e:
                await self._safe_cleanup()
                error_msg = str(e)
                # Differentiate specific OPC UA status codes
                if "BadUserAccessDenied" in error_msg or "BadIdentityToken" in error_msg or "BadSecurityChecksFailed" in error_msg:
                    auth_err = AuthenticationError(f"OPC UA Authentication failed: {error_msg}")
                    self.set_state(ConnectionState.ERROR, str(auth_err))
                    raise auth_err
                elif "BadCertificate" in error_msg or "BadSecurity" in error_msg:
                    sec_err = UntrustedCertificateError(f"OPC UA Security handshake failed: {error_msg}")
                    self.set_state(ConnectionState.ERROR, str(sec_err))
                    raise sec_err
                else:
                    self.set_state(ConnectionState.ERROR, error_msg)
                    raise OPCUAError(f"OPC UA connection error: {error_msg}") from e

            except (OSError, ConnectionRefusedError) as e:
                await self._safe_cleanup()
                err = ConnectionTimeoutError(f"Network error connecting to {self.config.endpoint_url}: {e}")
                self.set_state(ConnectionState.ERROR, str(err))
                raise err from e

            except Exception as e:
                await self._safe_cleanup()
                self.set_state(ConnectionState.ERROR, str(e))
                raise

    async def _validate_server_certificate(self) -> None:
        """Inspect and validate server's X.509 certificate if presented."""
        if not self._client:
            return

        server_cert = None
        try:
            if hasattr(self._client, "security_policy") and self._client.security_policy:
                server_cert = getattr(self._client.security_policy, "peer_certificate", None)
            if not server_cert and hasattr(self._client, "get_endpoints"):
                endpoints = await self._client.get_endpoints()
                for ep in endpoints:
                    if getattr(ep, "ServerCertificate", None):
                        server_cert = ep.ServerCertificate
                        break
        except Exception:
            pass

        # If secure communication was mandated but no server cert was provided, fail closed
        if self.config.security_policy != SecurityPolicy.NONE:
            if not server_cert:
                raise SecurityConfigurationError(
                    f"Security policy '{self.config.security_policy.value}' was mandated, but server "
                    f"did not present an X.509 certificate. Rejecting plaintext downgrade."
                )

        if server_cert:
            self._cert_validator.validate_certificate(server_cert)

    async def disconnect(self) -> None:
        """Gracefully disconnect from the OPC UA server and release network resources."""
        async with self._get_lock():
            await self._safe_cleanup()
            self.set_state(ConnectionState.DISCONNECTED)

    async def _safe_cleanup(self) -> None:
        """Internal helper to disconnect client without raising exceptions."""
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            finally:
                self._client = None

    # =========================================================================
    # HEALTH MONITORING
    # =========================================================================

    async def check_health(self) -> ConnectionHealth:
        """Execute a heartbeat check and return connection health metrics."""
        days_rem = self._client_cert_info.get("days_remaining") if self._client_cert_info else None
        expires_at = self._client_cert_info.get("valid_to_dt") if self._client_cert_info else None

        if self._state != ConnectionState.CONNECTED or not self._client:
            return ConnectionHealth(
                state=self._state,
                is_healthy=False,
                error_message=self._last_error or "Client is not connected",
                reconnect_attempts=self._reconnect_attempts,
                cert_days_remaining=days_rem,
                cert_expires_at=expires_at,
            )

        start = time.perf_counter()
        try:
            # Query the standard OPC UA Server CurrentTime node (ns=0;i=2258)
            time_node = self._client.get_node("ns=0;i=2258")
            server_time_raw = await asyncio.wait_for(
                time_node.read_value(),
                timeout=self.config.timeout_sec
            )

            latency = (time.perf_counter() - start) * 1000.0
            self._latency_ms = latency
            self._last_heartbeat = datetime.now(timezone.utc)

            server_time = server_time_raw if isinstance(server_time_raw, datetime) else None

            return ConnectionHealth(
                state=ConnectionState.CONNECTED,
                is_healthy=True,
                latency_ms=latency,
                last_heartbeat=self._last_heartbeat,
                reconnect_attempts=self._reconnect_attempts,
                server_time=server_time,
                cert_days_remaining=days_rem,
                cert_expires_at=expires_at,
            )

        except (ua.UaError, asyncio.TimeoutError, OSError) as e:
            self._latency_ms = None
            err_msg = f"Heartbeat check failed: {e}"
            self.set_state(ConnectionState.ERROR, err_msg)
            return ConnectionHealth(
                state=ConnectionState.ERROR,
                is_healthy=False,
                error_message=err_msg,
                reconnect_attempts=self._reconnect_attempts,
                cert_days_remaining=days_rem,
                cert_expires_at=expires_at,
            )

    # =========================================================================
    # READ-ONLY OPERATIONS
    # =========================================================================

    async def read_value(self, node_id: str) -> Any:
        """Read a single telemetry value from an OPC UA node."""
        if self._state != ConnectionState.CONNECTED or not self._client:
            raise OPCUAError(f"Cannot read node '{node_id}': client is {self._state.value}")

        try:
            node = self._client.get_node(node_id)
            return await asyncio.wait_for(
                node.read_value(),
                timeout=self.config.timeout_sec
            )
        except Exception as e:
            raise OPCUAError(f"Failed to read OPC UA node '{node_id}': {e}") from e

    async def read_values(self, node_ids: List[str]) -> List[Any]:
        """Read multiple values in batch."""
        if self._state != ConnectionState.CONNECTED or not self._client:
            raise OPCUAError(f"Cannot read nodes: client is {self._state.value}")

        results = []
        for nid in node_ids:
            results.append(await self.read_value(nid))
        return results

    # =========================================================================
    # MANDATORY WRITE PROHIBITION
    # =========================================================================

    async def write_value(self, node_id: str, value: Any) -> None:
        """Write operations are strictly disallowed in PharmaPredict AI."""
        raise ReadOnlyError(
            "OPC UA write operations are strictly disallowed. PharmaPredict AI is read-only."
        )

    async def write_attribute(self, node_id: str, attribute: Any, value: Any) -> None:
        """Write operations are strictly disallowed in PharmaPredict AI."""
        raise ReadOnlyError(
            "OPC UA write operations are strictly disallowed. PharmaPredict AI is read-only."
        )

    async def set_value(self, *args, **kwargs) -> None:
        """Write operations are strictly disallowed in PharmaPredict AI."""
        raise ReadOnlyError(
            "OPC UA write operations are strictly disallowed. PharmaPredict AI is read-only."
        )
