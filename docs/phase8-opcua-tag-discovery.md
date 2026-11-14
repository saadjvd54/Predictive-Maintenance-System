# PharmaPredict AI — Phase 8: Standalone OPC UA PLC Tag Discovery Utility

## 1. Executive Summary

The **Standalone OPC UA PLC Tag Discovery Utility** (`backend/gateway/tag_discovery.py`) is a production-oriented, non-intrusive command-line tool designed for pharmaceutical factory pilot commissioning and site surveys. It connects to any standard OPC UA industrial server (Siemens S7-1500/1200, Beckhoff TwinCAT, Rockwell FactoryTalk, or software emulators), browses the industrial address space recursively, extracts engineering metadata, and automatically classifies sensor signals across 11 pharmaceutical monitoring categories.

Crucially, the utility enforces **strict read-only safety**, **zero-trust security validation**, and **human-in-the-loop governance**:
- It guarantees that no write operations, method executions, or state-altering commands are ever transmitted to plant floor PLCs.
- It prevents automated runtime ingestion until candidate signal mappings are reviewed and approved by a qualified automation engineer.
- It outputs structured JSON inventories and canonical signal mapping templates adhering directly to PharmaPredict AI's `MachineSignal` database schema.

---

## 2. Architectural Overview

```
+---------------------------------------------------------------------------------+
|                       Industrial Plant Floor Network                            |
|  +---------------------+  +----------------------+  +------------------------+  |
|  |  Siemens S7-1500    |  |  Beckhoff TwinCAT 3  |  |  PharmaOPCUASimulator  |  |
|  |  OPC UA Server      |  |  OPC UA Server       |  |  (Local / Testing)     |  |
|  +---------------------+  +----------------------+  +------------------------+  |
+---------------------------------------------------------------------------------+
                                         ^
                                         | OPC UA Binary (tcp / opc.tcp://)
                                         | Read-Only Sessions (Strictly No Writes)
                                         v
+---------------------------------------------------------------------------------+
|               Standalone OPC UA Tag Discovery Utility (Python 3.10+)            |
|                 File: backend/gateway/tag_discovery.py                          |
|                                                                                 |
|   +-----------------------+     +-----------------------+     +---------------+ |
|   |   OPCUATagDiscovery   | --> |   SignalClassifier    | --> | JSON Exporter | |
|   |  - Cycle Prevention   |     |  - 11 Categories      |     | - Nodes Inv.  | |
|   |  - Max Depth Limits   |     |  - Tokenizer / Regex  |     | - Canonical   | |
|   |  - Read-Only Guard    |     |  - Negative Context   |     |   Mapping Tpl | |
|   +-----------------------+     +-----------------------+     +---------------+ |
+---------------------------------------------------------------------------------+
                                         |
                                         v
+---------------------------------------------------------------------------------+
|                                Output Artifacts                                 |
|                                                                                 |
|   1. discovered_nodes.json            2. signal_mapping_template.json           |
|      Full hierarchical node inventory    Canonical mapping candidates           |
|      with engineering metadata, types,   for engineer review and validation     |
|      sampling rates, & current values.   before activating ingestion.           |
+---------------------------------------------------------------------------------+
```

---

## 3. Signal Classification Engine

The utility classifies industrial variable nodes using a deterministic, tokenized regex classifier with multi-attribute scoring and false-positive prevention guards:

### 3.1 Supported Telemetry Categories (11 Total)

| Category Enum | Canonical Code | Default Unit | Description & Target Equipment Context |
| :--- | :--- | :--- | :--- |
| `TEMPERATURE` | `TEMPERATURE` / `SEALING_TEMPERATURE` | `°C` | Sealing jaws, blister heaters, drive motor bearings, chillers. |
| `VIBRATION` | `MOTOR_VIBRATION` / `BEARING_VIBRATION` | `mm/s` | Main drive motor, cutting station, blister forming bearings. |
| `MOTOR_CURRENT` | `MOTOR_CURRENT` | `A` | Drive motors, servo drives, mechanical drag detection. |
| `ROTATIONAL_SPEED` | `ROTATIONAL_SPEED_RPM` | `RPM` | Drive shaft RPM, roller speeds, motor spindle velocity. |
| `LINE_SPEED` | `LINE_SPEED_CPM` | `CPM` | Blister packaging throughput, cartons/min, line speed. |
| `PRESSURE` | `FORMING_PRESSURE` | `bar` | Forming station pneumatic air, main manifold pressure. |
| `VACUUM` | `VACUUM_LEVEL` | `bar` | Blister cavity formation vacuum, pick-and-place suction. |
| `FLOW` | `FLOW_RATE` | `L/min` | Chilled water coolant loops, purge gas flow. |
| `ALARM_FAULT` | `ALARM_STATE` / `EMERGENCY_STOP_ACTIVE` | `status` | E-Stop interlocks, guard doors, machine fault alarms. |
| `CYCLE_COUNTER` | `CYCLE_COUNT` | `cycles` | Stroke counter, cutter actuations, cumulative cycles. |
| `PRODUCTION_COUNTER`| `PRODUCTION_COUNT` | `units` | Blister packs produced, batch good/reject pack totals. |

