# PharmaPredict AI — Phase 10: Industrial Edge Gateway Production Hardening & Secure PLC Integration

## 1. Executive Summary

Phase 10 transforms the PharmaPredict AI Edge Gateway into a production-hardened, industrial-deployment-ready software package suitable for pharmaceutical pilot environments and physical industrial PCs (IPCs).

Key accomplishments:
- **IEC 62443 Security Compliance:** Secure OPC UA communication with `Basic256Sha256` policy and `SignAndEncrypt` mode, X.509 client certificate management, server certificate validation, expiration monitoring, and fail-closed defense against plaintext downgrade.
- **Strict Read-Only Enforcement:** Guaranteed read-only telemetry acquisition; zero write capabilities or actuation control commands can be issued to physical PLCs (`ReadOnlyError`).
- **Store-and-Forward Telemetry Buffer:** Preserves the 5,000 RAM queue and 50 MB persistent disk spool with crash-safe recovery, deterministic event ID deduplication, and zero silent telemetry loss.
- **Automatic Reconnection & Resilience:** Exponential backoff with ±15% jitter to prevent network storming, network interruption recovery, and graceful shutdown.
- **Industrial Linux Deployment:** Multi-stage rootless Docker packaging (`Dockerfile.edge`), industrial compose (`docker-compose.edge.yml`), systemd service unit with watchdog integration (`pharmapredict-edge.service`), and an operational guide (`docs/edge-linux-installation.md`).
- **Purdue Model OT/IT Segmentation:** Strict dual-homed network architecture requiring outbound HTTPS (port 443) only, with zero open listening ports on the plant floor.

---

## 2. Purdue Model OT/IT Architecture

```
+---------------------------------------------------------------------------------+
|                        LEVEL 4 / ENTERPRISE & CLOUD                             |
|   PharmaPredict AI Cloud (Vercel Ingestion API)                                 |
|   https://predictive-maintenance-system-bay.vercel.app/api/v1/internal/ingestion |
+---------------------------------------------------------------------------------+
                                         ^
                                         | Outbound HTTPS Only (TCP Port 443)
                                         | Authenticated with X-Gateway-Secret
                                         v
+---------------------------------------------------------------------------------+
|                        LEVEL 3 / INDUSTRIAL DMZ                                 |
|                                                                                 |
|   Corporate / DMZ Network (NIC 2: e.g. 10.20.0.50/24)                          |
|   +-------------------------------------------------------------------------+   |
|   |            Industrial Edge Gateway (IPC / DIN-Rail Box)                |   |
|   |            Daemon: edgeuser:10001 (Rootless Execution)                  |   |
|   |                                                                         |   |
|   |    +----------------------+   RAM Queue    +-----------------------+    |   |
|   |    |  SecureOPCUAClient   | -------------> | BoundedGatewayBuffer  |    |   |
|   |    |  - Basic256Sha256    | (Up to 5,000)  |  - 50 MB Disk Spool   |    |   |
|   |    |  - SignAndEncrypt    |                |  - fsync Durability   |    |   |
|   |    |  - X.509 Trust Store |                |  - Crash-Safe Staging |    |   |
|   |    |  - Strictly ReadOnly |                |  - Backoff + Jitter   |    |   |
|   |    +----------------------+                +-----------------------+    |   |
|   +-------------------------------------------------------------------------+   |
|   OT Network Interface (NIC 1: e.g. 192.168.1.50/24)                            |
+---------------------------------------------------------------------------------+
                                         ^
                                         | OPC UA Binary (TCP Port 4840 / opc.tcp)
                                         | Read-Only Polling Sessions Only
                                         v
+---------------------------------------------------------------------------------+
|                        LEVEL 1 / 2 : CONTROL & CELL                             |
|   Siemens S7-1500 / Beckhoff TwinCAT / Rockwell ControlLogix                    |
|   OPC UA Server (192.168.1.100:4840)                                            |
+---------------------------------------------------------------------------------+
```

### Network Security Rules:
1. **Zero Inbound Ports:** The edge gateway opens no listening network sockets (HTTP, SSH, or RPC). All inbound connections are dropped by iptables/nftables.
2. **Dedicated Read-Only Service Account:** The gateway connects using a dedicated operator service account with read-only permissions configured at the PLC level.
3. **Firewall Allowlisting:** OT firewalls restrict gateway communication strictly to PLC IP `192.168.1.100` on TCP port `4840`. DMZ firewalls restrict outbound HTTPS to the PharmaPredict ingestion hostname on TCP port `443`.

---

## 3. Security & X.509 Certificate Management

