# PharmaPredict AI — Physical Pharmaceutical PLC Pilot Commissioning Standard Operating Procedure (SOP)

**Document ID:** `SOP-ENG-PH11-001`  
**Version:** `1.0.0`  
**Classification:** Engineering Standard Operating Procedure (GxP / Critical)  
**System:** PharmaPredict AI Industrial Edge Gateway  
**Target Reference Equipment:** Uhlen Blister Packaging Machine BPK-200 (`PILOT-BPK-01` / `DEMO-BPK-200`)  
**Target Facility Reference:** Getz Pharma — Secondary Packaging Hall, Packaging Line 4  
**Status:** Approved for Controlled Field Execution  

---

## 1. PURPOSE & SCOPE

This Standard Operating Procedure (SOP) defines the mandatory engineering protocol for physically installing, commissioning, and validating the PharmaPredict AI Industrial Edge Gateway against physical Programmable Logic Controllers (PLCs) in a regulated pharmaceutical manufacturing facility.

### Scope
- Applies to all edge gateway deployments interfacing with packaging hall machinery (blister packers, cartoners, checkweighers, tablet presses).
- Covers hardware installation, network isolation (Purdue Level 2/3), X.509 certificate exchange, read-only tag discovery, human signal commissioning, telemetry verification, and 24-hour shadow monitoring.
- **Strict Constraint:** This procedure enforces read-only OPC UA connectivity. Under no circumstances may write or control commands be configured or transmitted to the PLC.

---

## 2. ROLES & RESPONSIBILITIES

| Role | Responsibility | Qualification Required |
|---|---|---|
| **Lead Automation Engineer** | Physical IPC installation, network cabling, PLC certificate import, tag discovery execution. | Siemens Certified Automation Professional / Industrial OT Specialist |
| **Maintenance Engineer** | Human signal review, canonical mapping validation, formal approval sign-off in PharmaPredict UI. | PharmaPredict Maintenance Engineer Role (RBAC) |
| **Quality Assurance (QA) / CSV** | Verification of ALCOA+ compliance, audit trail review, change control sign-off. | Computerized System Validation Specialist |
| **Site Operations Manager** | Maintenance window authorization, Lockout/Tagout (LOTO) approval. | Secondary Packaging Production Authority |

---

## 3. HARDWARE & NETWORK PREREQUISITES

### 3.1 Edge Gateway Industrial PC (IPC) Specifications
- **Form Factor:** DIN-rail mountable fanless industrial IPC (e.g., Advantech UNO-2484G, Siemens Microbox IPC427E, or Moxa MC-1121).
- **CPU:** Quad-Core Intel x86_64 or ARM64 industrial processor (minimum 2.0 GHz).
- **RAM:** Minimum 8 GB DDR4 ECC RAM (minimum floor: 2 GB).
- **Storage:** Industrial MLC/pSLC Solid State Drive (minimum 64 GB) with $\ge 50$ GB allocated to `/var/lib/pharmapredict/buffer`.
- **Power Supply:** Redundant 24V DC ($\pm 10\%$) with surge suppression and uninterruptible power supply (UPS) backing.
- **Dual Network Interfaces (Mandatory):**
  - `NIC 1 (eth0 / OT)`: Connects exclusively to the machine cell OT network (Purdue Level 1/2). Static IP (e.g., `192.168.10.51/24`). No gateway or internet routing on this interface.
  - `NIC 2 (eth1 / IT)`: Connects exclusively to the plant DMZ / corporate IT network (Purdue Level 3/3.5). DHCP or static IP with outbound HTTPS (port 443) to the PharmaPredict cloud backend. No inbound ports permitted.

### 3.2 Network Architecture (Purdue Model Separation)
```
[ LEVEL 4: Enterprise Cloud ]  <--- PharmaPredict Cloud Backend (HTTPS :443)
            ^
            | (Outbound HTTPS only, TLS 1.3, mutual auth)
[ LEVEL 3: Industrial DMZ ]    <--- NIC 2 (eth1) [ Edge Gateway IPC ]
                                    | (Isolated physical interface)
[ LEVEL 2: Machine Cell OT ]   <--- NIC 1 (eth0) [ Edge Gateway IPC ]
            |
            | (OPC UA TCP :4840, Basic256Sha256 SignAndEncrypt)
[ LEVEL 1: Industrial PLC ]    <--- Siemens S7-1500 / Beckhoff CX5120
```

---

## 4. SAFETY & LOCKOUT / TAGOUT (LOTO) PROTOCOL

1. Prior to opening any industrial electrical cabinet, obtain an approved **Electrical Hot Work Permit** and **Line Intervention Sign-Off** from the Secondary Packaging Area Supervisor.
2. Confirm the packaging line is in a controlled stopped state or during a planned changeover/preventative maintenance window.
3. Apply standard LOTO locks and tags to the control cabinet power supply per **SOP-SAF-LOTO-004** if physical wiring changes are necessary.
4. Mount the Industrial Edge IPC securely on the standard 35 mm DIN rail in the low-voltage (24V DC) telemetry section of the electrical cabinet.
5. Connect earth ground (minimum $2.5\text{ mm}^2$ green/yellow grounding wire) directly to the main cabinet PE bus bar.
6. Connect the 24V DC primary and secondary power leads, verify correct polarity using a calibrated digital multimeter before powering on the unit.