### 3.2 Confidence Scoring & Rating Levels

Each candidate variable is scored against a composite rubric:
- **Keyword / Token Match:** `+0.45` to `+0.55` (case-insensitive, tokenized camelCase, snake_case, dot.separated).
- **Unit Compatibility:** `+0.35` (matching engineering units e.g., `°C`, `mm/s`, `A`, `bar`, `RPM`, `CPM`).
- **Data Type Compatibility:** `+0.20` (matching schema types e.g., `Float`, `Double`, `Int32`, `Boolean`).

**Confidence Tiering:**
- **`HIGH`** ($\ge 0.70$): Definitive semantic match (e.g. matching token + unit or matching token + data type). Automatically designated as `CANDIDATE_FOR_REVIEW`.
- **`MEDIUM`** ($0.50 \le \text{Score} < 0.70$): Strong keyword match without unit confirmation. Designated as `CANDIDATE_FOR_REVIEW`.
- **`LOW`** ($0.30 \le \text{Score} < 0.50$): Weak keyword match. Placed in `unmapped_signals` for manual inspection.
- **`UNMAPPED`** ($< 0.30$): Generic or non-industrial variables. Placed in `unmapped_signals` without fabricated codes.

### 3.3 Anti-False-Positive Guards

1. **CamelCase Pre-Tokenization:** Splits compound identifiers (`CurrentTime`, `InsertDataCapability`, `MainDriveMotorVibration`) before lowercasing, preserving word boundaries.
2. **Negative Context Filters:** Rejects variables containing non-electrical tokens for motor current (`time`, `version`, `session`, `count`, `state`, `file`, `date`, `item`, `timestamp`). E.g., `CurrentTime` is never classified as `MOTOR_CURRENT`.
3. **Server Diagnostics Skipping:** Automatically bypasses `ns=0;i=2253` (`Objects / Server`) by default (`skip_server_diagnostics=True`) to avoid scanning internal OPC UA session and server metadata.

---

## 4. Security & Pharmaceutical Compliance

The utility adheres strictly to GAMP 5 and 21 CFR Part 11 operational safety guidelines:

1. **Strict Read-Only Enforcement:**
   - The utility contains zero OPC UA write routines (`ua.WriteValue`, `write_value`, `set_value`).
   - If any programmatic caller invokes `discovery.execute_write(...)`, the utility immediately raises `ReadOnlyViolationError` and aborts.
2. **Zero-Trust Security Downgrade Prevention:**
   - If secure policies are requested (`Basic256Sha256`, `Aes128_Sha256_RsaOaep`) but certificates/keys are missing, the utility raises `SecurityDowngradeError` rather than silently falling back to `None`.
3. **Credential Sanitization:**
   - Basic authentication passwords and private keys are never included in console output, JSON exports, or log files.
   - Output files retain only endpoint URLs and public metadata.
4. **Non-Intrusive Exploration:**
   - Recursion limits (`max_depth=10`, `max_nodes=10000`, `timeout_sec=10.0`) prevent gateway lockups, PLC buffer exhaustion, or network saturation.
   - Cycle tracking maintains a visited set of `NodeId` instances to prevent infinite traversal of circular OPC UA references.

---

## 5. CLI Installation & Usage

### 5.1 Environment Requirements

- Python 3.10, 3.11, 3.12, or 3.13
- Dependencies: `asyncua>=1.0.6`, `cryptography>=41.0.0`

### 5.2 Command Line Options

