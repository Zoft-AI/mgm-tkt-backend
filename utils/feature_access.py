"""
RBAC: Feature access checks for members.
Owner (is_owner=true) bypasses all checks.
"""
from typing import Dict, Any

FEATURES = ["campaigns", "tickets", "help_desk"]


def can_view(member: Dict[str, Any], feature: str) -> bool:
    """True if member can view the feature."""
    if member.get("is_owner"):
        return True
    access = (member.get("feature_access") or {}).get(feature, "none")
    return access in ("viewer", "editor")


def can_edit(member: Dict[str, Any], feature: str) -> bool:
    """True if member can create/update/run (not delete)."""
    if member.get("is_owner"):
        return True
    return (member.get("feature_access") or {}).get(feature) == "editor"


def can_delete(member: Dict[str, Any]) -> bool:
    """True if member can delete resources (owner only)."""
    return bool(member.get("is_owner"))


def can_manage_team(member: Dict[str, Any]) -> bool:
    """True if member can add/remove members, change permissions."""
    return bool(member.get("is_owner"))


def get_member_feature_access(member: Dict[str, Any]) -> Dict[str, str]:
    """Return effective access for frontend (owner = all editor)."""
    if member.get("is_owner"):
        return {f: "editor" for f in FEATURES}
    return {f: (member.get("feature_access") or {}).get(f, "none") for f in FEATURES}
