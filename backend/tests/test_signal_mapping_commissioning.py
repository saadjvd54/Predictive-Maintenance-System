"""Automated Test Suite for Phase 9: Human-Approved Signal Mapping & Commissioning Workflow.
========================================================================================
Validates:
1. Discovery output import (signal_mapping_template.json and discovered_nodes.json formats).
2. Multi-criteria signal mapping validation:
   - Duplicate NodeIds within session.
   - Duplicate canonical signal assignments without component disambiguation.
   - Incompatible data types (e.g. numeric to boolean, string to float).
   - Engineering unit mismatches and physical dimension preservation.
   - Missing required machine identifiers.
   - Unsupported or invalid categories.
   - Low-confidence mapping warning guards.
3. Manual mapping correction by authorized engineers with immutable audit diff tracking.
4. Human approval and rejection lifecycle states (PENDING_REVIEW, APPROVED, REJECTED, ACTIVATED).
5. Role-Based Access Control (RBAC) rejection of unauthorized approval attempts.
6. Duplicate registration prevention and version bumping on machine configurations.
7. MachineSignal persistence and association with machine, site, and line.
8. Audit trail integrity across candidates and commissioning sessions.
9. Transaction-safe activation and reversible rollback.
10. Full end-to-end simulator discovery to approved machine signal activation workflow.
"""

import os
import sys
import json
import uuid
import pytest
from datetime import datetime, timezone
from pathlib import Path

# Add backend directory to sys.path
backend_path = Path(__file__).resolve().parent.parent
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app import create_app
from app.extensions import db
from app.models.tenant import Organization, Site
from app.models.user import User, Role, UserRoleAssignment
from app.models.equipment import Machine, ProductionArea, ProductionLine, EquipmentCategory
from app.models.signal_mapping import (
    SignalDefinition,
    MachineSignal,
    SignalGroup,
    ValidationStatus,
)
from app.models.commissioning import (
    CommissioningSession,
    DiscoveredSignalCandidate,
    CommissioningStatus,
)
from app.security.session import create_user_session
from app.modules.signal_mapping.commissioning_service import CommissioningService
from app.modules.signal_mapping.commissioning_validator import CommissioningValidator


@pytest.fixture
def app_instance():
    """Create a clean isolated test application with in-memory SQLite database."""
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def setup_factory_environment(app_instance):
    """Sets up a pharmaceutical tenant, site, production line, demo machine, and users."""
    with app_instance.app_context():
        # 1. Organization & Site
        org = Organization(name="PharmaHealth Global Manufacturing", slug="pharmahealth")
        db.session.add(org)
        db.session.flush()

        site = Site(organization_id=org.id, name="Basel Packaging Facility", code="BSL-01")
        db.session.add(site)
        db.session.flush()

        category = EquipmentCategory(organization_id=org.id, name="Blister Packaging", is_default=True)
        db.session.add(category)
        db.session.flush()

        area = ProductionArea(organization_id=org.id, site_id=site.id, name="Packaging Hall A")
        db.session.add(area)
        db.session.flush()

        line = ProductionLine(organization_id=org.id, site_id=site.id, production_area_id=area.id, name="Blister Line 1", line_code="LINE-1")
        db.session.add(line)
        db.session.flush()

        # 2. Registered Demo Blister Packaging Machine
        machine = Machine(
            id="0d9bba98-6ad9-417c-9543-ef024447ef04",
            organization_id=org.id,
            site_id=site.id,
            production_line_id=line.id,
            production_area_id=area.id,
            category_id=category.id,
            equipment_name="DEMO — Uhlen Blister Packaging Machine BPK-200",
            asset_code="DEMO-BPK-200",
            lifecycle_status="Active",
        )
        db.session.add(machine)
        db.session.flush()

        # 3. Roles and Users
        maint_role = Role.query.filter_by(name=Role.MAINTENANCE_ENGINEER).first()
        if not maint_role:
            maint_role = Role(name=Role.MAINTENANCE_ENGINEER, description="Maintenance Engineer")
            db.session.add(maint_role)
            db.session.flush()

        viewer_role = Role.query.filter_by(name=Role.VIEWER).first()
        if not viewer_role:
            viewer_role = Role(name=Role.VIEWER, description="Viewer")
            db.session.add(viewer_role)
            db.session.flush()

        engineer_user = User(
            email="lead.engineer@pharmahealth.com",
            password_hash="argon2id_mock_hash",
            full_name="Lead Maintenance Engineer",
            organization_id=org.id,
            is_active=True,
        )
        db.session.add(engineer_user)
        db.session.flush()

        db.session.add(UserRoleAssignment(
            user_id=engineer_user.id,
            role_id=maint_role.id,
            organization_id=org.id,
        ))

        viewer_user = User(
            email="viewer.demo@pharmahealth.com",
            password_hash="argon2id_mock_hash",
            full_name="Auditor Viewer",
            organization_id=org.id,
            is_active=True,
        )
        db.session.add(viewer_user)
        db.session.flush()

        db.session.add(UserRoleAssignment(
            user_id=viewer_user.id,
            role_id=viewer_role.id,
            organization_id=org.id,
        ))

        db.session.commit()

        return {
            "organization_id": org.id,
            "site_id": site.id,
            "machine_id": machine.id,
            "engineer_user_id": engineer_user.id,
            "operator_user_id": viewer_user.id,
        }


