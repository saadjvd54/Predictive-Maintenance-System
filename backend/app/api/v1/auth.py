import re
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, make_response, current_app, g
from app.extensions import db
from app.models.tenant import Organization, Site
from app.models.user import User, Role, UserRoleAssignment, UserSession
from app.security import (
    create_user_session,
    revoke_user_session,
    login_required,
    check_rate_limit,
    record_failed_attempt,
    clear_rate_limit,
    log_audit_event,
    get_token_from_request,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


def is_valid_email(email: str) -> bool:
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    return bool(re.match(pattern, email))


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Authenticate user with email and password.
    Enforces login rate limiting, generic authentication errors, and returns HttpOnly session cookie.
    """
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({
            "error": "Bad Request",
            "message": "Both email and password are required."
        }), 400

    # Rate limiting key based on client IP and email
    ip_addr = request.remote_addr or "unknown"
    rate_key = f"{ip_addr}:{email}"
    is_allowed, remaining_or_retry = check_rate_limit(rate_key, max_attempts=5, window_seconds=900)

    if not is_allowed:
        log_audit_event(
            action="login_rate_limited",
            details={"email": email, "retry_after": remaining_or_retry}
        )
        return jsonify({
            "error": "Too Many Requests",
            "message": f"Too many failed login attempts. Please try again in {remaining_or_retry} seconds.",
            "retry_after": remaining_or_retry
        }), 429

    # Look up user
    user = User.query.filter_by(email=email).first()

    # Generic invalid credentials check
    if not user or not user.check_password(password):
        record_failed_attempt(rate_key)
        log_audit_event(
            action="login_failed",
            details={"email": email, "reason": "invalid_credentials"}
        )
        return jsonify({
            "error": "Unauthorized",
            "message": "Invalid email or password."
        }), 401

    if not user.is_active:
        log_audit_event(
            action="login_blocked_inactive",
            user_id=user.id,
            organization_id=user.organization_id
        )
        return jsonify({
            "error": "Forbidden",
            "message": "Your account has been deactivated. Please contact your organization administrator."
        }), 403

    if user.organization and user.organization.status != "active":
        return jsonify({
            "error": "Forbidden",
            "message": "Organization account is suspended or inactive."
        }), 403

    # Authentication successful: clear rate limits
    clear_rate_limit(rate_key)

    # Create server-side session
    user_agent = request.headers.get("User-Agent", "")
    session = create_user_session(
        user_id=user.id,
        ip_address=ip_addr,
        user_agent=user_agent,
        lifetime_hours=24
    )

    log_audit_event(
        action="login_success",
        user_id=user.id,
        organization_id=user.organization_id
    )

    roles = user.get_roles_for_org(user.organization_id)
    org_data = user.organization.to_dict() if user.organization else None

    response_payload = {
        "message": "Login successful.",
        "user": user.to_dict(),
        "organization": org_data,
        "roles": roles,
        "session_token": session.session_token,
        "expires_at": session.expires_at.isoformat()
    }

    response = make_response(jsonify(response_payload), 200)

    # Secure HttpOnly Cookie
    is_prod = current_app.config.get("ENV") == "production"
    response.set_cookie(
        key="pharma_session",
        value=session.session_token,
        max_age=86400,
        httponly=True,
        secure=is_prod,
        samesite="Lax",
        path="/"
    )

    return response


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Revoke user session and clear HttpOnly cookie."""
    token = get_token_from_request()
    if token:
        revoke_user_session(token)
        log_audit_event(action="logout", details={"token_prefix": token[:8]})

    response = make_response(jsonify({
        "message": "Successfully signed out."
    }), 200)

    response.delete_cookie("pharma_session", path="/")
    return response


@auth_bp.route("/me", methods=["GET"])
@login_required
def get_current_user():
    """Retrieve the currently authenticated user with organization and role metadata."""
    user = g.current_user
    org = user.organization.to_dict() if user.organization else None
    roles = user.get_roles_for_org(g.current_org_id)

    # Compute permission flags
    permissions = {
        "is_platform_admin": Role.PLATFORM_ADMIN in roles,
        "is_org_admin": Role.ORG_ADMIN in roles or Role.PLATFORM_ADMIN in roles,
        "can_manage_maintenance": (
            Role.MAINTENANCE_MANAGER in roles or
            Role.ORG_ADMIN in roles or
            Role.PLATFORM_ADMIN in roles
        ),
        "can_review_diagnostics": (
            Role.MAINTENANCE_ENGINEER in roles or
            Role.MAINTENANCE_MANAGER in roles or
            Role.ORG_ADMIN in roles or
            Role.PLATFORM_ADMIN in roles
        ),
        "can_view": True,
    }

    return jsonify({
        "user": user.to_dict(g.current_org_id),
        "organization": org,
        "roles": roles,
        "permissions": permissions
    }), 200


@auth_bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    """
    Secure password rotation endpoint.
    Validates current password, updates to strong new password,
    revokes all active sessions for the user, and logs an audit event.
    """
    data = request.get_json(silent=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""

    if not current_password or not new_password:
        return jsonify({
            "error": "Bad Request",
            "message": "Both current_password and new_password are required."
        }), 400

    user = g.current_user
    if not user.check_password(current_password):
        return jsonify({
            "error": "Unauthorized",
            "message": "Current password is incorrect."
        }), 401

    if len(new_password) < 12:
        return jsonify({
            "error": "Bad Request",
            "message": "Password must be at least 12 characters long."
        }), 400

    user.set_password(new_password)

    # Revoke all existing sessions for this user
    UserSession.query.filter_by(user_id=user.id).update({"is_revoked": True})
    db.session.commit()

    log_audit_event(
        action="password_rotated",
        user_id=user.id,
        organization_id=user.organization_id,
        details={"status": "success"}
    )

    return jsonify({
        "message": "Password updated successfully. All existing sessions have been revoked."
    }), 200


@auth_bp.route("/seed", methods=["POST"])
def seed_initial_data():
    """
    Controlled bootstrap endpoint for initial environment initialization.
    Permanently locks after initial seeding to prevent unauthorized modification.
    """
    # Security Lockdown: Permanently reject if initial seed has already occurred
    admin_exists = User.query.filter_by(email="admin@getzpharma.com").first() is not None
    roles_exist = Role.query.first() is not None
    if admin_exists and roles_exist:
        return jsonify({
            "error": "Forbidden",
            "message": "Bootstrap seeding has already been completed and is locked for security."
        }), 403

    # Require explicit bootstrap authorization key for production/staging environments
    req_key = request.headers.get("X-Bootstrap-Key", "")
    expected_key = current_app.config.get("BOOTSTRAP_KEY", "pharma-predict-bootstrap-2026")
    is_allowed = (current_app.config.get("ENV") not in ("production", "staging")) or (req_key == expected_key)

    if not is_allowed:
        return jsonify({"error": "Forbidden", "message": "Bootstrap endpoint disabled or invalid bootstrap key."}), 403

    # 1. Provision Roles
    roles_dict = {}
    for role_name in Role.ALL_ROLES:
        role = Role.query.filter_by(name=role_name).first()
        if not role:
            role = Role(
                name=role_name,
                description=f"Standard {role_name} permissions for PharmaPredict AI"
            )
            db.session.add(role)
        roles_dict[role_name] = role
    db.session.commit()

    # 2. Provision Demo Organizations (Getz Pharma & Benchmark Pharma to test multi-tenancy)
    org_getz = Organization.query.filter_by(name="Getz Pharma").first()
    if not org_getz:
        org_getz = Organization(
            name="Getz Pharma",
            slug="getz-pharma",
            status="active"
        )
        db.session.add(org_getz)

    org_benchmark = Organization.query.filter_by(name="Benchmark Pharmaceuticals").first()
    if not org_benchmark:
        org_benchmark = Organization(
            name="Benchmark Pharmaceuticals",
            slug="benchmark-pharma",
            status="active"
        )
        db.session.add(org_benchmark)
    db.session.commit()

    # 3. Provision Sites for Getz Pharma
    site_u1 = Site.query.filter_by(organization_id=org_getz.id, name="Unit-1 Korangi").first()
    if not site_u1:
        site_u1 = Site(
            organization_id=org_getz.id,
            name="Unit-1 Korangi",
            location="Plot 29-30/27, K.I.A., Karachi, Pakistan",
            code="GP-U1",
            status="active"
        )
        db.session.add(site_u1)

    site_u2 = Site.query.filter_by(organization_id=org_getz.id, name="Unit-2 Sterile BFS").first()
    if not site_u2:
        site_u2 = Site(
            organization_id=org_getz.id,
            name="Unit-2 Sterile BFS",
            location="Korangi Industrial Area, Karachi",
            code="GP-U2",
            status="active"
        )
        db.session.add(site_u2)

    # Site for Benchmark Pharmaceuticals
    site_bm = Site.query.filter_by(organization_id=org_benchmark.id, name="Lahore Formulation Facility").first()
    if not site_bm:
        site_bm = Site(
            organization_id=org_benchmark.id,
            name="Lahore Formulation Facility",
            location="Sundar Industrial Estate, Lahore",
            code="BM-LHE",
            status="active"
        )
        db.session.add(site_bm)
    db.session.commit()

    # 4. Provision Standard Users
    # Saad Javed - Assistant Manager Maintenance (Getz Pharma)
    saad = User.query.filter_by(email="saad.javed@pharmapredict.ai").first()
    if not saad:
        saad = User(
            organization_id=org_getz.id,
            full_name="Saad Javed",
            email="saad.javed@pharmapredict.ai",
            is_active=True
        )
        saad.set_password("PharmaPredict@2026")
        db.session.add(saad)
        db.session.commit()

        # Assign Maintenance Manager role
        assign = UserRoleAssignment(
            user_id=saad.id,
            role_id=roles_dict[Role.MAINTENANCE_MANAGER].id,
            organization_id=org_getz.id
        )
        db.session.add(assign)

    # Admin User (Getz Pharma)
    admin_user = User.query.filter_by(email="admin@getzpharma.com").first()
    if not admin_user:
        admin_user = User(
            organization_id=org_getz.id,
            full_name="Getz Pharma Administrator",
            email="admin@getzpharma.com",
            is_active=True
        )
        admin_user.set_password("Admin@Getz2026")
        db.session.add(admin_user)
        db.session.commit()

        assign = UserRoleAssignment(
            user_id=admin_user.id,
            role_id=roles_dict[Role.ORG_ADMIN].id,
            organization_id=org_getz.id
        )
        db.session.add(assign)

    # Benchmark User (Belongs strictly to Benchmark Pharmaceuticals)
    bm_user = User.query.filter_by(email="engineer@benchmarkpharma.com").first()
    if not bm_user:
        bm_user = User(
            organization_id=org_benchmark.id,
            full_name="Benchmark Engineer",
            email="engineer@benchmarkpharma.com",
            is_active=True
        )
        bm_user.set_password("Benchmark@2026")
        db.session.add(bm_user)
        db.session.commit()

        assign = UserRoleAssignment(
            user_id=bm_user.id,
            role_id=roles_dict[Role.MAINTENANCE_ENGINEER].id,
            organization_id=org_benchmark.id
        )
        db.session.add(assign)

    db.session.commit()

    return jsonify({
        "message": "Bootstrap completed successfully.",
        "seeded": {
            "roles": list(roles_dict.keys()),
            "organizations": [org_getz.name, org_benchmark.name],
            "sites": [site_u1.name, site_u2.name, site_bm.name],
            "users": [
                {"email": saad.email, "org": org_getz.name, "role": Role.MAINTENANCE_MANAGER},
                {"email": admin_user.email, "org": org_getz.name, "role": Role.ORG_ADMIN},
                {"email": bm_user.email, "org": org_benchmark.name, "role": Role.MAINTENANCE_ENGINEER},
            ]
        }
    }), 200