| Argument | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--endpoint` | string | `opc.tcp://127.0.0.1:48401/pharmapredict/server/` | Target OPC UA server endpoint URL. |
| `--root-node` | string | `i=85` (`Root.Objects`) | NodeId to initiate recursive discovery. |
| `--username` | string | None | Username for OPC UA user authentication. |
| `--password` | string | None | Password for OPC UA user authentication (never logged). |
| `--cert` | path | None | Client X.509 certificate file path (`.pem` / `.der`). |
| `--key` | path | None | Client private key file path (`.pem`). |
| `--security-policy` | string | `None` | `None`, `Basic256Sha256`, `Basic128Rsa15`, `Aes128_Sha256_RsaOaep`. |
| `--security-mode` | string | `None` | `None`, `Sign`, `SignAndEncrypt`. |
| `--max-depth` | int | `10` | Maximum recursion depth in hierarchical tree. |
| `--max-nodes` | int | `10000` | Maximum number of variable nodes to discover. |
| `--timeout` | float | `10.0` | Connection and discovery timeout in seconds. |
| `--output-dir` | path | `./discovery_output` | Destination directory for generated JSON files. |
| `--generate-template`| flag | `True` | Generates canonical `signal_mapping_template.json`. |
| `--machine-id` | UUID | None | Target registered equipment UUID. |
| `--asset-code` | string | `DEMO-BPK-200` | Machine asset identifier code. |
| `--site-id` | UUID | None | Manufacturing site UUID. |
| `--production-line-id`| UUID | None | Production line UUID. |
| `--read-values` | flag | `True` | Reads initial snapshot values of variable nodes. |
| `--include-server-diagnostics` | flag | `False` | Also browse internal `Objects/Server` diagnostics. |
| `--verbose` | flag | `False` | Enable DEBUG level logging. |
| `--quiet` | flag | `False` | Silence stdout except for summary JSON. |

### 5.3 Execution Examples

#### Windows PowerShell (Local Simulator Discovery)
```powershell
# Run discovery against local pharma blister machine simulator
& "backend\.venv\Scripts\python.exe" backend/gateway/tag_discovery.py `
  --endpoint "opc.tcp://127.0.0.1:48401/pharmapredict/server/" `
  --asset-code "DEMO-BPK-200" `
  --machine-id "0d9bba98-6ad9-417c-9543-ef024447ef04" `
  --output-dir "./discovery_output" `
  --read-values
```

#### Linux Industrial Edge Gateway (Secure Factory PLC Discovery)
```bash
# Secure encrypted discovery against physical plant PLC (e.g. Siemens S7-1500)
python3 backend/gateway/tag_discovery.py \
  --endpoint "opc.tcp://192.168.10.50:4840" \
  --root-node "ns=3;s=\"PLC_Data\"" \
  --security-policy "Basic256Sha256" \
  --security-mode "SignAndEncrypt" \
  --cert "/etc/pharmapredict/certs/client_cert.pem" \
  --key "/etc/pharmapredict/certs/client_key.pem" \
  --username "pilot_operator" \
  --password "$PLC_GATEWAY_PASSWORD" \
  --asset-code "LINE1-BLISTER-01" \
  --machine-id "0d9bba98-6ad9-417c-9543-ef024447ef04" \
  --output-dir "/var/log/pharmapredict/pilot" \
  --max-depth 8