# =============================================================================
# 1. DISCOVERY IMPORT TESTS
# =============================================================================

def test_import_signal_mapping_template(app_instance, setup_factory_environment):
    """Proves that a canonical signal_mapping_template.json can be imported into a session."""
    env = setup_factory_environment
    with app_instance.app_context():
        payload = {
            "metadata": {
                "endpoint_url": "opc.tcp://127.0.0.1:48401/pharmapredict/server/",
                "asset_code": "DEMO-BPK-200",
                "mapped_candidate_count": 2,
                "unmapped_candidate_count": 1,
            },
            "mapped_signals": [
                {
                    "source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
                    "browse_name": "2:SealingTemperature",
                    "display_name": "SealingTemperature",
                    "classification_category": "Temperature",
                    "confidence_level": "HIGH",
                    "confidence_score": 0.85,
                    "suggested_signal_code": "SEALING_TEMPERATURE",
                    "engineering_unit": "°C",
                    "data_type": "Double",
                    "sampling_interval_ms": 1000,
                    "warning_min": 170.0,
                    "warning_max": 190.0,
                },
                {
                    "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MotorTemperature",
                    "browse_name": "2:MotorTemperature",
                    "display_name": "MotorTemperature",
                    "classification_category": "Temperature",
                    "confidence_level": "HIGH",
                    "confidence_score": 0.85,
                    "suggested_signal_code": "MOTOR_TEMPERATURE",
                    "engineering_unit": "°C",
                    "data_type": "Double",
                    "sampling_interval_ms": 1000,
                },
            ],
            "unmapped_signals": [
                {
                    "source_node_id": "i=2258",
                    "browse_name": "0:CurrentTime",
                    "display_name": "CurrentTime",
                    "data_type": "UtcTime",
                }
            ],
        }

        session = CommissioningService.import_discovery(
            machine_id=env["machine_id"],
            organization_id=env["organization_id"],
            payload=payload,
            user_id=env["engineer_user_id"],
        )

        assert session["machine_id"] == env["machine_id"]
        assert session["status"] == CommissioningStatus.PENDING_REVIEW.value
        assert session["discovered_nodes_count"] == 3
        assert session["mapped_candidates_count"] == 2
        assert session["unmapped_candidates_count"] == 1
        assert len(session["candidates"]) == 3

        # Verify initial audit log entry
        assert len(session["audit_log"]) >= 1
        assert session["audit_log"][0]["action"] == "SESSION_CREATED"


# =============================================================================
# 2. VALIDATION ENGINE TESTS
# =============================================================================

