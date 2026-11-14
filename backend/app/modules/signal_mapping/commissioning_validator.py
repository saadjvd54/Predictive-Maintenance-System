"""PharmaPredict AI — Phase 9 Commissioning Mapping Validator.

Enforces multi-criteria validation rules for candidate OPC UA signal mappings:
1. Duplicate NodeIds within session and active machine configurations.
2. Duplicate canonical signal code assignments without distinct component disambiguation.
3. Incompatible data types between OPC UA source and target signal definition.
4. Engineering unit mismatches and physical dimension preservation.
5. Missing required machine and organizational identifiers.
6. Invalid or unsupported industrial signal categories.
7. Anti-false-positive and low-confidence mapping guards.
"""
import logging
from typing import Dict, Any, List, Optional, Tuple
from app.models.signal_mapping import (
    MachineSignal,
    SignalDefinition,
    SignalGroup,
)
from app.models.commissioning import (
    DiscoveredSignalCandidate,
    CommissioningStatus,
)
from app.modules.signal_mapping.validators import (
    SignalValidator,
    NUMERIC_OPCUA_TYPES,
    BOOLEAN_OPCUA_TYPES,
)
from app.modules.signal_mapping.unit_converter import (
    UnitNormalizer,
    IncompatibleUnitError,
    UnsupportedUnitError,
)

logger = logging.getLogger(__name__)

SUPPORTED_CATEGORIES = {
    "Temperature",
    "Vibration",
    "Motor Current",
    "Speed",
    "Pressure",
    "Vacuum",
    "Flow",
    "Alarms",
    "Cycles",
    "Other",
}


