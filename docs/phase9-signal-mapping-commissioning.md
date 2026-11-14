# PharmaPredict AI — Phase 9: Human-Approved Signal Mapping & Industrial Commissioning Workflow

## 1. Executive Summary

Phase 9 implements an enterprise-grade, human-in-the-loop commissioning and signal-mapping governance system for PharmaPredict AI. Building upon the Phase 8 read-only OPC UA discovery utility, Phase 9 bridges raw industrial PLC node inventories (`discovered_nodes.json` and `signal_mapping_template.json`) and live telemetry ingestion by requiring authorized human engineer sign-off before any signal can be activated into production.

Key system guarantees:
- **Zero PLC Writes:** Purely read-only downstream processing; no commands or control parameters are ever written to the physical equipment or PLC.
- **Strict Human Approval Gate:** No automatically discovered signal is ever ingested into live production or time-series storage without explicit review and approval by an authorized engineer.
- **Multi-Criteria Validation Guard:** Discovered signals are audited against 7 strict data integrity rules, preventing duplicate NodeIds, conflicting canonical assignments, incompatible data types, unit mismatches, and unsupported signal categories.
- **Auditable & Reversible Lifecycle:** Every mapping decision (edits, approvals, rejections, activations, and rollbacks) records the user identity, timestamp, decision, rationale, and exact field-level diffs into an immutable audit trail.
- **Preserved Existing Configurations:** Activating signals automatically supersedes previous versions without breaking existing telemetry ingestion or historical records.

---

## 2. Architectural Overview

```
+---------------------------------------------------------------------------------+
|                       PHASE 8 DISCOVERY OUTPUTS                                 |
|   discovered_nodes.json                   signal_mapping_template.json          |
|   (Complete OPC UA node hierarchy)        (Canonical suggestions & metadata)    |
+---------------------------------------------------------------------------------+
                                         |
                                         | POST /api/v1/equipment/<id>/commissioning/import
                                         v
+---------------------------------------------------------------------------------+
|                       COMMISSIONING SESSION (PHASE 9)                           |
|   State: DISCOVERED -> PENDING_REVIEW                                           |
|   Table: commissioning_sessions                                                 |
|   - session_name, machine_id, total_candidates, status, session_audit_trail     |
|                                                                                 |
|   Table: discovered_signal_candidates                                           |
|   - source_node_id, browse_name, data_type, raw_unit, raw_category              |
|   - proposed_canonical_signal, proposed_unit, proposed_category                 |
|   - validation_status, validation_errors, review_history                        |
+---------------------------------------------------------------------------------+
                                         |
                                         | Multi-Criteria Validation Engine
                                         | (7 automated data integrity rules)
                                         v
+---------------------------------------------------------------------------------+
|                       HUMAN REVIEW & APPROVAL WORKFLOW                          |
|   Role: MAINTENANCE_ENGINEER, MAINTENANCE_MANAGER, ORG_ADMIN                    |
|   Actions:                                                                      |
|     1. Search, filter by category / confidence score / status                   |
|     2. Correct canonical mapping, engineering unit, or scaling factor           |
|     3. Mark candidate APPROVED or REJECTED with human rationale                 |
+---------------------------------------------------------------------------------+
                                         |
                                         | POST /api/v1/commissioning/sessions/<id>/activate
                                         v
+---------------------------------------------------------------------------------+
|                       PRODUCTION REGISTRATION & PERSISTENCE                     |
|   Table: machine_signals (Active Production Signals)                            |
|   - Associates with machine, site, production line, and physical component      |
|   - Increments mapping_version, disables superseded versions                    |
|   - Session transitions to ACTIVATED; gateway now authorized to stream          |
|                                                                                 |
|   Table: commissioning_sessions (Reversible Rollback Capability)                |
|   - POST /api/v1/commissioning/sessions/<id>/rollback                          |
|   - Disables newly registered signals, reverts candidate states                 |
+---------------------------------------------------------------------------------+
```

---

## 3. Signal Review & Commissioning Interface