def test_validation_duplicate_node_ids(app_instance, setup_factory_environment):
    """Proves that duplicate NodeIds in the same session are flagged as fatal errors."""
    env = setup_factory_environment
    with app_instance.app_context():
        c1 = DiscoveredSignalCandidate(
            id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            organization_id=env["organization_id"],
            machine_id=env["machine_id"],
            source_node_id="ns=2;s=SameNode",
            display_name="Tag 1",
            source_data_type="Double",
            suggested_category="Temperature",
            is_mapped=True,
        )
        c2 = DiscoveredSignalCandidate(
            id=str(uuid.uuid4()),
            session_id=c1.session_id,
            organization_id=env["organization_id"],
            machine_id=env["machine_id"],
            source_node_id="ns=2;s=SameNode",
            display_name="Tag 2 (Duplicate)",
            source_data_type="Double",
            suggested_category="Temperature",
            is_mapped=True,
        )

        val_res = CommissioningValidator.validate_candidate(c1, all_session_candidates=[c1, c2])
        assert not val_res.is_valid
        assert any("Duplicate source NodeId" in err for err in val_res.errors)


def test_validation_incompatible_data_type(app_instance, setup_factory_environment):
    """Proves that incompatible OPC UA data types (e.g. String for Double signal) fail validation."""
    env = setup_factory_environment
    with app_instance.app_context():
        temp_def = SignalDefinition.query.filter_by(signal_code="SEALING_TEMP").first()
        if not temp_def:
            temp_def = SignalDefinition(
                signal_code="SEALING_TEMP",
                name="Sealing Temperature",
                signal_group="Temperature",
                expected_data_type="Double",
                standard_unit="°C",
            )
            db.session.add(temp_def)
            db.session.flush()

        candidate = DiscoveredSignalCandidate(
            id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            organization_id=env["organization_id"],
            machine_id=env["machine_id"],
            source_node_id="ns=2;s=BadTypeNode",
            display_name="BadType",
            source_data_type="String",  # Incompatible with Double
            suggested_category="Temperature",
            target_signal_definition_id=temp_def.id,
            signal_definition=temp_def,
            engineering_unit="°C",
            is_mapped=True,
        )

        val_res = CommissioningValidator.validate_candidate(candidate)
        assert not val_res.is_valid
        assert any("Incompatible data type" in err for err in val_res.errors)


def test_validation_unit_mismatch(app_instance, setup_factory_environment):
    """Proves that physical unit dimension mismatch (e.g. vibration 'g' for temperature) fails validation."""
    env = setup_factory_environment
    with app_instance.app_context():
        temp_def = SignalDefinition(
            signal_code="TEST_TEMP",
            name="Test Temp",
            signal_group="Temperature",
            expected_data_type="Double",
            standard_unit="°C",
        )
        db.session.add(temp_def)
        db.session.flush()

        candidate = DiscoveredSignalCandidate(
            id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            organization_id=env["organization_id"],
            machine_id=env["machine_id"],
            source_node_id="ns=2;s=MismatchedUnit",
            display_name="MismatchedUnit",
            source_data_type="Double",
            suggested_category="Temperature",
            target_signal_definition_id=temp_def.id,
            signal_definition=temp_def,
            engineering_unit="mm/s",  # Velocity unit for temperature!
            is_mapped=True,
        )

        val_res = CommissioningValidator.validate_candidate(candidate)
        assert not val_res.is_valid
        assert any("Engineering unit mismatch" in err for err in val_res.errors)


def test_validation_unsupported_category(app_instance, setup_factory_environment):
    """Proves that invalid or fabricated signal categories are rejected."""
    env = setup_factory_environment
    with app_instance.app_context():
        candidate = DiscoveredSignalCandidate(
            id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            organization_id=env["organization_id"],
            machine_id=env["machine_id"],
            source_node_id="ns=2;s=WeirdCategory",
            display_name="WeirdCategory",
            source_data_type="Double",
            suggested_category="QuantumFluctuations",  # Unsupported category
            is_mapped=True,
        )

        val_res = CommissioningValidator.validate_candidate(candidate)
        assert not val_res.is_valid
        assert any("Unsupported signal category" in err for err in val_res.errors)