---

## 5. PLC VENDOR-SPECIFIC CONFIGURATION PRE-REQUISITES

### 5.1 Siemens S7-1500 Configuration (TIA Portal v16+)
1. **Enable OPC UA Server:** In TIA Portal, open CPU Properties $\rightarrow$ `OPC UA` $\rightarrow$ `General` $\rightarrow$ Check `Activate OPC UA Server`.
2. **Server Port:** Ensure port `4840` is configured (default).
3. **Security Policies:**
   - Under `OPC UA` $\rightarrow$ `Security` $\rightarrow$ `Security Policies`, enable **`Basic256Sha256`**.
   - Check **`Sign & encrypt`**. Disable `None` (unencrypted communication is strictly prohibited).
4. **Data Block Accessibility:**
   - Open Telemetry Data Block `DB_Telemetry` (e.g. DB100).
   - In DB properties, uncheck `Optimized block access` if standard offset addressing is used, or leave enabled if using standard symbolic browsing.
   - For all 13 required telemetry tags, ensure `Accessible from HMI/OPC UA` is checked and `Writable from HMI/OPC UA` is unchecked or read-only.
5. **Compile & Download:** Perform software rebuild and download hardware configuration to the PLC during the maintenance window.

### 5.2 Beckhoff TwinCAT 3 Configuration
1. Install and activate **TF6100 TwinCAT OPC UA Server**.
2. In the TwinCAT Solution Explorer, configure the OPC UA server endpoint to port `4840`.
3. In PLC project, tag variables with the `{attribute 'OPC.UA' := '1'}` pragma for all 13 monitored signals.
4. Set security profile to `Basic256Sha256` with message security mode `SignAndEncrypt`.
5. Restart TwinCAT in Run Mode.

---

## 6. X.509 MUTUAL CERTIFICATE EXCHANGE SOP

Mutual certificate authentication ensures that only the authorized edge gateway can read PLC data, and the edge gateway only connects to the authentic verified PLC.

```
+--------------------------+                         +--------------------------+
|   Edge Gateway IPC       |                         |    Industrial PLC        |
|                          |                         |                          |
| 1. Generate Keypair      |                         |                          |
|    client_cert.pem       |  -- 2. Export Cert -->  | 3. Import to PLC Trusted |
|    client_key.pem (0600) |                         |    Client Store          |
|                          |                         |                          |
| 5. Import PLC Cert to    |  <-- 4. Export Cert --  |    Server Certificate    |
|    /trusted_certs/       |                         |    plc_cert.pem          |
|                          |                         |                          |
| 6. Preflight Validation  |  ====================>  | 7. Secure OPC UA Session |
|    (No 'None' fallback)  |   Basic256Sha256 Enc.   |    (Strictly Read-Only)  |
+--------------------------+                         +--------------------------+
```

### Step 1: Generate Edge Gateway Client Certificate
On the Edge Gateway IPC, execute:
```bash
python -m app.modules.connectivity.security \
  --generate-cert \
  --cert-dir /var/lib/pharmapredict/certs \
  --common-name "PharmaPredict Edge Gateway - Pilot 01" \
  --validity-days 365
```
Verify that `client_cert.pem` and `client_key.pem` exist and key permissions are `0600`.

### Step 2: Export Client Certificate to PLC
1. Copy `client_cert.pem` to a secure FAT32 engineering USB drive or transfer via secure SFTP.
2. In Siemens TIA Portal: Open `CPU Properties` $\rightarrow$ `OPC UA` $\rightarrow$ `Certificate Manager` $\rightarrow$ `Trusted Clients` $\rightarrow$ `Import`.
3. Select `client_cert.pem` and commit changes to the PLC.

### Step 3: Export PLC Server Certificate to Edge Gateway
1. In TIA Portal: Open `Certificate Manager` $\rightarrow$ `Server Certificates` $\rightarrow$ Export the PLC server certificate (e.g., `plc_server.der` or `plc_cert.pem`).
2. If in DER format, convert to PEM:
   ```bash
   openssl x509 -inform DER -in plc_server.der -outform PEM -out /var/lib/pharmapredict/trusted_certs/plc_cert.pem
   ```
3. Place the file in `/var/lib/pharmapredict/trusted_certs/plc_cert.pem`.

---

## 7. PREFLIGHT DIAGNOSTIC EXECUTION

Before launching live data acquisition, run the non-intrusive preflight diagnostic utility:
```bash
python backend/gateway/edge_preflight.py \
  --config /etc/pharmapredict/pilot_config.json \
  --buffer-dir /var/lib/pharmapredict/buffer
```
Verify the output:
- `configuration_validation`: **`PASSED`**
- `os_and_architecture`: **`PASSED`** (Linux x86_64 or aarch64)
- `system_resources`: **`PASSED`** (Free disk $\ge 5000\text{ MB}$, RAM $\ge 2048\text{ MB}$)
- `x509_certificates`: **`PASSED`** (Client cert and server cert verified)
- `network_connectivity`: **`PASSED`** (OPC UA port 4840 and Cloud port 443 reachable)

