"""PharmaPredict AI — Phase 9 Commissioning API Endpoints.

REST API routes providing human-in-the-loop commissioning controls:
- Discovery template ingestion and session initialization.
- Candidate signal querying, searching, and category/confidence filtering.
- Manual mapping review, unit configuration, and threshold tuning.
- Multi-criteria validation execution.
- Human approval / rejection decisions with audit trail logging.
- Production MachineSignal registration and transactional rollback.
"""
import logging
from flask import Blueprint, request, jsonify, g
from app.models.user import Role
from app.security import login_required, roles_required
from app.modules.signal_mapping.commissioning_service import CommissioningService

logger = logging.getLogger(__name__)

commissioning_bp = Blueprint("commissioning", __name__)

COMMISSIONING_MANAGE_ROLES = [
    Role.ORG_ADMIN,
    Role.MAINTENANCE_MANAGER,
    Role.MAINTENANCE_ENGINEER,
]


# ==============================================================================
# 1. DISCOVERY IMPORT & SESSION MANAGEMENT
# ==============================================================================

@commissioning_bp.route("/equipment/<machine_id>/commissioning/import", methods=["POST"])
@login_required
@roles_required(*COMMISSIONING_MANAGE_ROLES)
def import_discovery_output(machine_id: str):
    """Imports Phase 8 discovery JSON outputs and creates a commissioning review session."""
    payload = request.get_json(silent=True) or {}
    if not payload:
        return jsonify({
            "error": "Validation Error",
            "message": "Discovery payload body is required (must contain mapped_signals or nodes).",
        }), 400

    session_name = request.args.get("session_name") or payload.get("session_name")
    user_id = g.current_user.id if hasattr(g, "current_user") and g.current_user else None

    try:
        session_data = CommissioningService.import_discovery(
            machine_id=machine_id,
            organization_id=g.current_org_id,
            payload=payload,
            user_id=user_id,
            session_name=session_name,
        )
        return jsonify({
            "message": "Discovery output successfully imported into commissioning session.",
            "session": session_data,
        }), 201
    except ValueError as e:
        return jsonify({"error": "Validation Error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f"Error importing discovery output: {e}")
        return jsonify({"error": "Internal Error", "message": str(e)}), 500


@commissioning_bp.route("/equipment/<machine_id>/commissioning/sessions", methods=["GET"])
@login_required
def list_sessions_for_equipment(machine_id: str):
    """Lists all commissioning sessions for an equipment asset."""
    sessions = CommissioningService.list_sessions_for_machine(machine_id, g.current_org_id)
    return jsonify({
        "machine_id": machine_id,
        "count": len(sessions),
        "sessions": sessions,
    }), 200


@commissioning_bp.route("/commissioning/sessions/<session_id>", methods=["GET"])
@login_required
def get_commissioning_session(session_id: str):
    """Retrieves detailed status and audit summary of a commissioning session."""
    session = CommissioningService.get_session(session_id, g.current_org_id)
    if not session:
        return jsonify({"error": "Not Found", "message": "Commissioning session not found or access denied."}), 404

    include_cand = request.args.get("include_candidates", "false").lower() == "true"
    return jsonify({"session": session.to_dict(include_candidates=include_cand)}), 200


# ==============================================================================
# 2. CANDIDATE QUERYING & FILTERING
# ==============================================================================

@commissioning_bp.route("/commissioning/sessions/<session_id>/candidates", methods=["GET"])
@login_required
def list_session_candidates(session_id: str):
    """Lists discovered signal candidates with rich filtering (category, confidence, status, search)."""
    category = request.args.get("category")
    confidence = request.args.get("confidence")
    status = request.args.get("status")
    search = request.args.get("search")

    is_mapped_raw = request.args.get("is_mapped")
    is_mapped = None
    if is_mapped_raw is not None:
        is_mapped = is_mapped_raw.lower() in ("true", "1")

    try:
        candidates = CommissioningService.list_candidates(
            session_id=session_id,
            organization_id=g.current_org_id,
            category=category,
            confidence=confidence,
            status=status,
            is_mapped=is_mapped,
            search=search,
        )
        return jsonify({
            "session_id": session_id,
            "count": len(candidates),
            "candidates": candidates,
        }), 200
    except ValueError as e:
        return jsonify({"error": "Validation Error", "message": str(e)}), 404
    except Exception as e:
        logger.error(f"Error querying candidates: {e}")
        return jsonify({"error": "Internal Error", "message": str(e)}), 500


@commissioning_bp.route("/commissioning/candidates/<candidate_id>", methods=["GET"])
@login_required
def get_candidate_detail(candidate_id: str):
    """Retrieves an individual candidate with its full audit and review history."""
    candidate = CommissioningService.get_candidate(candidate_id, g.current_org_id)
    if not candidate:
        return jsonify({"error": "Not Found", "message": "Signal candidate not found or access denied."}), 404

    return jsonify({"candidate": candidate.to_dict()}), 200


# ==============================================================================
# 3. MANUAL MAPPING CORRECTION & HUMAN REVIEW
# ==============================================================================

@commissioning_bp.route("/commissioning/candidates/<candidate_id>", methods=["PATCH"])
@login_required
@roles_required(*COMMISSIONING_MANAGE_ROLES)
def update_candidate_mapping(candidate_id: str):
    """Allows authorized engineers to manually correct or assign signal mappings."""
    data = request.get_json(silent=True) or {}
    user_id = g.current_user.id if hasattr(g, "current_user") and g.current_user else None

    try:
        updated = CommissioningService.update_candidate_mapping(
            candidate_id=candidate_id,
            organization_id=g.current_org_id,
            data=data,
            user_id=user_id,
        )
        return jsonify({
            "message": "Candidate mapping updated and re-validated.",
            "candidate": updated,
        }), 200
    except ValueError as e:
        return jsonify({"error": "Validation Error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f"Error updating candidate mapping: {e}")
        return jsonify({"error": "Internal Error", "message": str(e)}), 500


@commissioning_bp.route("/commissioning/candidates/<candidate_id>/review", methods=["POST"])
@login_required
@roles_required(*COMMISSIONING_MANAGE_ROLES)
def review_candidate(candidate_id: str):
    """Submits human approval or rejection for a candidate mapping."""
    payload = request.get_json(silent=True) or {}
    decision = payload.get("decision")
    if not decision:
        return jsonify({"error": "Validation Error", "message": "Field 'decision' (APPROVED or REJECTED) is required."}), 400

    reason = payload.get("reason")
    user_id = g.current_user.id if hasattr(g, "current_user") and g.current_user else None

    try:
        updated = CommissioningService.review_candidate(
            candidate_id=candidate_id,
            organization_id=g.current_org_id,
            decision=decision,
            user_id=user_id,
            reason=reason,
        )
        return jsonify({
            "message": f"Candidate mapping {decision.upper()}.",
            "candidate": updated,
        }), 200
    except ValueError as e:
        return jsonify({"error": "Validation Error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f"Error reviewing candidate: {e}")
        return jsonify({"error": "Internal Error", "message": str(e)}), 500


@commissioning_bp.route("/commissioning/sessions/<session_id>/bulk-review", methods=["POST"])
@login_required
@roles_required(*COMMISSIONING_MANAGE_ROLES)
def bulk_review_candidates(session_id: str):
    """Submits batch human approvals or rejections for multiple candidates."""
    payload = request.get_json(silent=True) or {}
    candidate_ids = payload.get("candidate_ids", [])
    decision = payload.get("decision")

    if not candidate_ids or not isinstance(candidate_ids, list):
        return jsonify({"error": "Validation Error", "message": "List of 'candidate_ids' is required."}), 400
    if not decision:
        return jsonify({"error": "Validation Error", "message": "Field 'decision' (APPROVED or REJECTED) is required."}), 400

    reason = payload.get("reason")
    user_id = g.current_user.id if hasattr(g, "current_user") and g.current_user else None

    try:
        res = CommissioningService.bulk_review(
            session_id=session_id,
            organization_id=g.current_org_id,
            candidate_ids=candidate_ids,
            decision=decision,
            user_id=user_id,
            reason=reason,
        )
        return jsonify({
            "message": f"Bulk review completed. Updated {res['updated_count']} candidates to {decision.upper()}.",
            "result": res,
        }), 200
    except ValueError as e:
        return jsonify({"error": "Validation Error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f"Error during bulk review: {e}")
        return jsonify({"error": "Internal Error", "message": str(e)}), 500


# ==============================================================================
# 4. ACTIVATION & ROLLBACK
# ==============================================================================

@commissioning_bp.route("/commissioning/sessions/<session_id>/activate", methods=["POST"])
@login_required
@roles_required(*COMMISSIONING_MANAGE_ROLES)
def activate_session(session_id: str):
    """Activates all APPROVED candidate mappings into production MachineSignal configurations."""
    user_id = g.current_user.id if hasattr(g, "current_user") and g.current_user else None

    try:
        res = CommissioningService.activate_approved(
            session_id=session_id,
            organization_id=g.current_org_id,
            user_id=user_id,
        )
        return jsonify({
            "message": f"Successfully activated {res['activated_count']} approved signal(s).",
            "activation": res,
        }), 200
    except ValueError as e:
        return jsonify({"error": "Activation Error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f"Error activating session: {e}")
        return jsonify({"error": "Internal Error", "message": str(e)}), 500


@commissioning_bp.route("/commissioning/sessions/<session_id>/rollback", methods=["POST"])
@login_required
@roles_required(*COMMISSIONING_MANAGE_ROLES)
def rollback_session(session_id: str):
    """Rolls back an activated session, deactivating created signals and restoring candidate states."""
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason")
    user_id = g.current_user.id if hasattr(g, "current_user") and g.current_user else None

    try:
        session_data = CommissioningService.rollback_activation(
            session_id=session_id,
            organization_id=g.current_org_id,
            user_id=user_id,
            reason=reason,
        )
        return jsonify({
            "message": "Session activation successfully rolled back. Registered signals have been deactivated.",
            "session": session_data,
        }), 200
    except ValueError as e:
        return jsonify({"error": "Rollback Error", "message": str(e)}), 400
    except Exception as e:
        logger.error(f"Error rolling back session: {e}")
        return jsonify({"error": "Internal Error", "message": str(e)}), 500