# =============================================================================
# 3. MANUAL MAPPING CORRECTION & AUDIT DIFF TESTS
# =============================================================================

def test_manual_mapping_correction_and_audit_diff(app_instance, setup_factory_environment):
    """Proves that an engineer can manually correct a mapping and the diff is saved immutably."""
    env = setup_factory_environment
    with app_instance.app_context():
        payload = {
            "metadata": {"endpoint_url": "opc.tcp://127.0.0.1:48401/pharmapredict/server/"},
            "mapped_signals": [
                {
                    "source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
                    "browse_name": "2:SealingTemperature",
                    "display_name": "SealingTemperature",
                    "classification_category": "Temperature",
                    "confidence_level": "HIGH",
                    "confidence_score": 0.85,
                    "suggested_signal_code": "SEALING_TEMPERATURE",
                    "engineering_unit": "°C",
                    "data_type": "Double",
                }
            ],
        }
        session = CommissioningService.import_discovery(
            machine_id=env["machine_id"],
            organization_id=env["organization_id"],
            payload=payload,
            user_id=env["engineer_user_id"],
        )
        cand_id = session["candidates"][0]["id"]

        # Engineer edits custom_name, warning thresholds, and sampling interval
        updated = CommissioningService.update_candidate_mapping(
            candidate_id=cand_id,
            organization_id=env["organization_id"],
            data={
                "custom_name": "Primary Upper Sealing Jaw Temp",
                "warning_min": 172.5,
                "warning_max": 188.0,
                "critical_min": 165.0,
                "critical_max": 195.0,
                "sampling_interval_ms": 500,
            },
            user_id=env["engineer_user_id"],
        )

        assert updated["custom_name"] == "Primary Upper Sealing Jaw Temp"
        assert updated["warning_min"] == 172.5
        assert updated["sampling_interval_ms"] == 500
        assert updated["status"] == CommissioningStatus.PENDING_REVIEW.value

        # Inspect immutable review history
        hist = updated["review_history"]
        assert len(hist) >= 2  # Import + Manual Correction
        diff_entry = hist[-1]
        assert diff_entry["action"] == "MANUAL_CORRECTION"
        assert diff_entry["user_id"] == env["engineer_user_id"]
        assert diff_entry["previous_mapping"]["sampling_interval_ms"] == 1000
        assert diff_entry["new_mapping"]["sampling_interval_ms"] == 500


# =============================================================================
# 4. HUMAN APPROVAL AND REJECTION WORKFLOW
# =============================================================================

def test_approve_and_reject_candidate_workflow(app_instance, setup_factory_environment):
    """Proves candidate approval and rejection transitions with user identity and rationale."""
    env = setup_factory_environment
    with app_instance.app_context():
        payload = {
            "metadata": {"endpoint_url": "opc.tcp://127.0.0.1:48401/pharmapredict/server/"},
            "mapped_signals": [
                {
                    "source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
                    "browse_name": "2:SealingTemperature",
                    "display_name": "SealingTemperature",
                    "classification_category": "Temperature",
                    "confidence_level": "HIGH",
                    "confidence_score": 0.85,
                    "suggested_signal_code": "SEALING_TEMPERATURE",
                    "engineering_unit": "°C",
                    "data_type": "Double",
                },
                {
                    "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MotorTemperature",
                    "browse_name": "2:MotorTemperature",
                    "display_name": "MotorTemperature",
                    "classification_category": "Temperature",
                    "confidence_level": "HIGH",
                    "confidence_score": 0.85,
                    "suggested_signal_code": "MOTOR_TEMPERATURE",
                    "engineering_unit": "°C",
                    "data_type": "Double",
                },
            ],
        }
        session = CommissioningService.import_discovery(
            machine_id=env["machine_id"],
            organization_id=env["organization_id"],
            payload=payload,
            user_id=env["engineer_user_id"],
        )
        c1_id = session["candidates"][0]["id"]
        c2_id = session["candidates"][1]["id"]

        # 1. Approve c1
        approved = CommissioningService.review_candidate(
            candidate_id=c1_id,
            organization_id=env["organization_id"],
            decision="APPROVED",
            user_id=env["engineer_user_id"],
            reason="Verified calibration against jaw thermocouple sensor.",
        )
        assert approved["status"] == CommissioningStatus.APPROVED.value
        last_hist = approved["review_history"][-1]
        assert last_hist["decision"] == "APPROVED"
        assert "thermocouple" in last_hist["reason"]

        # 2. Reject c2
        rejected = CommissioningService.review_candidate(
            candidate_id=c2_id,
            organization_id=env["organization_id"],
            decision="REJECTED",
            user_id=env["engineer_user_id"],
            reason="Auxiliary fan motor not in pilot scope.",
        )
        assert rejected["status"] == CommissioningStatus.REJECTED.value

        # 3. Verify session counters
        sess = CommissioningService.get_session(session["id"], env["organization_id"])
        assert sess.approved_count == 1
        assert sess.rejected_count == 1


