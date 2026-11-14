# PharmaPredict AI — Industrial Linux Edge Gateway Deployment & Operations Guide

## 1. Overview & System Scope

This document provides complete instructions for provisioning, configuring, and operating the **PharmaPredict AI Standalone Industrial Edge Gateway** on industrial PCs (IPCs), DIN-rail IoT gateways (e.g. Siemens SIMATIC IOT2050, Advantech UNO, Beckhoff CX series), and virtual appliances running industrial Linux (Ubuntu 22.04/24.04 LTS, Debian 12 Bookworm, or RHEL 9).

The gateway acts as an autonomous, strictly read-only bridge between industrial plant-floor PLCs (Purdue Level 1/2) and the PharmaPredict AI Cloud Backend (Purdue Enterprise / Cloud).

---

## 2. Hardware & Architecture Prerequisites

### 2.1 Hardware Requirements
- **CPU:** Dual-core x86_64 or ARM64 processor (1.0 GHz+).
- **RAM:** Minimum 1 GB (Gateway consumes < 200 MB under peak load).
- **Storage:** Minimum 8 GB eMMC, SSD, or industrial-grade SD card (with 50 MB dedicated for crash-safe disk spooling).
- **Network Interfaces:** Minimum two physical Ethernet ports (NIC1 for OT, NIC2 for IT/DMZ) for physical network segmentation.

### 2.2 Purdue Model Network Architecture

```
[ Level 4 / Cloud ]   PharmaPredict AI Cloud (Vercel Ingestion API)
                                    ^
                                    | HTTPS Outbound (Port 443 Only)
                                    v
[ Level 3 / DMZ ]     Plant Floor Firewall / Industrial DMZ
                         NIC2: 10.20.0.50 (Corporate/DMZ Subnet)
                      +------------------------------------------+
                      |   Industrial Edge Gateway (Linux PC)     |
                      |   PharmaPredict Daemon (edgeuser:10001)  |
                      +------------------------------------------+
                         NIC1: 192.168.1.50 (Isolated OT Subnet)
                                    ^
                                    | OPC UA (Port 4840 / opc.tcp://)
                                    | Strictly Read-Only; Encrypted
                                    v
[ Level 1 / 2 ]       PLC / SCADA (Siemens S7-1500 / Beckhoff / Rockwell)
                      192.168.1.100:4840
```

> [!IMPORTANT]
> **Strict Firewall Rules:**
> - **Inbound:** 0 open listening ports on the Edge Gateway. No unsolicited traffic from cloud, IT, or OT is accepted.
> - **Outbound (OT NIC1):** TCP Port 4840 to specific PLC IP only (`192.168.1.100`).
> - **Outbound (DMZ NIC2):** TCP Port 443 (HTTPS) to `predictive-maintenance-system-bay.vercel.app` only.

---

## 3. Installation Methods

Choose between **Method A: Docker / Container Deployment** (recommended for rapid deployment and container isolation) or **Method B: Native Systemd Service** (recommended for ultra-lightweight bare-metal DIN-rail computers).

---

### Method A: Docker & Docker Compose Deployment

#### Step 1: Create Dedicated Service Directory
```bash
sudo mkdir -p /opt/pharmapredict-edge
cd /opt/pharmapredict-edge
```

#### Step 2: Download Compose & Environment Files
Copy `docker-compose.edge.yml` and `.env.edge.example`:
```bash
sudo cp /path/to/repo/docker-compose.edge.yml ./docker-compose.yml
sudo cp /path/to/repo/.env.edge.example ./.env
```

#### Step 3: Configure Environment Variables
Edit `.env` and set your credentials:
```bash
sudo nano .env
```
Ensure the following are configured:
- `GATEWAY_INTERNAL_SECRET`: Strong shared secret matching the cloud tenant.
- `OPCUA_ENDPOINT_URL`: The PLC endpoint (e.g. `opc.tcp://192.168.1.100:4840`).
- `EQUIPMENT_ID`: The target machine ID (e.g. `0d9bba98-6ad9-417c-9543-ef024447ef04`).
- `OPCUA_SECURITY_POLICY`: `Basic256Sha256`
- `OPCUA_SECURITY_MODE`: `SignAndEncrypt`
- `OPCUA_USERNAME`: Dedicated read-only PLC service user.
- `OPCUA_PASSWORD`: Service user password.

#### Step 4: Restrict Permissions
```bash
sudo chmod 600 .env
```

#### Step 5: Start Gateway
```bash
sudo docker compose up -d
```

#### Step 6: Verify Service Health
```bash
sudo docker compose ps
sudo docker compose logs -f edge-gateway
```

---

### Method B: Native Systemd Service Deployment

