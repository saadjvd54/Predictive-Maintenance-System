from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone


class ConnectionState(str, Enum):
    """OPC UA connection states according to Phase 4 specifications."""
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    ERROR = "ERROR"


class SecurityMode(str, Enum):
    """OPC UA Message Security Modes."""
    NONE = "None"
    SIGN = "Sign"
    SIGN_AND_ENCRYPT = "SignAndEncrypt"


class SecurityPolicy(str, Enum):
    """OPC UA Security Policies."""
    NONE = "None"
    BASIC256_SHA256 = "Basic256Sha256"
    AES128_SHA256_RSAOAEP = "Aes128_Sha256_RsaOaep"


class UserAuthType(str, Enum):
    """OPC UA User Identity Token types."""
    ANONYMOUS = "Anonymous"
    USERNAME = "UserName"
    CERTIFICATE = "Certificate"


class OPCUAError(Exception):
    """Base exception for OPC UA connectivity."""
    pass


class ReadOnlyError(OPCUAError):
    """Raised when an illegal write operation is attempted on read-only client."""
    pass


class AuthenticationError(OPCUAError):
    """Raised when user or token authentication fails."""
    pass


class UntrustedCertificateError(OPCUAError):
    """Raised when the server's certificate is not trusted."""
    pass


class ExpiredCertificateError(UntrustedCertificateError):
    """Raised when an X.509 certificate has expired or is not yet valid."""
    pass


class SecurityConfigurationError(OPCUAError):
    """Raised when security parameters are invalid or fail closed (e.g. plaintext downgrade attempt)."""
    pass


class ConnectionTimeoutError(OPCUAError):
    """Raised when connection attempt exceeds configured timeout."""
    pass


class ServerShutdownError(OPCUAError):
    """Raised when the server unexpectedly terminates or sends shutdown notification."""
    pass


@dataclass
class ConnectionConfig:
    """Configuration parameters for OPC UA client connection."""
    endpoint_url: str
    timeout_sec: float = 5.0
    security_policy: SecurityPolicy = SecurityPolicy.NONE
    security_mode: SecurityMode = SecurityMode.NONE
    user_auth_type: UserAuthType = UserAuthType.ANONYMOUS
    username: Optional[str] = None
    password: Optional[str] = None
    client_cert_path: Optional[str] = None
    client_key_path: Optional[str] = None
    trusted_certs_dir: Optional[str] = None
    trusted_cert_fingerprints: List[str] = field(default_factory=list)
    auto_trust_unknown: bool = False  # Strictly False by default per requirement 6
    
    # Bounded Exponential Backoff Parameters
    max_reconnect_attempts: int = 5
    initial_backoff_sec: float = 1.0
    backoff_factor: float = 2.0
    max_backoff_sec: float = 30.0

    # Health monitoring
    health_check_interval_sec: float = 5.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "endpoint_url": self.endpoint_url,
            "timeout_sec": self.timeout_sec,
            "security_policy": self.security_policy.value,
            "security_mode": self.security_mode.value,
            "user_auth_type": self.user_auth_type.value,
            "username": self.username,
            "client_cert_path": self.client_cert_path,
            "trusted_cert_fingerprints": self.trusted_cert_fingerprints,
            "auto_trust_unknown": self.auto_trust_unknown,
            "max_reconnect_attempts": self.max_reconnect_attempts,
            "health_check_interval_sec": self.health_check_interval_sec,
        }


@dataclass
class ConnectionHealth:
    """Real-time health status of the connection."""
    state: ConnectionState
    is_healthy: bool
    latency_ms: Optional[float] = None
    last_heartbeat: Optional[datetime] = None
    reconnect_attempts: int = 0
    error_message: Optional[str] = None
    server_time: Optional[datetime] = None
    cert_days_remaining: Optional[int] = None
    cert_expires_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "is_healthy": self.is_healthy,
            "latency_ms": round(self.latency_ms, 2) if self.latency_ms is not None else None,
            "last_heartbeat": self.last_heartbeat.isoformat() if self.last_heartbeat else None,
            "reconnect_attempts": self.reconnect_attempts,
            "error_message": self.error_message,
            "server_time": self.server_time.isoformat() if self.server_time else None,
            "cert_days_remaining": self.cert_days_remaining,
            "cert_expires_at": self.cert_expires_at.isoformat() if self.cert_expires_at else None,
        }

