# PharmaPredict AI — Industrial Edge Gateway

The **PharmaPredict Industrial Edge Gateway** is a lightweight, read-only industrial edge software package designed for deployment on-premise inside pharmaceutical manufacturing plants (Purdue Model Level 2 / Supervisory Network).

It bridges factory PLCs/SCADA systems to the PharmaPredict cloud predictive maintenance platform without opening inbound ports or exposing factory machinery to the public internet.

---

## Architecture & Security Boundary

```
[ Factory Floor: Purdue Level 1 ]
  Sensors -> PLC / SCADA -> OPC UA Server
                              ▲
                              │ (Strictly Read-Only OPC UA)
[ On-Premise IPC: Purdue Level 2 ]
  PharmaPredict Edge Gateway
    ├── SecureOPCUAClient (Read-Only Enforcement: Write operations rejected)
    ├── BoundedGatewayBuffer (5,000 RAM queue)
    └── Persistent Disk Buffer (50 MB limit, mode 0700/0600)
                              │
                              ▼ (Outbound HTTPS POST only with X-Gateway-Secret)
[ Internet / Cloudflare Tunnel: Purdue Level 4/5 ]
  Cloud Backend API (/api/v1/internal/ingestion/readings)
    └── Neon PostgreSQL (Deduplicated Time-Series Storage)
```

### Key Security Safeguards
1. **Read-Only OT Enforcement:** The gateway code contains zero PLC write routines. Calling any write operation raises `ReadOnlyError` and immediately aborts.
2. **Outbound-Only HTTPS:** The gateway initiates outbound HTTPS requests to the cloud ingestion endpoint. It listens on **no public inbound ports**. Factory PLCs remain insulated behind plant firewalls.
3. **Secret Masking:** Authentication secrets (`GATEWAY_INTERNAL_SECRET`, OPC UA passwords) are never logged, formatted, or exposed in diagnostics.
4. **Tenant Isolation:** Every reading is verified against the gateway's configured `ORGANIZATION_ID` and `EQUIPMENT_ID` before queuing. Cross-tenant spoofing is rejected locally.
5. **Idempotent Ingestion:** Deterministic SHA-256 `event_id` ensures that retried or replayed batches cannot cause duplicate database records.
6. **Multi-Tier Buffering:** Up to 5,000 readings are held in RAM. During network or cloud outages, batches are spooled to encrypted local disk (up to 50 MB) and automatically drained upon reconnection. Buffered data survives gateway and container restarts.

---

## Configuration Reference

The gateway is configured via environment variables:

| Variable | Description | Default | Mandatory |
| :--- | :--- | :--- | :--- |
| `GATEWAY_ID` | Unique identifier for this edge gateway instance | `gw-edge-01` | No |
| `ORGANIZATION_ID` | Pharmaceutical tenant ID (enforces isolation) | - | **Yes** |
| `EQUIPMENT_ID` | Machine UUID associated with this gateway | - | **Yes** |
| `OPCUA_ENDPOINT_URL` | URL of factory OPC UA server | `opc.tcp://127.0.0.1:48401/...` | **Yes** |
| `OPCUA_SECURITY_POLICY` | `None`, `Basic256Sha256`, `Aes128Sha256RsaOaep` | `None` | No |
| `OPCUA_SECURITY_MODE` | `None`, `Sign`, `SignAndEncrypt` | `None` | No |
| `OPCUA_AUTH_TYPE` | `Anonymous`, `UserName`, `Certificate` | `Anonymous` | No |
| `OPCUA_USERNAME` | Username for OPC UA server (if UserName auth) | - | No |
| `OPCUA_PASSWORD` | Password for OPC UA server (masked in logs) | - | No |
| `CLOUD_INGESTION_URL` | Cloud ingestion API endpoint | `http://127.0.0.1:5000/...` | **Yes** |
| `GATEWAY_INTERNAL_SECRET`| Shared HMAC/PSK for `X-Gateway-Secret` | - | **Yes** |
| `BUFFER_DIR` | Directory for persistent disk spooling | `./data/gateway_buffer` | No |
| `MAX_QUEUE_SIZE` | Max readings held in RAM queue | `5000` | No |
| `MAX_DISK_BUFFER_BYTES` | Max bytes for persistent disk buffer | `52428800` (50 MB) | No |
| `BATCH_SIZE` | Telemetry batch size for cloud delivery | `50` | No |
| `FLUSH_INTERVAL_SEC` | Ingestion delivery frequency | `1.0` | No |
| `VERIFY_SSL` | Validate cloud SSL/TLS certificate | `true` | No |

---

## Deployment Options

### Option 1: Docker (Recommended for On-Premise IPCs)

1. Set up your `.env` file:
   ```bash
   ORGANIZATION_ID=org-pharma-01
   EQUIPMENT_ID=822bf987-00b7-4103-8694-285bfb997cf6
   OPCUA_ENDPOINT_URL=opc.tcp://192.168.1.50:4840/
   CLOUD_INGESTION_URL=https://wed-thousands-kelkoo-centuries.trycloudflare.com/api/v1/internal/ingestion/readings
   GATEWAY_INTERNAL_SECRET=pharma-predict-internal-gateway-key-2026
   ```

2. Build and run using Docker Compose:
   ```bash
   cd gateway
   docker compose up -d
   ```

3. Inspect live operational metrics:
   ```bash
   docker logs -f pharmapredict-edge-gateway
   ```

### Option 2: Standalone Python Service (Systemd / Windows Service)

1. Install Python 3.12+ and virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. Run the gateway process:
   ```bash
   python gateway/edge_gateway.py
   ```

---

## Resiliency & Recovery Behavior

1. **Normal Operation:**
   Readings arrive from OPC UA subscriptions → buffered in RAM → batched in groups of 50 → sent to cloud via HTTPS POST every 1.0s.

2. **Cloud/Tunnel Disconnection:**
   - Outbound HTTP POST fails.
   - Buffer attempts exponential backoff retry (0.5s → 1.0s → 2.0s).
   - If cloud remains unreachable, batches are automatically written to `gateway_overflow.jsonl` on disk.
   - RAM queue is preserved up to 5,000 readings; disk buffer stores up to 50 MB (~100,000 readings, representing ~24-48 hours of typical machine telemetry).

3. **Reconnection & Drain:**
   - Once cloud connectivity is restored, the gateway automatically reads `gateway_overflow.jsonl`, repopulates the delivery queue, and flushes all backlog batches to the cloud.
   - Event IDs are preserved; zero duplicates are created in the database.

4. **Gateway Restart / Power Interruption:**
   - On shutdown (`SIGTERM`/`SIGINT`), the gateway flushes active RAM readings to disk.
   - On startup, the gateway checks for existing disk buffer files, calculates the backlog, and resumes delivery immediately.