#### Step 1: Create System User & Directories
```bash
# Create unprivileged service user and group
sudo groupadd -g 10001 edgegroup
sudo useradd -u 10001 -g edgegroup -s /sbin/nologin -d /opt/pharmapredict edgeuser

# Create persistent buffer, cert, and log directories
sudo mkdir -p /opt/pharmapredict \
              /var/lib/pharmapredict/buffer \
              /var/lib/pharmapredict/certs \
              /var/lib/pharmapredict/trusted_certs \
              /var/log/pharmapredict \
              /etc/pharmapredict

# Set restrictive permissions
sudo chown -R edgeuser:edgegroup /opt/pharmapredict /var/lib/pharmapredict /var/log/pharmapredict
sudo chmod 700 /var/lib/pharmapredict/buffer /var/lib/pharmapredict/certs /var/log/pharmapredict
```

#### Step 2: Set Up Python Virtual Environment
```bash
cd /opt/pharmapredict
sudo -u edgeuser python3 -m venv venv
sudo -u edgeuser ./venv/bin/pip install --upgrade pip
sudo -u edgeuser ./venv/bin/pip install -r /path/to/backend/requirements.txt

# Copy gateway and backend modules
sudo cp -r /path/to/backend/* /opt/pharmapredict/
sudo chown -R edgeuser:edgegroup /opt/pharmapredict
```

#### Step 3: Install Configuration File
```bash
sudo cp /path/to/.env.edge.example /etc/pharmapredict/edge.env
sudo chown edgeuser:edgegroup /etc/pharmapredict/edge.env
sudo chmod 600 /etc/pharmapredict/edge.env
sudo nano /etc/pharmapredict/edge.env
```

#### Step 4: Install and Enable Systemd Unit
```bash
sudo cp /path/to/deploy/systemd/pharmapredict-edge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pharmapredict-edge.service
sudo systemctl start pharmapredict-edge.service
```

#### Step 5: Monitor Gateway Status
```bash
sudo systemctl status pharmapredict-edge.service
sudo journalctl -u pharmapredict-edge.service -f
```

---

## 4. X.509 Certificate Management

### 4.1 Client Certificate Generation
If `OPCUA_CERT_PATH` does not point to an existing certificate, the gateway automatically generates a 2048-bit RSA self-signed client certificate on initial startup:
- Certificate location: `/var/lib/pharmapredict/certs/client_cert.pem`
- Private key location: `/var/lib/pharmapredict/certs/client_key.pem` (mode `0600`)

### 4.2 Trusting the Gateway on the PLC
1. Export the client public certificate:
   ```bash
   cat /var/lib/pharmapredict/certs/client_cert.pem
   ```
2. In TIA Portal (Siemens) or TwinCAT (Beckhoff):
   - Import the certificate into the **OPC UA Server Trusted Clients** certificate store.
   - Verify the SHA-256 fingerprint matches the log output of the gateway.

### 4.3 Trusting the PLC Server Certificate on the Gateway
1. Export the PLC's server certificate (DER or PEM format) from engineering software.
2. Copy it into the trusted directory:
   ```bash
   sudo cp plc_server_cert.der /var/lib/pharmapredict/trusted_certs/
   sudo chown edgeuser:edgegroup /var/lib/pharmapredict/trusted_certs/*
   sudo chmod 644 /var/lib/pharmapredict/trusted_certs/*
   ```
3. Restart the service to reload the trust store:
   ```bash
   sudo systemctl restart pharmapredict-edge.service
   ```

---

## 5. Store-and-Forward Telemetry Buffer & Recovery

- **Normal Operation:** Readings are collected into RAM and dispatched in batches of 50 every 1.0 second.
- **Network Outage:** If cloud delivery fails (e.g. factory WAN drops), readings are spooled into `/var/lib/pharmapredict/buffer/gateway_overflow.jsonl` with an `fsync` call.
- **Capacity Ceiling:** When the spool reaches 50 MB (approx. 200,000 readings), an overflow alert is emitted to journald and bounded dropping begins to protect flash storage.
- **Automatic Recovery:** Once connectivity is restored, the gateway stages the file to `gateway_recovering.jsonl` and streams backlog batches to the cloud without duplicate generation or data loss.

---

## 6. Health & Diagnostics Probe

Execute the standalone health check at any time:
```bash
python3 /opt/pharmapredict/gateway/healthcheck.py
```
Output:
```text
[Healthcheck OK] Gateway 'gw-edge-packaging-01' responsive (age: 1.2s, uptime: 3600.0s).
```

Inspecting active metrics:
```bash
cat /var/lib/pharmapredict/buffer/.gateway_health.json | jq .
```
Key fields to verify:
- `"opcua_connected": true`
- `"is_running": true`
- `"queue_depth": 0`
- `"client_cert_days_remaining": 364`
- `"delivery_success_pct": 100.0`