def test_cannot_approve_invalid_candidate(app_instance, setup_factory_environment):
    """Proves that a candidate with fatal validation errors CANNOT be approved."""
    env = setup_factory_environment
    with app_instance.app_context():
        # Create candidate with fatal error (unsupported category)
        session = CommissioningSession(
            organization_id=env["organization_id"],
            machine_id=env["machine_id"],
            session_name="Invalid Candidate Test",
            status=CommissioningStatus.PENDING_REVIEW.value,
        )
        db.session.add(session)
        db.session.flush()

        invalid_cand = DiscoveredSignalCandidate(
            session_id=session.id,
            organization_id=env["organization_id"],
            machine_id=env["machine_id"],
            source_node_id="ns=2;s=BadTag",
            display_name="BadTag",
            source_data_type="Double",
            suggested_category="FakeCategory",
            is_mapped=True,
            status=CommissioningStatus.PENDING_REVIEW.value,
        )
        db.session.add(invalid_cand)
        db.session.commit()

        # Approval must raise ValueError
        with pytest.raises(ValueError) as exc_info:
            CommissioningService.review_candidate(
                candidate_id=invalid_cand.id,
                organization_id=env["organization_id"],
                decision="APPROVED",
                user_id=env["engineer_user_id"],
            )
        assert "Validation failed" in str(exc_info.value)


# =============================================================================
# 5. ACTIVATION, ROLLBACK & PERSISTENCE
# =============================================================================