The Phase 9 frontend integration provides an intuitive, high-density interface embedded directly into the machine detail view (`/dashboard/equipment/[id]` -> **Commissioning Review (Phase 9)** tab):

### 3.1 Key Interface Capabilities
1. **Interactive Session Selector:** View all commissioning sessions for the selected machine, showing progress bars (`X / Y Approved`), session status badges, and creation dates.
2. **Import Trigger:** Single-click import of Phase 8 discovery outputs directly from the browser or automated pipeline.
3. **Faceted Filtering & Search:**
   - Filter by telemetry category (`TEMPERATURE`, `VIBRATION`, `PRESSURE`, `ROTATIONAL_SPEED`, `ALARM_FAULT`, etc.).
   - Filter by classification confidence level (High $\ge 0.85$, Medium $0.65-0.85$, Low $< 0.65$).
   - Filter by mapped vs unmapped status tabs.
   - Text search across BrowseName, NodeId, and canonical signal names.
4. **Interactive Correction Modal:** Allows authorized engineers to modify the proposed canonical signal code, change the engineering unit, tune scaling factors, and adjust sampling intervals before approval.
5. **Bulk Operations:** Multi-select valid candidates for instant batch approval or rejection with a shared engineering comment.
6. **Detailed Audit Trail Inspector:** View the full provenance for any candidate, including original discovery timestamp, review history diffs, previous values, reviewer identity, and human rationale.
7. **One-Click Activation & Rollback:** Safely push approved candidates into production `MachineSignal` records, or roll back in case of calibration discrepancies.

---

## 4. Multi-Criteria Validation Engine

Before any candidate can be transitioned to `APPROVED` or `ACTIVATED`, it is evaluated by the `CommissioningValidator` against seven non-negotiable industrial rules:

| Rule ID | Rule Name | Severity | Condition & Enforcement |
| :--- | :--- | :--- | :--- |
| **V1** | **Duplicate NodeId** | `ERROR` | Rejects multiple candidates within the same machine session mapped from the identical OPC UA NodeId. |
| **V2** | **Duplicate Canonical Signal** | `ERROR` | Prevents multiple sensor nodes from claiming the identical canonical signal name (e.g. two `forming_temperature` tags) unless explicitly bound to distinct physical `component_id` values. |
| **V3** | **Data Type Compatibility** | `ERROR` | Validates that the OPC UA source data type matches the canonical signal requirement (e.g. numeric types for physical analogs, `Boolean` for discrete alarms, rejecting strings/booleans mapped to numeric values). |
| **V4** | **Engineering Unit Compatibility**| `ERROR` | Verifies that the engineering unit is dimensionally compatible with the canonical standard (e.g. `°C`/`°F`/`K` for temperature, `bar`/`psi`/`kPa` for pressure, `mm/s` for vibration velocity). |
| **V5** | **Machine Identifier Presence** | `ERROR` | Confirms that the target machine ID is active and belongs to the authenticated tenant organization. |
| **V6** | **Unsupported Category** | `ERROR` | Restricts telemetry categories strictly to the 11 supported PharmaPredict AI industrial categories. |
| **V7** | **Confidence & Scaling Sanity** | `WARNING` | Emits cautionary warnings for AI confidence scores $< 0.65$ or scaling factors $\le 0$ to ensure intentional human review. |

---

## 5. Human Approval Workflow & Lifecycle States

The commissioning workflow enforces strict state-machine transitions:

```
    [ Phase 8 JSON ]
           |
           v
    +--------------+
    |  DISCOVERED  |  (Raw tags imported; initial automated validation executed)
    +--------------+
           |
           v
    +------------------+     Manual edit
    |  PENDING_REVIEW  | <-----------------+
    +------------------+                   |
        |          |                       |
        | Reject   | Approve               |
        v          v                       |
  +----------+   +----------+              |
  | REJECTED |   | APPROVED |              |
  +----------+   +----------+              |
                       |                   |
                       | Activate          |
                       v                   |
                 +-----------+             |
                 | ACTIVATED |             |
                 +-----------+             |
                       |                   |
                       | Rollback          |
                       +-------------------+
```

