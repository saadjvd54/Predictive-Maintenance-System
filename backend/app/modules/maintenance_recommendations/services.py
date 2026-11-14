"""Service layer for human-in-the-loop maintenance recommendation review and approvals."""
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from app.extensions import db
from app.models.diagnostic import MaintenanceRecommendation, RecommendationApproval

logger = logging.getLogger(__name__)


class MaintenanceRecommendationService:
    """Manages recommendation lifecycle, engineer approvals, rejections, and work-order handoff."""

    @classmethod
    def list_recommendations(
        cls,
        organization_id: str,
        machine_id: Optional[str] = None,
        priority: Optional[str] = None,
        approval_status: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Queries maintenance recommendations with organization isolation."""
        query = MaintenanceRecommendation.query.filter_by(organization_id=organization_id)

        if machine_id:
            query = query.filter_by(machine_id=machine_id)
        if priority:
            query = query.filter_by(priority=priority)
        if approval_status:
            query = query.filter_by(approval_status=approval_status)
        if session_id:
            query = query.filter_by(session_id=session_id)

        recs = query.order_by(MaintenanceRecommendation.created_at.desc()).limit(limit).all()
        return [r.to_dict() for r in recs]

    @classmethod
    def get_recommendation(cls, recommendation_id: str, organization_id: str) -> Dict[str, Any]:
        """Fetches a specific recommendation and its audit trail."""
        rec = MaintenanceRecommendation.query.filter_by(
            id=recommendation_id, organization_id=organization_id
        ).first()
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found.")

        approvals = RecommendationApproval.query.filter_by(
            recommendation_id=rec.id
        ).order_by(RecommendationApproval.created_at.desc()).all()

        data = rec.to_dict()
        data["approvals"] = [a.to_dict() for a in approvals]
        return data

    @classmethod
    def approve_recommendation(
        cls,
        recommendation_id: str,
        organization_id: str,
        user_id: str,
        notes: Optional[str] = None,
        assigned_technician_id: Optional[str] = None,
        scheduled_for: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approves a recommendation and stages an authorized maintenance work order."""
        rec = MaintenanceRecommendation.query.filter_by(
            id=recommendation_id, organization_id=organization_id
        ).first()
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found.")

        if rec.compliance_state == "BLOCKED":
            raise ValueError("Cannot approve a recommendation that is marked BLOCKED by safety compliance.")

        rec.approval_status = "APPROVED"
        rec.reviewed_by = user_id
        rec.reviewed_at = datetime.now(timezone.utc)
        rec.engineer_notes = notes

        # Generate work order reference stub
        work_order_ref = f"WO-{rec.machine_id[:6]}-{rec.id[:6]}".upper()
        rec.work_order_reference = work_order_ref

        # Record approval audit trail
        approval_log = RecommendationApproval(
            recommendation_id=rec.id,
            user_id=user_id,
            decision="APPROVED",
            comments=notes,
            work_order_reference=work_order_ref,
        )
        db.session.add(approval_log)
        db.session.commit()

        res = cls.get_recommendation(rec.id, organization_id)
        res["work_order_reference"] = work_order_ref
        return res

    @classmethod
    def reject_recommendation(
        cls,
        recommendation_id: str,
        organization_id: str,
        user_id: str,
        rejection_reason: str,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rejects a recommendation with a required justification for GMP traceability."""
        rec = MaintenanceRecommendation.query.filter_by(
            id=recommendation_id, organization_id=organization_id
        ).first()
        if not rec:
            raise ValueError(f"Recommendation {recommendation_id} not found.")

        if not rejection_reason or not rejection_reason.strip():
            raise ValueError("Rejection reason is mandatory for GMP change trail compliance.")

        rec.approval_status = "REJECTED"
        rec.reviewed_by = user_id
        rec.reviewed_at = datetime.now(timezone.utc)
        rec.engineer_notes = f"REJECTED: {rejection_reason.strip()} - {notes or ''}"

        approval_log = RecommendationApproval(
            recommendation_id=rec.id,
            user_id=user_id,
            decision="REJECTED",
            comments=rejection_reason.strip(),
        )
        db.session.add(approval_log)
        db.session.commit()

        res = cls.get_recommendation(rec.id, organization_id)
        res["rejection_reason"] = rejection_reason
        return res