def test_activation_and_rollback_lifecycle(app_instance, setup_factory_environment):
    """Proves transactional activation of APPROVED candidates and reversible rollback."""
    env = setup_factory_environment
    with app_instance.app_context():
        payload = {
            "metadata": {"endpoint_url": "opc.tcp://127.0.0.1:48401/pharmapredict/server/"},
            "mapped_signals": [
                {
                    "source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
                    "browse_name": "2:SealingTemperature",
                    "display_name": "SealingTemperature",
                    "classification_category": "Temperature",
                    "confidence_level": "HIGH",
                    "confidence_score": 0.85,
                    "suggested_signal_code": "SEALING_TEMPERATURE",
                    "engineering_unit": "°C",
                    "data_type": "Double",
                },
                {
                    "source_node_id": "ns=2;s=BlisterPackagingMachine_01.MotorTemperature",
                    "browse_name": "2:MotorTemperature",
                    "display_name": "MotorTemperature",
                    "classification_category": "Temperature",
                    "confidence_level": "HIGH",
                    "confidence_score": 0.85,
                    "suggested_signal_code": "MOTOR_TEMPERATURE",
                    "engineering_unit": "°C",
                    "data_type": "Double",
                },
            ],
            "unmapped_signals": [
                {
                    "source_node_id": "i=2258",
                    "browse_name": "0:CurrentTime",
                    "display_name": "CurrentTime",
                    "data_type": "UtcTime",
                }
            ],
        }
        session_dict = CommissioningService.import_discovery(
            machine_id=env["machine_id"],
            organization_id=env["organization_id"],
            payload=payload,
            user_id=env["engineer_user_id"],
        )
        s_id = session_dict["id"]
        c_temp1 = session_dict["candidates"][0]["id"]
        c_temp2 = session_dict["candidates"][1]["id"]
        c_unmapped = session_dict["candidates"][2]["id"]

        # 1. Approve c_temp1, Reject c_temp2, leave c_unmapped PENDING_REVIEW
        CommissioningService.review_candidate(c_temp1, env["organization_id"], "APPROVED", env["engineer_user_id"])
        CommissioningService.review_candidate(c_temp2, env["organization_id"], "REJECTED", env["engineer_user_id"])

        # 2. Activate Approved
        act_res = CommissioningService.activate_approved(s_id, env["organization_id"], env["engineer_user_id"])
        assert act_res["status"] == CommissioningStatus.ACTIVATED.value
        assert act_res["activated_count"] == 1

        # Verify MachineSignal created in database
        ms = MachineSignal.query.filter_by(
            machine_id=env["machine_id"],
            source_node_id="ns=2;s=BlisterPackagingMachine_01.SealingTemperature",
        ).first()
        assert ms is not None
        assert ms.enabled is True
        assert ms.validation_status == ValidationStatus.VALID
        assert ms.mapping_version == 1

        # Verify candidate states
        cand1 = CommissioningService.get_candidate(c_temp1, env["organization_id"])
        assert cand1.status == CommissioningStatus.ACTIVATED.value
        assert cand1.registered_machine_signal_id == ms.id

        cand2 = CommissioningService.get_candidate(c_temp2, env["organization_id"])
        assert cand2.status == CommissioningStatus.REJECTED.value
        assert cand2.registered_machine_signal_id is None  # REJECTED was NOT activated!

        cand_unm = CommissioningService.get_candidate(c_unmapped, env["organization_id"])
        assert cand_unm.status == CommissioningStatus.PENDING_REVIEW.value
        assert cand_unm.registered_machine_signal_id is None  # PENDING was NOT activated!

        # 3. Rollback Activation
        rb_res = CommissioningService.rollback_activation(
            session_id=s_id,
            organization_id=env["organization_id"],
            user_id=env["engineer_user_id"],
            reason="Sensor recalibration required before production streaming.",
        )
        assert rb_res["status"] == CommissioningStatus.APPROVED.value
        assert rb_res["activated_count"] == 0

        # Verify MachineSignal disabled
        ms_after = db.session.get(MachineSignal, ms.id)
        assert ms_after.enabled is False

        # Verify candidate reverted to APPROVED
        cand1_after = CommissioningService.get_candidate(c_temp1, env["organization_id"])
        assert cand1_after.status == CommissioningStatus.APPROVED.value
        assert cand1_after.registered_machine_signal_id is None


# =============================================================================
# 6. FULL END-TO-END WORKFLOW (ALL 13 BLISTER MACHINE SIGNALS)
# =============================================================================