### 3.1 Client Certificate Lifecycle
The gateway manages its own cryptographic identity using `CertificateManager`:
- **Generation:** 2048-bit RSA key with SHA-256 digital signature, SAN extensions (`DNS:localhost`, `URI:urn:PharmaPredict-OPCUA-Client`), and standard Key Usage flags.
- **Storage:** Persisted to `/var/lib/pharmapredict/certs/client_cert.pem` with private key `/var/lib/pharmapredict/certs/client_key.pem` (mode `0600`).
- **Rotation:** If the client certificate is within 30 days of expiration, `CertificateManager.ensure_client_certificate` archives the previous pair to `/var/lib/pharmapredict/certs/archive/` and generates a fresh pair.

### 3.2 Server Certificate Validation
The `CertificateValidator` enforces three levels of checks on the server's certificate:
1. **Expiration & Period:** Rejects expired certificates or certificates not yet active with `ExpiredCertificateError`.
2. **Fingerprint & Trust Store:** Matches the SHA-256 fingerprint against `TRUSTED_CERT_FINGERPRINTS` or loads approved DER/PEM certificates from `TRUSTED_CERTS_DIR`.
3. **Fail-Closed Plaintext Downgrade Guard:** If `OPCUA_SECURITY_POLICY != None`, any attempt by the server to offer `None` or connect without encryption raises `SecurityConfigurationError`.

---

## 4. Store-and-Forward Telemetry Buffer

The `BoundedGatewayBuffer` provides uninterrupted data collection during temporary network outages:

| Component | Specification | Behavior & Guard |
| :--- | :--- | :--- |
| **RAM Queue** | Max 5,000 readings | In-memory FIFO queue. Batches of 50 dispatched every 1.0s. |
| **Oldest Record Age** | Real-time metric | Tracks latency of oldest buffered reading in seconds. |
| **Disk Spool** | Max 50 MB (`gateway_overflow.jsonl`) | Spools overflow or undelivered batches to disk with POSIX `fsync`. |
| **Crash Recovery** | `gateway_recovering.jsonl` | Staged atomically on restart; replayed to cloud without duplicate records. |
| **Deduplication** | Deterministic `event_id` | SHA-256 of `(machine_id, signal_id, timestamp, value, sequence_id)`. |
| **Capacity Ceiling** | 50 MB hard limit | Emits critical alert and halts spooling to protect flash media from exhaustion. |
| **Corrupt Line Guard** | `gateway_corrupt_records.jsonl` | Quarantines malformed lines without dropping valid telemetry. |

---

## 5. Automatic Reconnection with Jitter

The gateway reconnection loop avoids synchronized connection storms using randomized backoff:
$$\text{wait\_time} = \min(\text{backoff} \times 1.5, 30.0) \times \text{Uniform}(0.85, 1.15)$$

- Initial retry: 2.0s
- Success: Resets backoff to 2.0s
- Disconnection: Re-polls health every loop without blocking the buffer flush worker.

---

## 6. Linux Deployment Package

The repository includes ready-to-deploy industrial Linux artifacts:
- **`Dockerfile.edge`:** Multi-stage, unprivileged UID 10001, no exposed ports, rootless volume mounts.
- **`docker-compose.edge.yml`:** Hardened container definitions, resource limits (1.0 CPU, 512 MB RAM), persistent volumes for buffer and certs.
- **`deploy/systemd/pharmapredict-edge.service`:** Systemd unit with watchdog integration (`WatchdogSec=60s`), `ProtectSystem=strict`, `NoNewPrivileges=true`, and resource sandboxing.
- **`.env.edge.example`:** Full reference template with zero embedded credentials.
- **`docs/edge-linux-installation.md`:** Comprehensive deployment, certificate provisioning, and troubleshooting manual.

---

## 7. Operational Health Monitoring

The edge gateway maintains real-time health metrics in `/var/lib/pharmapredict/buffer/.gateway_health.json`:
- `opcua_connected`: Boolean state of PLC connection.
- `uptime_sec`: Continuous running duration.
- `queue_depth` & `queue_utilization_pct`: Current RAM queue load.
- `buffered_disk_readings` & `disk_utilization_pct`: Staged offline records.
- `oldest_record_age_sec`: Telemetry latency indicator.
- `client_cert_days_remaining`: Time until X.509 certificate renewal.
- `delivery_success_pct`: Cloud batch delivery success rate.
- `quarantined_corrupt_records`: Count of isolated malformed records.

The probe script `python gateway/healthcheck.py` evaluates these metrics and exits:
- `0` for healthy or temporarily degraded (OPC UA reconnecting) states.
- `1` for fatal errors (event loop stalled > 60s, expired certificate, process stopped).