---

## 8. PLC TAG DISCOVERY & HUMAN COMMISSIONING (PHASES 8 & 9)

### Step 1: Execute Standalone Tag Discovery
Connect to the physical PLC and browse the address space without writing:
```bash
python backend/gateway/tag_discovery.py \
  --endpoint opc.tcp://192.168.10.50:4840 \
  --security-mode SignAndEncrypt \
  --security-policy Basic256Sha256 \
  --client-cert /var/lib/pharmapredict/certs/client_cert.pem \
  --client-key /var/lib/pharmapredict/certs/client_key.pem \
  --trusted-cert /var/lib/pharmapredict/trusted_certs/plc_cert.pem \
  --asset-code PILOT-BPK-01 \
  --output-dir /var/lib/pharmapredict/discovery
```
Outputs generated:
- `/var/lib/pharmapredict/discovery/discovered_nodes.json`
- `/var/lib/pharmapredict/discovery/signal_mapping_template.json`

### Step 2: Human-in-the-Loop Signal Approval in Cloud UI
1. Log in to the PharmaPredict UI as an authorized **Maintenance Engineer**.
2. Navigate to `Equipment` $\rightarrow$ `Pilot Commissioning` $\rightarrow$ `Import Discovery`.
3. Upload `signal_mapping_template.json`.
4. Review the 13 canonical signals against electrical schematics:
   - Verify `sealing_temperature` maps to the thermocouple on Station 2.
   - Verify `motor_vibration` maps to the drive motor accelerometer.
   - Verify engineering units match PLC scaling (°C, mm/s, bar, CPM).
5. Review validation checks (0 errors, no duplicates).
6. Click **`Approve & Activate Configuration`**.
7. Audit log records the action with user identity, timestamp, and digital signature.

---

## 9. LIVE TELEMETRY INGESTION & 24-HOUR SHADOW MONITORING

### Step 1: Launch Edge Gateway Service
```bash
sudo systemctl enable --now pharmapredict-edge.service
sudo systemctl status pharmapredict-edge.service
```

### Step 2: Verify Initial Telemetry Flow
Verify logs show active reading acquisition:
```bash
journalctl -u pharmapredict-edge.service -f
```
Expected output:
```
INFO: Connected to OPC UA Server: opc.tcp://192.168.10.50:4840 (SignAndEncrypt/Basic256Sha256)
INFO: Subscribed to 13 monitored nodes. Sampling interval: 1000ms.
INFO: Flushed batch of 50 readings to cloud backend (HTTP 200, 142ms latency).
```

### Step 3: Complete 24-Hour Passive Shadow Monitoring
- Let the gateway collect telemetry passively in shadow mode for a minimum of 24 contiguous operating hours.
- Generate the formal observation report:
```bash
python backend/gateway/shadow_monitoring.py \
  --config /etc/pharmapredict/pilot_config.json \
  --output /var/lib/pharmapredict/reports/pilot_24h_monitoring_report.md
```

---

## 10. TROUBLESHOOTING PLAYBOOK

| Error Code / Symptom | Root Cause | Remediation Procedure |
|---|---|---|
| `BadSecurityChecksFailed` (0x80130000) | Server rejected edge client certificate. | Verify `client_cert.pem` is imported into PLC's trusted certificates list in TIA Portal. Check PLC system clock. |
| `BadCertificateUntrusted` (0x801A0000) | Gateway rejected PLC server certificate. | Verify PLC certificate is installed in `/var/lib/pharmapredict/trusted_certs/` and matches the server endpoint CN. |
| `ConnectionRefusedError` / Port 4840 | PLC OPC UA server inactive or network cable disconnected. | Check physical RJ45 connection on `NIC 1`. Verify OPC UA server is activated in PLC CPU properties. |
| Queue Depth Growth (> 500) | Cloud ingestion network offline. | Gateway disk buffering is operating normally. Verify `NIC 2` plant network connectivity and outbound port 443 firewall access. |
| Negative Latency / Clock Skew | Edge IPC clock drift. | Configure NTP client (`chrony` or `systemd-timesyncd`) against the local plant PTP/NTP time server. |

---

## 11. EMERGENCY DE-COMMISSIONING & ROLLBACK PROCEDURE

If any anomalous machine behavior occurs or if requested by the Area Supervisor:
1. Immediately stop the edge gateway service:
   ```bash
   sudo systemctl stop pharmapredict-edge.service
   ```
2. Disconnect the physical Ethernet cable from `NIC 1 (eth0)`.
3. The PLC operation is completely decoupled and remains unaffected (read-only architecture).
4. File an Incident Report and retain buffer logs in `/var/lib/pharmapredict/buffer` for root-cause analysis.