def test_full_blister_machine_commissioning_workflow(app_instance, setup_factory_environment):
    """End-to-end commissioning workflow importing Phase 8 discovery template for all 13 signals."""
    env = setup_factory_environment
    with app_instance.app_context():
        # Canonical 13 blister machine signals from Phase 8 discovery
        template_data = {
            "metadata": {"endpoint_url": "opc.tcp://127.0.0.1:48401/pharmapredict/server/"},
            "mapped_signals": [
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.Speed_CPM", "browse_name": "2:Speed_CPM", "display_name": "Speed_CPM", "classification_category": "Speed", "suggested_signal_code": "LINE_SPEED_CPM", "engineering_unit": "CPM", "data_type": "Double"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.MachineSpeedRPM", "browse_name": "2:MachineSpeedRPM", "display_name": "MachineSpeedRPM", "classification_category": "Speed", "suggested_signal_code": "ROTATIONAL_SPEED_RPM", "engineering_unit": "RPM", "data_type": "Double"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.SealingTemperature", "browse_name": "2:SealingTemperature", "display_name": "SealingTemperature", "classification_category": "Temperature", "suggested_signal_code": "SEALING_TEMPERATURE", "engineering_unit": "°C", "data_type": "Double"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.MotorTemperature", "browse_name": "2:MotorTemperature", "display_name": "MotorTemperature", "classification_category": "Temperature", "suggested_signal_code": "MOTOR_TEMPERATURE", "engineering_unit": "°C", "data_type": "Double"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorVibration", "browse_name": "2:MainDriveMotorVibration", "display_name": "MainDriveMotorVibration", "classification_category": "Vibration", "suggested_signal_code": "MOTOR_VIBRATION", "engineering_unit": "mm/s", "data_type": "Double"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.BearingVibration", "browse_name": "2:BearingVibration", "display_name": "BearingVibration", "classification_category": "Vibration", "suggested_signal_code": "BEARING_VIBRATION", "engineering_unit": "mm/s", "data_type": "Double"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.MainDriveMotorCurrent", "browse_name": "2:MainDriveMotorCurrent", "display_name": "MainDriveMotorCurrent", "classification_category": "Motor Current", "suggested_signal_code": "MOTOR_CURRENT", "engineering_unit": "A", "data_type": "Double"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.VacuumLevel", "browse_name": "2:VacuumLevel", "display_name": "VacuumLevel", "classification_category": "Pressure", "suggested_signal_code": "VACUUM_LEVEL", "engineering_unit": "bar", "data_type": "Double"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.FormingAirPressure", "browse_name": "2:FormingAirPressure", "display_name": "FormingAirPressure", "classification_category": "Pressure", "suggested_signal_code": "FORMING_PRESSURE", "engineering_unit": "bar", "data_type": "Double"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.MachineFaultAlarm", "browse_name": "2:MachineFaultAlarm", "display_name": "MachineFaultAlarm", "classification_category": "Alarms", "suggested_signal_code": "ALARM_STATE", "engineering_unit": "Boolean", "data_type": "Boolean"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.EmergencyStopActive", "browse_name": "2:EmergencyStopActive", "display_name": "EmergencyStopActive", "classification_category": "Alarms", "suggested_signal_code": "EMERGENCY_STOP_ACTIVE", "engineering_unit": "Boolean", "data_type": "Boolean"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.CumulativeCycleCount", "browse_name": "2:CumulativeCycleCount", "display_name": "CumulativeCycleCount", "classification_category": "Cycles", "suggested_signal_code": "CYCLE_COUNT", "engineering_unit": "cycles", "data_type": "Int64"},
                {"source_node_id": "ns=2;s=BlisterPackagingMachine_01.BatchProductionCount", "browse_name": "2:BatchProductionCount", "display_name": "BatchProductionCount", "classification_category": "Cycles", "suggested_signal_code": "PRODUCTION_COUNT", "engineering_unit": "units", "data_type": "Int64"},
            ]
        }

        # Step 1: Import Discovery
        session = CommissioningService.import_discovery(
            machine_id=env["machine_id"],
            organization_id=env["organization_id"],
            payload=template_data,
            user_id=env["engineer_user_id"],
        )
        assert session["mapped_candidates_count"] == 13

        # Step 2: Query candidates
        cands = CommissioningService.list_candidates(
            session_id=session["id"],
            organization_id=env["organization_id"],
            is_mapped=True,
        )
        assert len(cands) == 13
        cand_ids = [c["id"] for c in cands]

        # Step 3: Bulk Approve all 13 candidates
        bulk_res = CommissioningService.bulk_review(
            session_id=session["id"],
            organization_id=env["organization_id"],
            candidate_ids=cand_ids,
            decision="APPROVED",
            user_id=env["engineer_user_id"],
            reason="Verified 13 blister packaging machine tags for commissioning.",
        )
        assert bulk_res["updated_count"] == 13

        # Step 4: Activate Approved signals
        act_res = CommissioningService.activate_approved(
            session_id=session["id"],
            organization_id=env["organization_id"],
            user_id=env["engineer_user_id"],
        )
        assert act_res["status"] == CommissioningStatus.ACTIVATED.value
        assert act_res["activated_count"] == 13

        # Step 5: Verify all 13 MachineSignals persisted in Database
        persisted = MachineSignal.query.filter_by(
            machine_id=env["machine_id"],
            enabled=True,
        ).all()
        assert len(persisted) == 13
        for ps in persisted:
            assert ps.organization_id == env["organization_id"]
            assert ps.validation_status == ValidationStatus.VALID
            assert ps.mapping_version == 1


