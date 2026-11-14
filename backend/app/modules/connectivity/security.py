"""PharmaPredict AI — Industrial OPC UA Security & X.509 Certificate Management.
================================================================================
Implements industrial-grade X.509 certificate generation, trust-store validation,
expiration monitoring, certificate rotation, and fail-closed security guards
compliant with IEC 62443 and OPC UA Part 4 / Part 12 specifications.
"""

import os
import shutil
import hashlib
import logging
from typing import List, Optional, Dict, Any, Union
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

from app.modules.connectivity.models import (
    UntrustedCertificateError,
    ExpiredCertificateError,
    SecurityConfigurationError,
)

logger = logging.getLogger("PharmaPredict.OPCUA.Security")


def compute_cert_fingerprint(cert_der: bytes) -> str:
    """Compute standard SHA-256 fingerprint in uppercase colon-delimited format."""
    sha256 = hashlib.sha256(cert_der).hexdigest().upper()
    return ":".join(sha256[i:i + 2] for i in range(0, len(sha256), 2))


def parse_x509_certificate(cert_data: Union[bytes, str, Path]) -> x509.Certificate:
    """Load an X.509 certificate from raw DER bytes, PEM bytes, or a filesystem path."""
    if isinstance(cert_data, (str, Path)):
        p = Path(cert_data)
        if not p.is_file():
            raise FileNotFoundError(f"Certificate file not found: {cert_data}")
        raw_bytes = p.read_bytes()
    elif isinstance(cert_data, bytes):
        raw_bytes = cert_data
    else:
        raise TypeError(f"Expected bytes, str, or Path, got {type(cert_data)}")

    if b"BEGIN CERTIFICATE" in raw_bytes:
        return x509.load_pem_x509_certificate(raw_bytes)
    else:
        try:
            return x509.load_der_x509_certificate(raw_bytes)
        except Exception:
            # Fallback if bytes happen to be ascii-pem without header
            return x509.load_pem_x509_certificate(raw_bytes)