### State Definitions
- **`DISCOVERED`**: Initial state upon ingestion. Node metadata and suggested mappings are stored.
- **`PENDING_REVIEW`**: Candidate mappings are queued for human inspection. Validation status indicates `VALID` or `INVALID`.
- **`APPROVED`**: An authorized engineer has verified the NodeId, engineering unit, scaling factor, and canonical assignment. Candidates with validation errors cannot be approved.
- **`REJECTED`**: An engineer has marked the node irrelevant (e.g. internal PLC diagnostic counter, unneeded register) or incorrect. Rejected tags are skipped during activation.
- **`ACTIVATED`**: Approved candidates are committed into the production `MachineSignal` database table. The session is closed.
- **`CANCELLED`**: The entire commissioning session was aborted without impacting production signals.

---

## 6. Production MachineSignal Registration & Rollback

### 6.1 Versioning and Registration
When a commissioning session is activated:
1. All `APPROVED` candidates in the session are gathered within an atomic database transaction.
2. For each candidate, the existing `MachineSignal` records for `(machine_id, source_node_id)` are queried.
3. If an existing mapping exists, its current `mapping_version` is retrieved and disabled (`enabled=False`), and a new `MachineSignal` row is inserted with `mapping_version = current_version + 1`.
4. If no prior mapping exists, a new `MachineSignal` row is created with `mapping_version = 1`.
5. The candidate record is updated with `status = ACTIVATED` and `registered_machine_signal_id = new_signal.id`.
6. The parent `CommissioningSession` is marked `ACTIVATED`.

### 6.2 Transaction-Safe Rollback
If sensor calibration issues or configuration anomalies occur post-activation:
1. The engineer executes `POST /api/v1/commissioning/sessions/<id>/rollback`.
2. All `MachineSignal` records registered by that session are disabled (`enabled = False`).
3. Candidates are reverted to `status = APPROVED` and `registered_machine_signal_id = None`.
4. If an older `MachineSignal` version existed prior to activation, it is automatically re-enabled (`enabled = True`).
5. An immutable rollback audit log is recorded on the session.

---

## 7. REST API Reference

All endpoints are hosted under `/api/v1/` and enforce JWT/Session authentication and Role-Based Access Control:

### Session & Candidate Endpoints
| HTTP Method | Path | Required Role | Description |
| :--- | :--- | :--- | :--- |
| `POST` | `/equipment/<id>/commissioning/import` | `MAINTENANCE_ENGINEER`+ | Imports Phase 8 JSON payload and initializes a review session. |
| `GET` | `/equipment/<id>/commissioning/sessions` | `VIEWER`+ | Lists all commissioning sessions for the specified machine. |
| `GET` | `/commissioning/sessions/<id>` | `VIEWER`+ | Retrieves session summary, candidate counts, and audit logs. |
| `GET` | `/commissioning/sessions/<id>/candidates` | `VIEWER`+ | Retrieves candidates with optional `category`, `confidence`, and `status` filters. |
| `GET` | `/commissioning/candidates/<id>` | `VIEWER`+ | Retrieves single candidate details, validation errors, and review diffs. |
| `PUT` | `/commissioning/candidates/<id>` | `MAINTENANCE_ENGINEER`+ | Manually updates canonical signal, unit, scaling, or category. |
| `POST` | `/commissioning/candidates/<id>/review` | `MAINTENANCE_ENGINEER`+ | Approves or rejects an individual candidate with human rationale. |
| `POST` | `/commissioning/sessions/<id>/bulk-review` | `MAINTENANCE_ENGINEER`+ | Batch approves or rejects a list of candidate IDs. |
| `POST` | `/commissioning/sessions/<id>/activate` | `MAINTENANCE_ENGINEER`+ | Persists all approved candidates to `MachineSignal` production records. |
| `POST` | `/commissioning/sessions/<id>/rollback` | `MAINTENANCE_ENGINEER`+ | Safely disables registered signals and reverts session state. |

---

## 8. Security, RBAC & Audit Trail Integrity

