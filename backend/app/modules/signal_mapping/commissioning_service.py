"""PharmaPredict AI — Phase 9 Commissioning Service.

Orchestrates the human-in-the-loop industrial equipment commissioning lifecycle:
- Import of Phase 8 OPC UA discovery templates (discovered_nodes.json, signal_mapping_template.json).
- Filtering, categorization, and confidence scoring of discovered candidates.
- Manual mapping review and correction with immutable diff history.
- Multi-criteria validation (duplicates, types, units, dimensions, required attributes).
- Formal human approval / rejection workflows with user identity and rationale tracking.
- Transactional activation into production MachineSignal configurations.
- Reversible rollback of activated commissioning batches.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from app.extensions import db
from app.models.user import User
from app.models.equipment import Machine
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
from app.modules.signal_mapping.repositories import (
    SignalDefinitionRepository,
    MachineSignalRepository,
)
from app.modules.signal_mapping.commissioning_validator import CommissioningValidator

logger = logging.getLogger(__name__)

# Canonical Signal Code Alias Map (Aligning Discovery Codes with Standard Definitions)
CODE_ALIAS_MAP: Dict[str, str] = {
    "SEALING_TEMPERATURE": "SEALING_TEMP",
    "MOTOR_TEMPERATURE": "MOTOR_TEMP",
    "MAIN_DRIVE_MOTOR_VIBRATION": "MOTOR_VIBRATION",
    "BEARING_VIBRATION": "BEARING_VIBRATION",
    "MOTOR_CURRENT": "MOTOR_CURRENT",
    "MAIN_DRIVE_MOTOR_CURRENT": "MOTOR_CURRENT",
    "ROTATIONAL_SPEED_RPM": "ROTATIONAL_SPEED",
    "ROTATIONAL_SPEED": "ROTATIONAL_SPEED",
    "LINE_SPEED_CPM": "LINE_SPEED",
    "LINE_SPEED": "LINE_SPEED",
    "VACUUM_LEVEL": "VACUUM_LEVEL",
    "FORMING_PRESSURE": "LINE_PRESSURE",
    "PRESSURE": "LINE_PRESSURE",
    "MACHINE_FAULT_ALARM": "FAULT_ALARM",
    "ALARM_STATE": "FAULT_ALARM",
    "EMERGENCY_STOP_ACTIVE": "EMERGENCY_STOP",
    "EMERGENCY_STOP": "EMERGENCY_STOP",
    "CUMULATIVE_CYCLE_COUNT": "CYCLE_COUNTER",
    "CYCLE_COUNT": "CYCLE_COUNTER",
    "BATCH_PRODUCTION_COUNT": "PRODUCTION_COUNT",
    "PRODUCTION_COUNT": "PRODUCTION_COUNT",
}


class CommissioningService:
    """Core domain service managing the human-approved signal commissioning lifecycle."""

    @classmethod
    def _find_or_seed_definition(
        cls,
        organization_id: str,
        suggested_code: Optional[str],
        category: Optional[str] = None,
        data_type: Optional[str] = "Double",
        unit: Optional[str] = None,
    ) -> Optional[SignalDefinition]:
        """Resolves target signal definition from standard library or creates tenant definition."""
        if not suggested_code:
            return None

        # 1. Check alias resolution
        clean_code = suggested_code.strip().upper()
        canonical_code = CODE_ALIAS_MAP.get(clean_code, clean_code)

        # 2. Check standard definitions
        defn = SignalDefinition.query.filter_by(signal_code=canonical_code, organization_id=None).first()
        if not defn:
            defn = SignalDefinition.query.filter_by(signal_code=clean_code, organization_id=None).first()

        # 3. Check organization custom definitions
        if not defn:
            defn = SignalDefinition.query.filter_by(signal_code=canonical_code, organization_id=organization_id).first()
        if not defn:
            defn = SignalDefinition.query.filter_by(signal_code=clean_code, organization_id=organization_id).first()

        # 4. If still not found, create a sensible standard definition for the code
        if not defn:
            group = SignalGroup.OTHER
            if category:
                for grp in SignalGroup.ALL_GROUPS:
                    if grp.lower() in category.lower():
                        group = grp
                        break

            defn = SignalDefinition(
                signal_code=clean_code,
                name=clean_code.replace("_", " ").title(),
                signal_group=group,
                expected_data_type=data_type or "Double",
                standard_unit=unit,
                description=f"Auto-registered signal definition for {clean_code}",
                is_custom=False,
                organization_id=None,
            )
            db.session.add(defn)
            try:
                db.session.flush()
            except Exception:
                db.session.rollback()
                defn = SignalDefinition.query.filter_by(signal_code=clean_code).first()

        return defn

    @classmethod
    def import_discovery(
        cls,
        machine_id: str,
        organization_id: str,
        payload: Dict[str, Any],
        user_id: Optional[str] = None,
        session_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Imports Phase 8 discovery JSON outputs and initiates a commissioning review session."""
        # 1. Validate Target Machine
        machine = db.session.get(Machine, machine_id)
        if not machine or machine.organization_id != organization_id:
            raise ValueError(f"Equipment asset '{machine_id}' not found or access denied.")

        # 2. Ensure standard definitions exist in the catalog
        SignalDefinitionRepository.seed_standard_definitions()

        # 3. Parse input payload (Supports signal_mapping_template.json or discovered_nodes.json)
        metadata = payload.get("metadata", {})
        source_endpoint = metadata.get("endpoint_url") or "opc.tcp://127.0.0.1:48401/pharmapredict/server/"
        now = datetime.now(timezone.utc)

        m_name = getattr(machine, "equipment_name", getattr(machine, "name", machine.asset_code))
        default_name = f"Commissioning — {m_name} ({now.strftime('%Y-%m-%d %H:%M')})"
        session = CommissioningSession(
            organization_id=organization_id,
            machine_id=machine_id,
            session_name=session_name or default_name,
            source_endpoint_url=source_endpoint,
            status=CommissioningStatus.PENDING_REVIEW.value,
            metadata_json=metadata,
            created_by=user_id,
            created_at=now,
            audit_log=[
                {
                    "timestamp": now.isoformat(),
                    "user_id": user_id,
                    "action": "SESSION_CREATED",
                    "details": f"Imported discovery output with {len(payload.get('mapped_signals', []))} mapped candidates.",
                }
            ],
        )
        db.session.add(session)
        db.session.flush()

        candidates: List[DiscoveredSignalCandidate] = []

        # Case A: signal_mapping_template.json format
        if "mapped_signals" in payload or "unmapped_signals" in payload:
            mapped_items = payload.get("mapped_signals", [])
            unmapped_items = payload.get("unmapped_signals", [])

            for item in mapped_items:
                s_node_id = item.get("source_node_id", "").strip()
                if not s_node_id:
                    continue

                code = item.get("suggested_signal_code")
                cat = item.get("classification_category", "Other")
                raw_dtype = item.get("data_type") or item.get("source_data_type")
                if not raw_dtype:
                    if "alarm" in cat.lower() or "fault" in cat.lower():
                        dtype = "Boolean"
                    elif "cycle" in cat.lower() or "count" in cat.lower():
                        dtype = "Int64"
                    else:
                        dtype = "Double"
                else:
                    dtype = raw_dtype
                unit = item.get("engineering_unit")

                target_def = cls._find_or_seed_definition(
                    organization_id=organization_id,
                    suggested_code=code,
                    category=cat,
                    data_type=dtype,
                    unit=unit,
                )

                candidate = DiscoveredSignalCandidate(
                    session_id=session.id,
                    organization_id=organization_id,
                    machine_id=machine_id,
                    source_node_id=s_node_id,
                    browse_name=item.get("browse_name"),
                    display_name=item.get("display_name"),
                    source_data_type=dtype,
                    access_level=item.get("access_level", "CurrentRead"),
                    source_unit=unit,
                    suggested_category=cat,
                    confidence_level=item.get("confidence_level", "HIGH"),
                    confidence_score=float(item.get("confidence_score", 0.85)),
                    suggested_signal_code=code,
                    target_signal_definition_id=target_def.id if target_def else None,
                    custom_name=item.get("custom_name"),
                    component_id=item.get("component_id"),
                    engineering_unit=unit,
                    scaling_factor=float(item.get("scaling_factor", 1.0)),
                    offset=float(item.get("offset", 0.0)),
                    sampling_interval_ms=int(item.get("sampling_interval_ms", 1000)),
                    warning_min=item.get("warning_min"),
                    warning_max=item.get("warning_max"),
                    critical_min=item.get("critical_min"),
                    critical_max=item.get("critical_max"),
                    is_mapped=True,
                    status=CommissioningStatus.PENDING_REVIEW.value,
                    review_history=[
                        {
                            "timestamp": now.isoformat(),
                            "user_id": user_id,
                            "action": "IMPORTED",
                            "decision": "PENDING_REVIEW",
                            "reason": f"Discovered by Phase 8 Tag Discovery ({item.get('confidence_level')} confidence).",
                        }
                    ],
                )
                db.session.add(candidate)
                candidates.append(candidate)

            for item in unmapped_items:
                s_node_id = item.get("source_node_id", item.get("node_id", "")).strip()
                if not s_node_id:
                    continue

                candidate = DiscoveredSignalCandidate(
                    session_id=session.id,
                    organization_id=organization_id,
                    machine_id=machine_id,
                    source_node_id=s_node_id,
                    browse_name=item.get("browse_name"),
                    display_name=item.get("display_name"),
                    source_data_type=item.get("data_type"),
                    access_level=item.get("access_level", "CurrentRead"),
                    source_unit=item.get("unit"),
                    suggested_category="Other",
                    confidence_level="UNMAPPED",
                    confidence_score=0.0,
                    suggested_signal_code=None,
                    target_signal_definition_id=None,
                    is_mapped=False,
                    status=CommissioningStatus.PENDING_REVIEW.value,
                    review_history=[
                        {
                            "timestamp": now.isoformat(),
                            "user_id": user_id,
                            "action": "IMPORTED",
                            "decision": "PENDING_REVIEW",
                            "reason": "Unmapped node requiring manual assignment or exclusion.",
                        }
                    ],
                )
                db.session.add(candidate)
                candidates.append(candidate)

        # Case B: discovered_nodes.json format
        elif "nodes" in payload:
            for item in payload.get("nodes", []):
                s_node_id = item.get("node_id", "").strip()
                if not s_node_id:
                    continue

                candidate = DiscoveredSignalCandidate(
                    session_id=session.id,
                    organization_id=organization_id,
                    machine_id=machine_id,
                    source_node_id=s_node_id,
                    browse_name=item.get("browse_name"),
                    display_name=item.get("display_name"),
                    source_data_type=item.get("data_type"),
                    access_level=item.get("access_level", "CurrentRead"),
                    source_unit=item.get("unit"),
                    suggested_category="Other",
                    confidence_level="UNMAPPED",
                    confidence_score=0.0,
                    is_mapped=False,
                    status=CommissioningStatus.PENDING_REVIEW.value,
                    review_history=[
                        {
                            "timestamp": now.isoformat(),
                            "user_id": user_id,
                            "action": "IMPORTED",
                            "decision": "PENDING_REVIEW",
                            "reason": "Imported from discovered_nodes.json raw inventory.",
                        }
                    ],
                )
                db.session.add(candidate)
                candidates.append(candidate)

        db.session.flush()

        # 4. Fetch existing machine signals to check for overwrite warnings
        existing_signals = MachineSignalRepository.get_signals_for_machine(machine_id, organization_id)

        # 5. Run initial validation on all candidates
        CommissioningValidator.validate_session(candidates, existing_signals)

        # 6. Update session metrics
        session.discovered_nodes_count = len(candidates)
        session.mapped_candidates_count = sum(1 for c in candidates if c.is_mapped)
        session.unmapped_candidates_count = sum(1 for c in candidates if not c.is_mapped)
        session.approved_count = 0
        session.rejected_count = 0
        session.activated_count = 0

        db.session.commit()
        logger.info(
            f"Commissioning session '{session.id}' created for machine '{machine_id}': "
            f"{session.mapped_candidates_count} mapped, {session.unmapped_candidates_count} unmapped."
        )
        return session.to_dict(include_candidates=True)

    @classmethod
    def get_session(cls, session_id: str, organization_id: str) -> Optional[CommissioningSession]:
        """Retrieves a commissioning session by ID within tenant organization."""
        session = db.session.get(CommissioningSession, session_id)
        if session and session.organization_id == organization_id:
            return session
        return None

    @classmethod
    def list_sessions_for_machine(cls, machine_id: str, organization_id: str) -> List[Dict[str, Any]]:
        """Lists all commissioning sessions for an equipment asset."""
        sessions = (
            CommissioningSession.query.filter_by(
                machine_id=machine_id,
                organization_id=organization_id,
            )
            .order_by(CommissioningSession.created_at.desc())
            .all()
        )
        return [s.to_dict() for s in sessions]

    @classmethod
    def list_candidates(
        cls,
        session_id: str,
        organization_id: str,
        category: Optional[str] = None,
        confidence: Optional[str] = None,
        status: Optional[str] = None,
        is_mapped: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieves candidate signals with filtering by category, confidence, status, and search."""
        session = cls.get_session(session_id, organization_id)
        if not session:
            raise ValueError(f"Commissioning session '{session_id}' not found or access denied.")

        query = DiscoveredSignalCandidate.query.filter_by(
            session_id=session_id,
            organization_id=organization_id,
        )

        if category:
            query = query.filter(DiscoveredSignalCandidate.suggested_category.ilike(f"%{category}%"))
        if confidence:
            query = query.filter_by(confidence_level=confidence.upper())
        if status:
            query = query.filter_by(status=status.upper())
        if is_mapped is not None:
            query = query.filter_by(is_mapped=is_mapped)
        if search:
            s = f"%{search.strip()}%"
            query = query.filter(
                db.or_(
                    DiscoveredSignalCandidate.source_node_id.ilike(s),
                    DiscoveredSignalCandidate.browse_name.ilike(s),
                    DiscoveredSignalCandidate.display_name.ilike(s),
                    DiscoveredSignalCandidate.suggested_signal_code.ilike(s),
                    DiscoveredSignalCandidate.custom_name.ilike(s),
                )
            )

        candidates = query.order_by(DiscoveredSignalCandidate.display_name.asc()).all()
        return [c.to_dict() for c in candidates]

    @classmethod
    def get_candidate(cls, candidate_id: str, organization_id: str) -> Optional[DiscoveredSignalCandidate]:
        """Retrieves an individual signal candidate by ID."""
        candidate = db.session.get(DiscoveredSignalCandidate, candidate_id)
        if candidate and candidate.organization_id == organization_id:
            return candidate
        return None

    @classmethod
    def update_candidate_mapping(
        cls,
        candidate_id: str,
        organization_id: str,
        data: Dict[str, Any],
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Allows authorized engineers to manually correct or assign signal mappings."""
        candidate = cls.get_candidate(candidate_id, organization_id)
        if not candidate:
            raise ValueError(f"Signal candidate '{candidate_id}' not found or access denied.")

        if candidate.status == CommissioningStatus.ACTIVATED.value:
            raise ValueError("Cannot edit an already ACTIVATED candidate. Roll back activation first.")

        # Capture snapshot of previous state for audit diff
        previous_mapping = {
            "target_signal_definition_id": candidate.target_signal_definition_id,
            "suggested_signal_code": candidate.suggested_signal_code,
            "custom_name": candidate.custom_name,
            "component_id": candidate.component_id,
            "engineering_unit": candidate.engineering_unit,
            "scaling_factor": candidate.scaling_factor,
            "offset": candidate.offset,
            "sampling_interval_ms": candidate.sampling_interval_ms,
            "warning_min": candidate.warning_min,
            "warning_max": candidate.warning_max,
            "critical_min": candidate.critical_min,
            "critical_max": candidate.critical_max,
            "is_mapped": candidate.is_mapped,
        }

        # Apply updates
        if "target_signal_definition_id" in data:
            candidate.target_signal_definition_id = data["target_signal_definition_id"]
            if candidate.target_signal_definition_id:
                defn = db.session.get(SignalDefinition, candidate.target_signal_definition_id)
                if defn:
                    candidate.suggested_signal_code = defn.signal_code
                    if not candidate.engineering_unit:
                        candidate.engineering_unit = defn.standard_unit
                    candidate.is_mapped = True
        elif "suggested_signal_code" in data and data["suggested_signal_code"]:
            code = data["suggested_signal_code"].strip().upper()
            defn = cls._find_or_seed_definition(
                organization_id=organization_id,
                suggested_code=code,
                category=candidate.suggested_category,
                data_type=candidate.source_data_type,
                unit=candidate.source_unit,
            )
            candidate.suggested_signal_code = code
            candidate.target_signal_definition_id = defn.id if defn else None
            candidate.is_mapped = True

        if "custom_name" in data:
            candidate.custom_name = data["custom_name"]
        if "component_id" in data:
            candidate.component_id = data["component_id"]
        if "engineering_unit" in data:
            candidate.engineering_unit = data["engineering_unit"]
        if "scaling_factor" in data:
            candidate.scaling_factor = float(data["scaling_factor"])
        if "offset" in data:
            candidate.offset = float(data["offset"])
        if "sampling_interval_ms" in data:
            candidate.sampling_interval_ms = int(data["sampling_interval_ms"])
        if "warning_min" in data:
            candidate.warning_min = float(data["warning_min"]) if data["warning_min"] is not None else None
        if "warning_max" in data:
            candidate.warning_max = float(data["warning_max"]) if data["warning_max"] is not None else None
        if "critical_min" in data:
            candidate.critical_min = float(data["critical_min"]) if data["critical_min"] is not None else None
        if "critical_max" in data:
            candidate.critical_max = float(data["critical_max"]) if data["critical_max"] is not None else None
        if "is_mapped" in data:
            candidate.is_mapped = bool(data["is_mapped"])

        # If candidate was rejected or approved, editing resets it to PENDING_REVIEW
        candidate.status = CommissioningStatus.PENDING_REVIEW.value

        # Re-validate candidate
        all_candidates = DiscoveredSignalCandidate.query.filter_by(session_id=candidate.session_id).all()
        existing_signals = MachineSignalRepository.get_signals_for_machine(candidate.machine_id, organization_id)
        val_res = CommissioningValidator.validate_candidate(candidate, all_candidates, existing_signals)

        candidate.validation_errors = val_res.errors
        candidate.validation_warnings = val_res.warnings
        candidate.is_valid = val_res.is_valid

        # Record immutable audit history entry
        now = datetime.now(timezone.utc)
        user = db.session.get(User, user_id) if user_id else None
        history_entry = {
            "timestamp": now.isoformat(),
            "user_id": user_id,
            "user_email": user.email if user else "system",
            "action": "MANUAL_CORRECTION",
            "previous_mapping": previous_mapping,
            "new_mapping": {
                "target_signal_definition_id": candidate.target_signal_definition_id,
                "suggested_signal_code": candidate.suggested_signal_code,
                "custom_name": candidate.custom_name,
                "component_id": candidate.component_id,
                "engineering_unit": candidate.engineering_unit,
                "scaling_factor": candidate.scaling_factor,
                "offset": candidate.offset,
                "sampling_interval_ms": candidate.sampling_interval_ms,
                "warning_min": candidate.warning_min,
                "warning_max": candidate.warning_max,
                "critical_min": candidate.critical_min,
                "critical_max": candidate.critical_max,
                "is_mapped": candidate.is_mapped,
            },
            "is_valid": candidate.is_valid,
        }
        review_hist = list(candidate.review_history or [])
        review_hist.append(history_entry)
        candidate.review_history = review_hist

        db.session.commit()
        return candidate.to_dict()

    @classmethod
    def review_candidate(
        cls,
        candidate_id: str,
        organization_id: str,
        decision: str,
        user_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Submits human approval or rejection for a candidate mapping."""
        decision_upper = decision.strip().upper()
        if decision_upper not in (CommissioningStatus.APPROVED.value, CommissioningStatus.REJECTED.value):
            raise ValueError(f"Invalid review decision '{decision}'. Must be 'APPROVED' or 'REJECTED'.")

        candidate = cls.get_candidate(candidate_id, organization_id)
        if not candidate:
            raise ValueError(f"Signal candidate '{candidate_id}' not found or access denied.")

        if candidate.status == CommissioningStatus.ACTIVATED.value:
            raise ValueError("Candidate is already ACTIVATED. Rollback session before changing review status.")

        all_candidates = DiscoveredSignalCandidate.query.filter_by(session_id=candidate.session_id).all()
        existing_signals = MachineSignalRepository.get_signals_for_machine(candidate.machine_id, organization_id)

        # Enforce validation on approval
        if decision_upper == CommissioningStatus.APPROVED.value:
            val_res = CommissioningValidator.validate_candidate(candidate, all_candidates, existing_signals)
            candidate.validation_errors = val_res.errors
            candidate.validation_warnings = val_res.warnings
            candidate.is_valid = val_res.is_valid

            if not candidate.is_valid:
                raise ValueError(
                    f"Cannot approve candidate '{candidate.display_name or candidate.source_node_id}': "
                    f"Validation failed with errors: {'; '.join(candidate.validation_errors)}"
                )

        now = datetime.now(timezone.utc)
        user = db.session.get(User, user_id) if user_id else None
        prev_status = candidate.status
        candidate.status = decision_upper

        # Record review history entry
        review_entry = {
            "timestamp": now.isoformat(),
            "user_id": user_id,
            "user_email": user.email if user else "system",
            "previous_status": prev_status,
            "new_status": decision_upper,
            "decision": decision_upper,
            "reason": reason or f"Candidate {decision_upper.lower()} by engineer.",
        }
        hist = list(candidate.review_history or [])
        hist.append(review_entry)
        candidate.review_history = hist

        # Update parent session counters
        session = candidate.session
        session.approved_count = sum(1 for c in all_candidates if c.status == CommissioningStatus.APPROVED.value)
        session.rejected_count = sum(1 for c in all_candidates if c.status == CommissioningStatus.REJECTED.value)

        # Append to session audit log
        session_audit = list(session.audit_log or [])
        session_audit.append({
            "timestamp": now.isoformat(),
            "user_id": user_id,
            "action": f"CANDIDATE_{decision_upper}",
            "candidate_id": candidate.id,
            "source_node_id": candidate.source_node_id,
            "reason": reason,
        })
        session.audit_log = session_audit

        db.session.commit()
        return candidate.to_dict()

    @classmethod
    def bulk_review(
        cls,
        session_id: str,
        organization_id: str,
        candidate_ids: List[str],
        decision: str,
        user_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Applies approval or rejection to multiple candidates within a session."""
        session = cls.get_session(session_id, organization_id)
        if not session:
            raise ValueError(f"Commissioning session '{session_id}' not found or access denied.")

        updated_count = 0
        errors = []

        for cid in candidate_ids:
            try:
                cls.review_candidate(
                    candidate_id=cid,
                    organization_id=organization_id,
                    decision=decision,
                    user_id=user_id,
                    reason=reason,
                )
                updated_count += 1
            except Exception as e:
                errors.append(f"Candidate {cid}: {str(e)}")

        return {
            "session_id": session_id,
            "decision": decision.upper(),
            "total_requested": len(candidate_ids),
            "updated_count": updated_count,
            "errors": errors,
        }

    @classmethod
    def activate_approved(
        cls,
        session_id: str,
        organization_id: str,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Registers all APPROVED candidates into production MachineSignal configurations.

        Strictly prevents activating REJECTED or PENDING_REVIEW candidates.
        Supports clean transaction rollback if any registration fails.
        """
        session = cls.get_session(session_id, organization_id)
        if not session:
            raise ValueError(f"Commissioning session '{session_id}' not found or access denied.")

        # Find all APPROVED candidates
        approved_candidates = (
            DiscoveredSignalCandidate.query.filter_by(
                session_id=session_id,
                organization_id=organization_id,
                status=CommissioningStatus.APPROVED.value,
            ).all()
        )

        if not approved_candidates:
            raise ValueError("No candidates with status 'APPROVED' found to activate in this session.")

        # Verify validity of every candidate
        all_candidates = DiscoveredSignalCandidate.query.filter_by(session_id=session_id).all()
        existing_signals = MachineSignalRepository.get_signals_for_machine(session.machine_id, organization_id)

        for cand in approved_candidates:
            val_res = CommissioningValidator.validate_candidate(cand, all_candidates, existing_signals)
            if not val_res.is_valid:
                raise ValueError(
                    f"Candidate '{cand.display_name or cand.source_node_id}' failed pre-activation validation: "
                    f"{'; '.join(val_res.errors)}"
                )

        now = datetime.now(timezone.utc)
        user = db.session.get(User, user_id) if user_id else None
        machine = session.machine
        activated_signals: List[Dict[str, Any]] = []

        try:
            # Transaction block
            with db.session.begin_nested():
                for cand in approved_candidates:
                    # Resolve or fallback to target definition
                    def_id = cand.target_signal_definition_id
                    if not def_id and cand.suggested_signal_code:
                        defn = cls._find_or_seed_definition(
                            organization_id=organization_id,
                            suggested_code=cand.suggested_signal_code,
                            category=cand.suggested_category,
                            data_type=cand.source_data_type,
                            unit=cand.engineering_unit,
                        )
                        def_id = defn.id if defn else None

                    if not def_id:
                        raise ValueError(f"Cannot activate candidate '{cand.source_node_id}': Missing target signal definition.")

                    # Check if signal already exists for this machine & node
                    existing_ms = (
                        MachineSignal.query.filter_by(
                            machine_id=session.machine_id,
                            source_node_id=cand.source_node_id,
                        )
                        .order_by(MachineSignal.mapping_version.desc())
                        .first()
                    )

                    if existing_ms:
                        # Bump mapping version and update parameters
                        existing_ms.mapping_version += 1
                        existing_ms.signal_definition_id = def_id
                        existing_ms.custom_name = cand.custom_name or cand.display_name
                        existing_ms.component_id = cand.component_id
                        existing_ms.source_browse_name = cand.browse_name
                        existing_ms.source_data_type = cand.source_data_type
                        existing_ms.source_unit = cand.source_unit
                        existing_ms.normalized_unit = cand.engineering_unit or cand.source_unit
                        existing_ms.scaling_factor = cand.scaling_factor
                        existing_ms.offset = cand.offset
                        existing_ms.sampling_interval_ms = cand.sampling_interval_ms
                        existing_ms.validation_status = ValidationStatus.VALID
                        existing_ms.enabled = True
                        ms_record = existing_ms
                    else:
                        # Create new MachineSignal
                        ms_record = MachineSignal(
                            organization_id=organization_id,
                            machine_id=session.machine_id,
                            connector_id="gateway_opcua_primary",
                            component_id=cand.component_id,
                            signal_definition_id=def_id,
                            custom_name=cand.custom_name or cand.display_name,
                            source_node_id=cand.source_node_id,
                            source_browse_name=cand.browse_name,
                            source_data_type=cand.source_data_type,
                            source_unit=cand.source_unit,
                            normalized_unit=cand.engineering_unit or cand.source_unit,
                            scaling_factor=cand.scaling_factor,
                            offset=cand.offset,
                            sampling_interval_ms=cand.sampling_interval_ms,
                            mapping_version=1,
                            validation_status=ValidationStatus.VALID,
                            enabled=True,
                            created_by=user_id,
                            created_at=now,
                        )
                        db.session.add(ms_record)
                        db.session.flush()

                    # Update candidate status
                    cand.status = CommissioningStatus.ACTIVATED.value
                    cand.registered_machine_signal_id = ms_record.id

                    hist = list(cand.review_history or [])
                    hist.append({
                        "timestamp": now.isoformat(),
                        "user_id": user_id,
                        "user_email": user.email if user else "system",
                        "action": "ACTIVATED",
                        "registered_machine_signal_id": ms_record.id,
                        "mapping_version": ms_record.mapping_version,
                    })
                    cand.review_history = hist

                    activated_signals.append(ms_record.to_dict())

                # Update session
                session.status = CommissioningStatus.ACTIVATED.value
                session.activated_count = len(approved_candidates)
                session.activated_at = now
                session.activated_by = user_id

                session_audit = list(session.audit_log or [])
                session_audit.append({
                    "timestamp": now.isoformat(),
                    "user_id": user_id,
                    "action": "SESSION_ACTIVATED",
                    "details": f"Successfully activated {len(approved_candidates)} approved machine signals.",
                })
                session.audit_log = session_audit

            db.session.commit()
            logger.info(f"Commissioning session '{session_id}' activated: {len(activated_signals)} signals registered.")
            return {
                "session_id": session_id,
                "status": CommissioningStatus.ACTIVATED.value,
                "activated_count": len(activated_signals),
                "activated_signals": activated_signals,
            }
        except Exception as e:
            db.session.rollback()
            logger.error(f"Activation transaction failed for session '{session_id}': {e}")
            raise

    @classmethod
    def rollback_activation(
        cls,
        session_id: str,
        organization_id: str,
        user_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rolls back an activated commissioning session, deactivating registered signals."""
        session = cls.get_session(session_id, organization_id)
        if not session:
            raise ValueError(f"Commissioning session '{session_id}' not found or access denied.")

        if session.status != CommissioningStatus.ACTIVATED.value:
            raise ValueError(f"Cannot rollback session with status '{session.status}'. Only ACTIVATED sessions can be rolled back.")

        activated_candidates = DiscoveredSignalCandidate.query.filter_by(
            session_id=session_id,
            organization_id=organization_id,
            status=CommissioningStatus.ACTIVATED.value,
        ).all()

        now = datetime.now(timezone.utc)
        user = db.session.get(User, user_id) if user_id else None
        reverted_count = 0

        for cand in activated_candidates:
            if cand.registered_machine_signal_id:
                ms = db.session.get(MachineSignal, cand.registered_machine_signal_id)
                if ms:
                    ms.enabled = False  # Deactivate registered signal
                    ms.validation_status = ValidationStatus.PENDING

            cand.status = CommissioningStatus.APPROVED.value
            cand.registered_machine_signal_id = None

            hist = list(cand.review_history or [])
            hist.append({
                "timestamp": now.isoformat(),
                "user_id": user_id,
                "user_email": user.email if user else "system",
                "action": "ROLLBACK_ACTIVATION",
                "reason": reason or "Activation rolled back by engineer.",
            })
            cand.review_history = hist
            reverted_count += 1

        session.status = CommissioningStatus.APPROVED.value
        session.activated_count = 0
        session.activated_at = None
        session.activated_by = None

        session_audit = list(session.audit_log or [])
        session_audit.append({
            "timestamp": now.isoformat(),
            "user_id": user_id,
            "action": "SESSION_ROLLBACK",
            "details": f"Rolled back {reverted_count} activated signals. Reason: {reason or 'Engineer requested'}",
        })
        session.audit_log = session_audit

        db.session.commit()
        logger.info(f"Commissioning session '{session_id}' rolled back: {reverted_count} signals deactivated.")
        return session.to_dict()