def check_certificate_expiry(cert_data: Union[bytes, str, Path]) -> Dict[str, Any]:
    """Inspect X.509 certificate validity dates and calculate days remaining."""
    cert = parse_x509_certificate(cert_data)
    now = datetime.now(timezone.utc)

    # Normalize timezone-aware dates
    not_before = cert.not_valid_before_utc if hasattr(cert, "not_valid_before_utc") else cert.not_valid_before.replace(tzinfo=timezone.utc)
    not_after = cert.not_valid_after_utc if hasattr(cert, "not_valid_after_utc") else cert.not_valid_after.replace(tzinfo=timezone.utc)

    der_bytes = cert.public_bytes(serialization.Encoding.DER)
    fingerprint = compute_cert_fingerprint(der_bytes)

    # Extract Common Name if present
    common_names = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    common_name = common_names[0].value if common_names else "Unknown"

    time_remaining = not_after - now
    days_remaining = int(time_remaining.total_seconds() // 86400)
    is_expired = now > not_after
    is_not_yet_valid = now < not_before
    is_valid = (not is_expired) and (not is_not_yet_valid)

    return {
        "common_name": common_name,
        "fingerprint": fingerprint,
        "valid_from": not_before.isoformat(),
        "valid_to": not_after.isoformat(),
        "valid_from_dt": not_before,
        "valid_to_dt": not_after,
        "days_remaining": days_remaining,
        "is_expired": is_expired,
        "is_not_yet_valid": is_not_yet_valid,
        "is_valid": is_valid,
        "serial_number": hex(cert.serial_number),
    }


class CertificateValidator:
    """Validates OPC UA server X.509 certificates against a strict trust list and expiration rules.
    
    Adheres strictly to IEC 62443:
    1. Rejects expired certificates or certificates not yet active.
    2. Rejects certificates not present in the trusted store or fingerprint allowlist.
    3. Prevents auto-trust in production unless explicitly flagged for tests.
    """

    def __init__(
        self,
        trusted_fingerprints: Optional[List[str]] = None,
        trusted_certs_dir: Optional[str] = None,
        auto_trust_unknown: bool = False,
        enforce_expiry: bool = True,
    ):
        self.trusted_fingerprints = set(
            fp.strip().upper() for fp in (trusted_fingerprints or [])
        )
        self.trusted_certs_dir = trusted_certs_dir
        self.auto_trust_unknown = auto_trust_unknown
        self.enforce_expiry = enforce_expiry
        self._load_trusted_directory()

    def reload(self) -> None:
        """Reload trusted certificates from disk."""
        self._load_trusted_directory()

    def _load_trusted_directory(self) -> None:
        """Load trusted certificates from the designated directory if present."""
        if not self.trusted_certs_dir or not os.path.isdir(self.trusted_certs_dir):
            return

        for filename in os.listdir(self.trusted_certs_dir):
            if filename.endswith((".der", ".cer", ".crt", ".pem")):
                filepath = os.path.join(self.trusted_certs_dir, filename)
                try:
                    with open(filepath, "rb") as f:
                        data = f.read()
                        if b"BEGIN CERTIFICATE" in data:
                            cert = x509.load_pem_x509_certificate(data)
                            fp = compute_cert_fingerprint(cert.public_bytes(serialization.Encoding.DER))
                        else:
                            fp = compute_cert_fingerprint(data)
                        self.trusted_fingerprints.add(fp)
                except Exception as e:
                    logger.warning(f"Failed to read trusted certificate '{filename}': {e}")
                    continue

    def validate_certificate(self, cert_der: bytes) -> bool:
        """Validate an incoming server certificate.
        
        Raises ExpiredCertificateError if certificate is expired.
        Raises UntrustedCertificateError if unknown and not explicitly trusted.
        """
        if not cert_der:
            raise UntrustedCertificateError("No server certificate was presented for validation.")

        # 1. Expiration check
        if self.enforce_expiry:
            expiry_info = check_certificate_expiry(cert_der)
            if expiry_info["is_expired"]:
                raise ExpiredCertificateError(
                    f"Server certificate '{expiry_info['common_name']}' expired on {expiry_info['valid_to']} "
                    f"({abs(expiry_info['days_remaining'])} days ago). Connection rejected."
                )
            if expiry_info["is_not_yet_valid"]:
                raise ExpiredCertificateError(
                    f"Server certificate '{expiry_info['common_name']}' is not yet valid (valid from {expiry_info['valid_from']}). "
                    f"Connection rejected."
                )

        # 2. Trust store check
        fingerprint = compute_cert_fingerprint(cert_der)

        if fingerprint in self.trusted_fingerprints:
            return True

        if self.auto_trust_unknown:
            logger.warning(
                f"[SECURITY ALERT] Auto-trusting unknown server certificate {fingerprint}. "
                f"Use ONLY in local test environments!"
            )
            self.trusted_fingerprints.add(fingerprint)
            return True

        raise UntrustedCertificateError(
            f"Server certificate with SHA-256 fingerprint {fingerprint} is not in the trusted certificate store. "
            f"Connection rejected to prevent man-in-the-middle attacks."
        )


def generate_self_signed_cert(
    output_dir: str,
    common_name: str = "PharmaPredict-OPCUA-Client",
    validity_days: int = 365,
    key_size: int = 2048,
) -> tuple[str, str]:
    """Generate a self-signed X.509 certificate and RSA private key for secure authentication.
    
    Returns (cert_path, key_path).
    """
    os.makedirs(output_dir, exist_ok=True)
    key_path = os.path.join(output_dir, f"{common_name}-key.pem")
    cert_path = os.path.join(output_dir, f"{common_name}-cert.pem")

    # Generate RSA private key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=key_size,
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "PK"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "PharmaPredict AI"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.UniformResourceIdentifier(f"urn:{common_name}")
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=True,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    # Restrict permissions on private key file (POSIX 0o600)
    with open(key_path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    if hasattr(os, "chmod") and os.name == "posix":
        try:
            os.chmod(key_path, 0o600)
        except OSError:
            pass

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    return cert_path, key_path


class CertificateManager:
    """Manages edge gateway client certificates and server trust store operations."""

    @staticmethod
    def ensure_client_certificate(
        cert_dir: str,
        common_name: str = "PharmaPredict-OPCUA-Client",
        validity_days: int = 365,
        renew_within_days: int = 30,
    ) -> tuple[str, str]:
        """Verify client certificate exists and has sufficient remaining validity.
        
        If missing or expiring within renew_within_days, generates a new one.
        Returns (cert_path, key_path).
        """
        p_dir = Path(cert_dir)
        p_dir.mkdir(parents=True, exist_ok=True)
        cert_path = p_dir / f"{common_name}-cert.pem"
        key_path = p_dir / f"{common_name}-key.pem"

        if cert_path.exists() and key_path.exists():
            try:
                info = check_certificate_expiry(cert_path)
                if info["is_valid"] and info["days_remaining"] > renew_within_days:
                    return str(cert_path), str(key_path)
                logger.info(
                    f"Client certificate '{common_name}' expiring soon ({info['days_remaining']} days remaining); rotating."
                )
            except Exception as e:
                logger.warning(f"Error checking existing client cert '{cert_path}': {e}. Re-generating.")

        return CertificateManager.rotate_client_certificate(cert_dir, common_name, validity_days)

    @staticmethod
    def rotate_client_certificate(
        cert_dir: str,
        common_name: str = "PharmaPredict-OPCUA-Client",
        validity_days: int = 365,
    ) -> tuple[str, str]:
        """Rotate client certificate by archiving the previous pair and generating a new one."""
        p_dir = Path(cert_dir)
        p_dir.mkdir(parents=True, exist_ok=True)
        cert_path = p_dir / f"{common_name}-cert.pem"
        key_path = p_dir / f"{common_name}-key.pem"

        # Archive existing if present
        if cert_path.exists() and key_path.exists():
            archive_dir = p_dir / "archive"
            archive_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            try:
                shutil.copy2(cert_path, archive_dir / f"{common_name}-cert-{ts}.pem")
                shutil.copy2(key_path, archive_dir / f"{common_name}-key-{ts}.pem")
            except Exception as e:
                logger.warning(f"Could not archive previous certificate: {e}")

        new_cert, new_key = generate_self_signed_cert(
            str(p_dir), common_name=common_name, validity_days=validity_days
        )
        logger.info(f"Generated new client certificate pair: {new_cert}")
        return new_cert, new_key

    @staticmethod
    def trust_server_certificate(
        cert_data: Union[bytes, str, Path],
        trust_dir: str,
        name_hint: Optional[str] = None,
    ) -> str:
        """Save a server certificate into the trusted certificates directory.
        
        Returns the SHA-256 fingerprint.
        """
        p_trust = Path(trust_dir)
        p_trust.mkdir(parents=True, exist_ok=True)

        cert = parse_x509_certificate(cert_data)
        fp = compute_cert_fingerprint(cert.public_bytes(serialization.Encoding.DER))
        slug = name_hint or fp.replace(":", "")[:16]
        dest_file = p_trust / f"server_{slug}.der"

        with open(dest_file, "wb") as f:
            f.write(cert.public_bytes(serialization.Encoding.DER))

        logger.info(f"Added server certificate to trust store: {dest_file} (Fingerprint: {fp})")
        return fp

    @staticmethod
    def list_trusted_certificates(trust_dir: str) -> List[Dict[str, Any]]:
        """List all certificates currently present in the trust directory."""
        p_trust = Path(trust_dir)
        if not p_trust.is_dir():
            return []

        results = []
        for file in p_trust.iterdir():
            if file.suffix.lower() in (".der", ".cer", ".crt", ".pem"):
                try:
                    info = check_certificate_expiry(file)
                    info["filename"] = file.name
                    info["filepath"] = str(file)
                    results.append(info)
                except Exception as e:
                    logger.debug(f"Could not parse certificate in trust dir {file.name}: {e}")
        return results