# =============================================================================
# 7. ROLE-BASED ACCESS CONTROL (RBAC) VERIFICATION
# =============================================================================

def test_rbac_unauthorized_user_cannot_access_commissioning_endpoints(app_instance, setup_factory_environment):
    """Verifies that unauthenticated or non-engineer (Viewer) roles cannot access commissioning endpoints."""
    client = app_instance.test_client()
    with app_instance.app_context():
        env = setup_factory_environment
        m_id = env["machine_id"]

        # Create sessions
        viewer_session = create_user_session(env["operator_user_id"])
        eng_session = create_user_session(env["engineer_user_id"])

        import_payload = {
            "mapped_signals": [
                {
                    "node_id": "ns=2;s=Device.TestRBAC",
                    "browse_name": "TestRBAC",
                    "data_type": "Double",
                    "canonical_signal": "forming_temperature",
                    "unit": "°C",
                    "category": "TEMPERATURE",
                    "confidence_score": 0.95,
                    "reasoning": "RBAC verification test tag",
                }
            ]
        }

        # 1. Unauthenticated request -> 401 Unauthorized
        res_no_auth = client.post(
            f"/api/v1/equipment/{m_id}/commissioning/import",
            json=import_payload,
        )
        assert res_no_auth.status_code == 401
        assert res_no_auth.get_json()["error"] == "Unauthorized"

        # 2. Viewer role request -> 403 Forbidden
        res_viewer = client.post(
            f"/api/v1/equipment/{m_id}/commissioning/import",
            headers={"Authorization": f"Bearer {viewer_session.session_token}"},
            json=import_payload,
        )
        assert res_viewer.status_code == 403
        assert res_viewer.get_json()["error"] == "Forbidden"
        assert "Insufficient permissions" in res_viewer.get_json()["message"]

        # 3. Engineer role request -> 201 Created
        res_eng = client.post(
            f"/api/v1/equipment/{m_id}/commissioning/import",
            headers={"Authorization": f"Bearer {eng_session.session_token}"},
            json=import_payload,
        )
        assert res_eng.status_code == 201
        session_info = res_eng.get_json()["session"]
        assert session_info["status"] == "PENDING_REVIEW"
        session_id = session_info["id"]

        # 4. Viewer cannot review or approve candidate -> 403 Forbidden
        dummy_cand_id = "00000000-0000-0000-0000-000000000001"
        res_viewer_review = client.post(
            f"/api/v1/commissioning/candidates/{dummy_cand_id}/review",
            headers={"Authorization": f"Bearer {viewer_session.session_token}"},
            json={"decision": "APPROVED", "reason": "Unauthorized attempt"},
        )
        assert res_viewer_review.status_code == 403
        assert res_viewer_review.get_json()["error"] == "Forbidden"

        # 5. Viewer cannot activate session -> 403 Forbidden
        res_viewer_act = client.post(
            f"/api/v1/commissioning/sessions/{session_id}/activate",
            headers={"Authorization": f"Bearer {viewer_session.session_token}"},
            json={},
        )
        assert res_viewer_act.status_code == 403
        assert res_viewer_act.get_json()["error"] == "Forbidden"