class CandidateValidationResult:
    def __init__(self, candidate_id: str, source_node_id: str):
        self.candidate_id = candidate_id
        self.source_node_id = source_node_id
        self.is_valid = True
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def add_error(self, message: str) -> None:
        self.is_valid = False
        self.errors.append(message)

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source_node_id": self.source_node_id,
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class CommissioningValidator:
    """Validator for candidate OPC UA signal mappings before human approval and activation."""

    @classmethod
    def validate_candidate(
        cls,
        candidate: DiscoveredSignalCandidate,
        all_session_candidates: Optional[List[DiscoveredSignalCandidate]] = None,
        existing_machine_signals: Optional[List[MachineSignal]] = None,
    ) -> CandidateValidationResult:
        """Runs the complete 7-rule validation suite on a single candidate."""
        res = CandidateValidationResult(candidate.id, candidate.source_node_id)

        # ---------------------------------------------------------------------
        # Rule 5: Missing Required Identifiers
        # ---------------------------------------------------------------------
        if not candidate.source_node_id or not candidate.source_node_id.strip():
            res.add_error("Missing required 'source_node_id'.")
        if not candidate.machine_id:
            res.add_error("Missing required 'machine_id'.")
        if not candidate.organization_id:
            res.add_error("Missing required 'organization_id'.")

        # ---------------------------------------------------------------------
        # Rule 1: Duplicate NodeIds
        # ---------------------------------------------------------------------
        if all_session_candidates:
            dup_session_nodes = [
                c for c in all_session_candidates
                if c.id != candidate.id and c.source_node_id == candidate.source_node_id
            ]
            if dup_session_nodes:
                res.add_error(
                    f"Duplicate source NodeId '{candidate.source_node_id}' found in the same session."
                )

        if existing_machine_signals:
            dup_active = [
                ms for ms in existing_machine_signals
                if ms.source_node_id == candidate.source_node_id and ms.enabled
            ]
            if dup_active:
                res.add_warning(
                    f"Source NodeId '{candidate.source_node_id}' is already mapped in an active configuration. "
                    "Activating this mapping will supersede it with a new version."
                )

        # ---------------------------------------------------------------------
        # Rule 6: Unsupported or Invalid Categories
        # ---------------------------------------------------------------------
        category = candidate.suggested_category or "Other"
        if category not in SUPPORTED_CATEGORIES:
            res.add_error(
                f"Unsupported signal category '{category}'. Must be one of: {sorted(list(SUPPORTED_CATEGORIES))}."
            )

        # ---------------------------------------------------------------------
        # Target Signal Definition Checks
        # ---------------------------------------------------------------------
        target_def: Optional[SignalDefinition] = candidate.signal_definition
        target_code = candidate.suggested_signal_code or (target_def.signal_code if target_def else None)

        if candidate.is_mapped:
            if not target_def and not target_code:
                res.add_error("Mapped candidate requires a target signal definition or suggested signal code.")

            # -----------------------------------------------------------------
            # Rule 2: Duplicate Canonical Signal Assignments
            # -----------------------------------------------------------------
            if target_code and all_session_candidates:
                dup_canonical = [
                    c for c in all_session_candidates
                    if c.id != candidate.id
                    and c.is_mapped
                    and (c.suggested_signal_code == target_code or (c.signal_definition and c.signal_definition.signal_code == target_code))
                    and c.component_id == candidate.component_id
                    and (c.custom_name or "") == (candidate.custom_name or "")
                ]
                if dup_canonical:
                    res.add_error(
                        f"Duplicate canonical signal code '{target_code}' assigned to multiple nodes without "
                        "distinct component or custom name disambiguation."
                    )

            # -----------------------------------------------------------------
            # Rule 3: Data Type Compatibility
            # -----------------------------------------------------------------
            if target_def and candidate.source_data_type:
                type_check = SignalValidator.check_data_type_compatibility(
                    expected_type=target_def.expected_data_type,
                    source_type=candidate.source_data_type,
                )
                if not type_check.passed:
                    res.add_error(type_check.message)
                elif type_check.severity == "WARNING":
                    res.add_warning(type_check.message)

            # -----------------------------------------------------------------
            # Rule 4: Engineering Unit Compatibility
            # -----------------------------------------------------------------
            unit = candidate.engineering_unit or candidate.source_unit
            if target_def and unit and target_def.standard_unit:
                std_unit = target_def.standard_unit.strip()
                cur_unit = unit.strip()

                # Check known incompatible dimensions
                temp_units = {"°c", "c", "°f", "f", "k"}
                vib_units = {"mm/s", "g", "in/s", "m/s2"}
                pres_units = {"bar", "mbar", "psi", "kpa", "mpa"}
                curr_units = {"a", "ma", "amp", "amperes"}

                u_lower = cur_unit.lower()
                std_lower = std_unit.lower()

                if std_lower in temp_units and u_lower not in temp_units:
                    res.add_error(
                        f"Engineering unit mismatch: definition requires temperature unit ({std_unit}), "
                        f"but candidate has '{cur_unit}'."
                    )
                elif std_lower in vib_units and u_lower not in vib_units:
                    res.add_error(
                        f"Engineering unit mismatch: definition requires vibration unit ({std_unit}), "
                        f"but candidate has '{cur_unit}'."
                    )
                elif std_lower in pres_units and u_lower not in pres_units:
                    res.add_error(
                        f"Engineering unit mismatch: definition requires pressure unit ({std_unit}), "
                        f"but candidate has '{cur_unit}'."
                    )
                elif std_lower in curr_units and u_lower not in curr_units:
                    res.add_error(
                        f"Engineering unit mismatch: definition requires electrical current unit ({std_unit}), "
                        f"but candidate has '{cur_unit}'."
                    )

            # -----------------------------------------------------------------
            # Rule 7: Confidence Level & Unapproved Checks
            # -----------------------------------------------------------------
            if candidate.confidence_level in ("LOW", "UNMAPPED"):
                # If engineer has not manually provided target definition, warn
                if not candidate.target_signal_definition_id:
                    res.add_warning(
                        f"Candidate has {candidate.confidence_level} confidence ({candidate.confidence_score:.2f}). "
                        "Requires explicit engineer review and target definition selection before activation."
                    )

            # Scaling factor sanity check
            scaling = candidate.scaling_factor if candidate.scaling_factor is not None else 1.0
            if scaling == 0.0:
                res.add_error("Scaling factor cannot be zero.")
            elif scaling < 0:
                res.add_warning("Negative scaling factor will invert measurement readings.")

            # Sampling interval check
            interval = candidate.sampling_interval_ms if candidate.sampling_interval_ms is not None else 1000
            if interval < 50:
                res.add_error("Sampling interval cannot be less than 50 ms (would overload PLC).")
            elif interval > 300000:
                res.add_warning("Sampling interval exceeds 5 minutes (300,000 ms).")

        return res

    @classmethod
    def validate_session(
        cls,
        candidates: List[DiscoveredSignalCandidate],
        existing_machine_signals: Optional[List[MachineSignal]] = None,
    ) -> Tuple[bool, List[CandidateValidationResult]]:
        """Validates all candidates in a session and returns overall validity and result list."""
        all_valid = True
        results = []

        for candidate in candidates:
            res = cls.validate_candidate(
                candidate=candidate,
                all_session_candidates=candidates,
                existing_machine_signals=existing_machine_signals,
            )
            # Sync candidate database record
            candidate.validation_errors = res.errors
            candidate.validation_warnings = res.warnings
            candidate.is_valid = res.is_valid

            if not res.is_valid:
                all_valid = False
            results.append(res)

        return all_valid, results