```

---

## 6. Generated Output Files

The utility outputs two structured JSON documents into `--output-dir`:

### 6.1 `discovered_nodes.json` (Complete Address Space Inventory)
Contains comprehensive metadata for every accessible variable node:
```json
{
  "metadata": {
    "utility_version": "1.0.0",
    "discovery_timestamp": "2026-11-14T12:35:48.120531+00:00",
    "endpoint_url": "opc.tcp://127.0.0.1:48401/pharmapredict/server/",
    "root_node_id": "i=85",
    "total_variables_discovered": 20
  },
  "nodes": [
    {
      "node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
      "browse_name": "2:SealingTemperature",
      "display_name": "SealingTemperature",
      "parent_path": "Root / Objects / BlisterPackagingMachine_01",
      "data_type": "Double",
      "access_level": "CurrentRead",
      "unit": "°C",
      "current_value": 180.24,
      "read_status": "SUCCESS"
    }
  ]
}
```

### 6.2 `signal_mapping_template.json` (Canonical Mapping Candidates)
Formats discovered nodes directly into PharmaPredict AI's `MachineSignal` registration schema:
```json
{
  "metadata": {
    "utility_version": "1.0.0",
    "generation_timestamp": "2026-11-14T12:35:48.121531+00:00",
    "endpoint_url": "opc.tcp://127.0.0.1:48401/pharmapredict/server/",
    "asset_code": "DEMO-BPK-200",
    "machine_id": "0d9bba98-6ad9-417c-9543-ef024447ef04",
    "mapped_candidate_count": 13,
    "unmapped_candidate_count": 7,
    "instructions": "HUMAN REVIEW REQUIRED: Review suggested_signal_code, engineering_unit, and thresholds before activating."
  },
  "mapped_signals": [
    {
      "signal_id_placeholder": "sig_auto_ns_2_s_blisterpackagingmachine_01_sealingtemperature",
      "source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
      "browse_name": "2:SealingTemperature",
      "display_name": "SealingTemperature",
      "classification_category": "Temperature",
      "confidence_level": "HIGH",
      "confidence_score": 0.85,
      "suggested_signal_code": "SEALING_TEMPERATURE",
      "signal_group": "THERMAL",
      "engineering_unit": "°C",
      "data_type": "Double",
      "sampling_interval_ms": 1000,
      "warning_min": 170.0,
      "warning_max": 190.0,
      "critical_min": 160.0,
      "critical_max": 200.0,
      "mapping_status": "CANDIDATE_FOR_REVIEW",
      "reviewed_by": null,
      "review_notes": null
    }
  ],
  "unmapped_signals": []
}
```

---

## 7. Testing & Verification

The utility is accompanied by a dedicated automated test suite:
`Predictive-Maintenance-System/backend/tests/test_standalone_tag_discovery.py`

### Test Suite Results (15/15 Passed):
- `test_classifier_temperature`: Validates sealing and motor temperature tags.
- `test_classifier_vibration`: Validates drive and bearing vibration tags.
- `test_classifier_motor_current`: Validates electrical current tags.
- `test_classifier_rotational_speed`: Validates RPM tags.
- `test_classifier_line_speed`: Validates CPM blister throughput tags.
- `test_classifier_pressure_and_vacuum`: Validates bar pneumatic and vacuum tags.
- `test_classifier_alarms_and_estop`: Validates boolean alarm and safety interlock tags.
- `test_classifier_cycle_and_production_counters`: Validates stroke and batch counters.
- `test_classifier_negative_context_and_false_positive_guard`: Proves `CurrentTime` is not classified as motor current.
- `test_classifier_unmapped_generic`: Verifies generic nodes receive `UNMAPPED` confidence.
- `test_read_only_safety_guard`: Proves write attempts raise `ReadOnlyViolationError`.
- `test_security_downgrade_rejection`: Proves missing certificates with secure policies raise `SecurityDowngradeError`.
- `test_credentials_not_in_sanitized_config`: Verifies password scrubbed from exported configuration.
- `test_connection_failure_handling`: Verifies graceful failure when endpoint is unreachable.
- `test_full_discovery_against_simulator`: End-to-end integration test against live simulator on port 48435, discovering all 13 machine tags with `HIGH` confidence.

---

## 8. Physical PLC Pilot Commissioning Checklist

Before connecting this utility to a physical pharmaceutical PLC:

1. [ ] **Network Segmentation:** Ensure the laptop/gateway is on an isolated OT VLAN with no direct routable path to unauthorized WAN segments.
2. [ ] **Firewall Authorization:** Confirm outbound TCP traffic on the PLC's OPC UA port (default `4840`) is permitted by site network engineering.
3. [ ] **PLC Server Configuration:** Verify the PLC OPC UA server has an active user certificate or application certificate installed for the PharmaPredict client.
4. [ ] **Read-Only Authorization:** Verify the PLC user role assigned to PharmaPredict has only `CurrentRead` permissions in the PLC security matrix.
5. [ ] **Run Discovery:** Execute `backend/gateway/tag_discovery.py` pointing to the PLC endpoint.
6. [ ] **Inspect Output:** Review `discovered_nodes.json` and verify node paths and sampling rates.
7. [ ] **Validate Signal Template:** Review `signal_mapping_template.json` with the site automation engineer, fill in `warning_min`/`warning_max` thresholds, and sign off before database registration.