### 8.1 Role-Based Access Control
- **`PLATFORM_ADMIN` / `ORG_ADMIN` / `MAINTENANCE_MANAGER` / `MAINTENANCE_ENGINEER`**: Full permissions to import discovery outputs, edit mappings, approve/reject candidates, activate into production, and trigger rollbacks.
- **`VIEWER`**: Read-only access to view sessions, candidates, and audit histories. Direct mutation calls return HTTP 403 Forbidden.
- **Unauthenticated**: All requests rejected with HTTP 401 Unauthorized.

### 8.2 Audit Trail Diff Tracking
Whenever an authorized engineer updates a candidate mapping, the previous state and new state are diffed and stored in the `review_history` JSONB column:
```json
{
  "timestamp": "2026-11-14T13:05:00Z",
  "action": "MANUAL_CORRECTION",
  "user_id": "f3464271-6279-4de3-bd2b-ef7c52f9a4f3",
  "diff": {
    "proposed_unit": {"from": "bar", "to": "mbar"},
    "scaling_factor": {"from": 1.0, "to": 0.001}
  },
  "reason": "Corrected vacuum sensor unit scaling per OEM wiring diagram"
}
```

---

## 9. Blister Packaging Machine Demonstration (`DEMO-BPK-200`)

The commissioning workflow was verified against the registered demo packaging machine:
- **Machine Name:** DEMO — Uhlen Blister Packaging Machine BPK-200
- **Asset Code:** `DEMO-BPK-200`
- **Machine ID:** `0d9bba98-6ad9-417c-9543-ef024447ef04`
- **Commissioned Signals (13 Total):**
  1. `forming_temperature` (`ns=2;s=Device.FormingTemperature`, `°C`)
  2. `sealing_temperature` (`ns=2;s=Device.SealingTemperature`, `°C`)
  3. `drive_motor_vibration` (`ns=2;s=Device.MotorVibration`, `mm/s`)
  4. `cutting_station_vibration` (`ns=2;s=Device.CutterVibration`, `mm/s`)
  5. `main_drive_current` (`ns=2;s=Device.MotorCurrent`, `A`)
  6. `drive_shaft_rpm` (`ns=2;s=Device.DriveShaftRPM`, `RPM`)
  7. `line_speed_cpm` (`ns=2;s=Device.LineSpeedCPM`, `CPM`)
  8. `forming_pressure` (`ns=2;s=Device.FormingPressure`, `bar`)
  9. `vacuum_level` (`ns=2;s=Device.VacuumLevel`, `bar`)
  10. `chilled_water_flow` (`ns=2;s=Device.CoolantFlowRate`, `L/min`)
  11. `cycle_counter` (`ns=2;s=Device.CycleCounter`, `cycles`)
  12. `machine_alarm_state` (`ns=2;s=Device.MachineAlarm`, `status`)
  13. `emergency_stop_tripped` (`ns=2;s=Device.EmergencyStop`, `status`)

---

## 10. Operational Guidelines for Commissioning Engineers

1. **Conduct Physical Site Survey:** Run Phase 8 `tag_discovery.py` against the machine's OPC UA endpoint to generate `discovered_nodes.json` and `signal_mapping_template.json`.
2. **Import via Commissioning Panel:** Navigate to the equipment detail view in the PharmaPredict AI UI and import the discovery files.
3. **Review High & Low Confidence Signals:** Filter by confidence score. Pay special attention to low-confidence tags ($< 0.65$) to ensure appropriate canonical names.
4. **Disambiguate Shared Canonical Codes:** If two vibration sensors exist (e.g. drive motor vs cutting station), assign distinct physical component identifiers.
5. **Execute Multi-Criteria Validation:** Ensure zero validation errors remain across all candidate tags.
6. **Obtain Engineering Sign-off:** Bulk approve the verified signals with an audit comment documenting calibration dates and OEM schematic references.
7. **Activate into Production:** Click **Activate Approved Signals**. Verify that `MachineSignal` records are active and begin streaming telemetry via Edge Gateway.

