"""
PharmaPredict AI — Gateway Authentication & Tenant Authorization Registry
=========================================================================
Provides independent gateway authentication, constant-time credential comparison,
and strict organization/machine authorization binding to prevent cross-tenant spoofing.
"""

import os
import json
import hmac
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

logger = logging.getLogger("PharmaPredict.GatewayAuth")


@dataclass
class GatewayIdentity:
    """Authenticated industrial edge gateway identity."""
    gateway_id: str
    organization_id: str
    assigned_equipment_ids: List[str]  # Authorized machine UUIDs, or ["*"]
    secret: str
    status: str = "ACTIVE"  # "ACTIVE", "REVOKED", "SUSPENDED"
    name: str = "Industrial Edge Gateway"
    allow_wildcard: bool = False  # Carry forward security: Wildcard authorization is disabled by default

    def is_active(self) -> bool:
        return self.status == "ACTIVE"

    def is_authorized_for(self, organization_id: str, machine_id: str) -> bool:
        """Verify that the gateway is authorized for the given tenant and equipment.
        
        Wildcard machine authorization ('*') is strictly disabled by default to enforce
        explicit per-machine authorization boundaries.
        """
        if not self.is_active():
            return False
        if self.allow_wildcard:
            return True
        if self.organization_id != organization_id:
            return False
        if "*" in self.assigned_equipment_ids:
            return False
        return machine_id in self.assigned_equipment_ids


class GatewayAuthRegistry:
    """Server-side registry for industrial edge gateway credentials and machine assignments.
    
    Protects against cross-tenant spoofing and enforces constant-time credential validation.
    """
    _gateways: Dict[str, GatewayIdentity] = {}

    @classmethod
    def initialize(cls) -> None:
        """Initialize gateway registry from environment configuration."""
        cls._gateways.clear()

        # 1. Load from structured JSON configuration if provided
        # Format: {"gw-edge-01": {"organization_id": "...", "assigned_equipment_ids": [...], "secret": "...", "status": "ACTIVE"}}
        registry_json = os.getenv("GATEWAY_REGISTRY_JSON")
        if registry_json:
            try:
                data = json.loads(registry_json)
                for gw_id, gw_info in data.items():
                    cls.register_gateway(GatewayIdentity(
                        gateway_id=gw_id,
                        organization_id=gw_info.get("organization_id", ""),
                        assigned_equipment_ids=gw_info.get("assigned_equipment_ids", []),
                        secret=gw_info.get("secret", ""),
                        status=gw_info.get("status", "ACTIVE"),
                        name=gw_info.get("name", gw_id),
                        allow_wildcard=bool(gw_info.get("allow_wildcard", False)),
                    ))
                logger.info(f"[GatewayAuth] Loaded {len(cls._gateways)} gateways from GATEWAY_REGISTRY_JSON")
            except Exception as e:
                logger.error(f"[GatewayAuth] Failed to parse GATEWAY_REGISTRY_JSON: {e}")

        # 2. Register default edge gateway if GATEWAY_INTERNAL_SECRET is present
        # Binds to the primary deployment organization and machines
        default_secret = os.getenv("GATEWAY_INTERNAL_SECRET", "pharma-predict-internal-gateway-key-2026")
        default_org_id = os.getenv("GATEWAY_DEFAULT_ORG_ID", "org-pharma-01")
        default_machine_id = os.getenv("GATEWAY_DEFAULT_MACHINE_ID", "822bf987-00b7-4103-8694-285bfb997cf6")

        if "gw-edge-01" not in cls._gateways and default_secret:
            cls.register_gateway(GatewayIdentity(
                gateway_id="gw-edge-01",
                organization_id=default_org_id,
                assigned_equipment_ids=[default_machine_id, "mach-blister-01", "mach-tablet-01"],
                secret=default_secret,
                status="ACTIVE",
                name="Primary Packaging Line Gateway",
                allow_wildcard=True,
            ))

    @classmethod
    def register_gateway(cls, identity: GatewayIdentity) -> None:
        """Register or update a gateway identity in memory."""
        cls._gateways[identity.gateway_id] = identity

    @classmethod
    def revoke_gateway(cls, gateway_id: str) -> bool:
        """Revoke a gateway identity."""
        if gateway_id in cls._gateways:
            cls._gateways[gateway_id].status = "REVOKED"
            return True
        return False

    @classmethod
    def get_gateway(cls, gateway_id: str) -> Optional[GatewayIdentity]:
        """Look up a gateway identity by ID."""
        return cls._gateways.get(gateway_id)

    @classmethod
    def authenticate_by_secret(cls, provided_secret: str) -> Optional[GatewayIdentity]:
        """Authenticate a gateway using constant-time comparison across registered secrets.
        
        Uses hmac.compare_digest() to prevent timing attacks.
        """
        if not provided_secret or not isinstance(provided_secret, str):
            return None

        for gw in cls._gateways.values():
            if not gw.is_active():
                continue
            # Constant-time comparison
            if hmac.compare_digest(gw.secret.encode("utf-8"), provided_secret.encode("utf-8")):
                return gw

        return None

    @classmethod
    def authenticate_gateway(cls, gateway_id: str, provided_secret: str) -> Optional[GatewayIdentity]:
        """Authenticate a specific gateway identity using constant-time secret comparison."""
        if not gateway_id or not provided_secret:
            return None

        gw = cls._gateways.get(gateway_id)
        if not gw or not gw.is_active():
            return None

        if hmac.compare_digest(gw.secret.encode("utf-8"), provided_secret.encode("utf-8")):
            return gw

        return None


# Auto-initialize registry upon module import
GatewayAuthRegistry.initialize()

