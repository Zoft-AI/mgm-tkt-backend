"""
Service for Team Member operations
"""
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Tuple

from db.member_repository import member_repository, MemberRepository
from utils.feature_access import can_manage_team, get_member_feature_access
from utils.email_service import notify_member_invited
from models.member import (
    InviteMember, UpdateMember, MemberResponse, MemberListResponse,
    InviteResponse, HierarchyLevel, HierarchyListResponse,
    WorkspaceInfo, MyWorkspacesResponse,
    InvitationListItem, InvitationListResponse,
    NotificationItem, NotificationListResponse
)

INVITATION_EXPIRY_DAYS = 7

logger = logging.getLogger(__name__)


class MemberService:
    """Service for team member business logic"""
    
    def __init__(self):
        self.repository: MemberRepository = member_repository
    
    # ========================================================================
    # Context/Auth Helpers
    # ========================================================================
    
    async def get_actor_context(
        self, 
        profile_id: str, 
        workspace_id: str
    ) -> Tuple[Optional[Dict], Optional[Dict], Optional[str]]:
        """Get workspace and actor member context"""
        try:
            # Get workspace
            workspace = await self.repository.get_workspace(workspace_id)
            if not workspace:
                return None, None, "Workspace not found"
            
            # Get actor's membership in this workspace
            actor = await self.repository.get_member_by_profile_workspace(profile_id, workspace_id)
            if not actor:
                return workspace, None, "You are not a member of this workspace"
            
            if actor.get("status") != "active":
                return workspace, None, "Your membership is not active"
            
            return workspace, actor, None
            
        except Exception as e:
            logger.error(f"Error getting actor context: {str(e)}")
            return None, None, str(e)
    
    async def check_permission(
        self, 
        actor: Dict, 
        required_level: int,
        action: str = "perform this action"
    ) -> Optional[str]:
        """Check if actor has required permission level"""
        actor_level = actor.get("hierarchy_level", 1)
        
        if actor_level < required_level:
            return f"Insufficient permission to {action}. Required level: {required_level}, your level: {actor_level}"
        
        return None
    
    # ========================================================================
    # List Members
    # ========================================================================
    
    async def list_members(
        self, 
        profile_id: str, 
        workspace_id: str,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[Optional[MemberListResponse], Optional[str]]:
        """List all members in a workspace"""
        try:
            workspace, actor, error = await self.get_actor_context(profile_id, workspace_id)
            if error:
                return None, error
            
            # Get members
            members, total = await self.repository.get_members_by_workspace(
                workspace_id, status, page, page_size
            )
            
            # Build responses with resolved names
            member_responses = []
            for m in members:
                response = await self._build_member_response(m, workspace_id)
                member_responses.append(response)
            
            return MemberListResponse(members=member_responses, total=total), None
            
        except Exception as e:
            logger.error(f"Error listing members: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # Get Single Member
    # ========================================================================
    
    async def get_member_by_profile(
        self,
        profile_id: str,
        workspace_id: str,
        target_profile_id: str
    ) -> Tuple[Optional[MemberResponse], Optional[str]]:
        """Get a single member by profile_id and workspace_id. Uses members table only (no Workspaces lookup)."""
        try:
            actor = await self.repository.get_member_by_profile_workspace(profile_id, workspace_id)
            if not actor:
                return None, "You are not a member of this workspace"
            if actor.get("status") != "active":
                return None, "Your membership is not active"

            member = await self.repository.get_member_by_profile_workspace(target_profile_id, workspace_id)
            if not member:
                return None, "Member not found"
            if member.get("workspace_id") != workspace_id:
                return None, "Member not in this workspace"

            response = await self._build_member_response(member, workspace_id)
            return response, None

        except Exception as e:
            logger.error(f"Error getting member by profile: {str(e)}")
            return None, str(e)

    async def get_member(
        self, 
        profile_id: str, 
        workspace_id: str,
        member_id: str
    ) -> Tuple[Optional[MemberResponse], Optional[str]]:
        """Get a single member by ID"""
        try:
            workspace, actor, error = await self.get_actor_context(profile_id, workspace_id)
            if error:
                return None, error
            
            member = await self.repository.get_member_by_id(member_id)
            if not member:
                return None, "Member not found"
            
            if member.get("workspace_id") != workspace_id:
                return None, "Member not in this workspace"
            
            response = await self._build_member_response(member, workspace_id)
            return response, None
            
        except Exception as e:
            logger.error(f"Error getting member: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # Invite Member
    # ========================================================================
    
    async def invite_member(
        self, 
        profile_id: str, 
        workspace_id: str,
        data: InviteMember
    ) -> Tuple[Optional[InviteResponse], Optional[str]]:
        """Invite a new member to the workspace"""
        try:
            workspace, actor, error = await self.get_actor_context(profile_id, workspace_id)
            if error:
                return None, error
            
            if not can_manage_team(actor):
                return None, "Only workspace owner can invite members"
            
            # Check if email already exists in workspace
            existing = await self.repository.get_member_by_email_workspace(data.email, workspace_id)
            if existing:
                return None, f"Member with email {data.email} already exists in this workspace"
            
            # Check if reports_to exists (if provided)
            if data.reports_to:
                manager = await self.repository.get_member_by_id(data.reports_to)
                if not manager or manager.get("workspace_id") != workspace_id:
                    return None, "Reports to member not found in this workspace"
            
            # Check if user already has a profile (existing user)
            profile = await self.repository.get_profile_by_email(data.email)
            profile_id_value = profile["id"] if profile else None
            status = "active" if profile else "pending"
            
            # Resolve name: provided > profile name > email prefix
            resolved_name = data.name
            if not resolved_name and profile:
                resolved_name = profile.get("name") or profile.get("full_name")
            if not resolved_name:
                resolved_name = data.email.split("@")[0].replace(".", " ").title()
            
            now = datetime.now(timezone.utc)
            invitation_token = secrets.token_urlsafe(32) if status == "pending" else None
            invitation_expires_at = (now + timedelta(days=INVITATION_EXPIRY_DAYS)).isoformat() if status == "pending" else None

            member_data = {
                "workspace_id": workspace_id,
                "profile_id": profile_id_value,
                "email": data.email.lower(),
                "name": resolved_name,
                "hierarchy_level": data.hierarchy_level,
                "designation": data.designation,
                "department": data.department,
                "employee_id": data.employee_id,
                "reports_to": data.reports_to,
                "status": status,
                "is_owner": False,
                "is_active": True,
                "invited_by": actor["id"],
                "invited_at": now.isoformat(),
                "invitation_token": invitation_token,
                "invitation_expires_at": invitation_expires_at,
                "data": data.data or {}
            }
            if data.feature_access is not None:
                member_data["feature_access"] = data.feature_access
            
            created = await self.repository.create_member(member_data)
            if not created:
                return None, "Failed to create member"
            
            # Get level name
            hierarchy = await self.repository.get_hierarchy_level(workspace_id, data.hierarchy_level)
            level_name = hierarchy.get("level_name") if hierarchy else f"Level {data.hierarchy_level}"
            
            message = "Member added successfully" if status == "active" else "Invitation sent. Member will be activated when they sign up."
            
            # Send invite email with token link (fire-and-forget)
            workspace_name = workspace.get("workspace_name", "Workspace") if workspace else "Workspace"
            inviter_name = actor.get("name", "Team Owner") if actor else "Team Owner"
            await notify_member_invited(
                invitee_email=data.email,
                workspace_name=workspace_name,
                inviter_name=inviter_name,
                role=level_name,
                designation=data.designation,
                invitation_token=invitation_token,
            )
            
            return InviteResponse(
                id=created["id"],
                email=created["email"],
                name=created["name"],
                hierarchy_level=created["hierarchy_level"],
                level_name=level_name,
                status=status,
                invitation_token=invitation_token,
                invitation_expires_at=created.get("invitation_expires_at"),
                message=message
            ), None
            
        except Exception as e:
            logger.error(f"Error inviting member: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # Update Member
    # ========================================================================
    
    async def update_member(
        self, 
        profile_id: str, 
        workspace_id: str,
        member_id: str,
        data: UpdateMember
    ) -> Tuple[Optional[MemberResponse], Optional[str]]:
        """Update a member's details"""
        try:
            workspace, actor, error = await self.get_actor_context(profile_id, workspace_id)
            if error:
                return None, error
            
            # Get target member
            target = await self.repository.get_member_by_id(member_id)
            if not target:
                return None, "Member not found"
            
            if target.get("workspace_id") != workspace_id:
                return None, "Member not in this workspace"
            
            # Cannot update owner
            if target.get("is_owner") and not actor.get("is_owner"):
                return None, "Cannot modify workspace owner"
            
            # Permission check: need to be higher level than target OR be owner
            actor_level = actor.get("hierarchy_level", 1)
            target_level = target.get("hierarchy_level", 1)
            
            if not actor.get("is_owner") and actor_level <= target_level:
                return None, "You can only modify members at a lower level than yourself"
            
            # Cannot promote to level higher than or equal to self (unless owner)
            if data.hierarchy_level and not actor.get("is_owner"):
                if data.hierarchy_level >= actor_level:
                    return None, f"Cannot promote member to level {data.hierarchy_level} or higher"
            
            # Build update data
            update_data = {}
            
            if data.name is not None:
                update_data["name"] = data.name
            if data.hierarchy_level is not None:
                update_data["hierarchy_level"] = data.hierarchy_level
            if data.designation is not None:
                update_data["designation"] = data.designation
            if data.department is not None:
                update_data["department"] = data.department
            if data.employee_id is not None:
                update_data["employee_id"] = data.employee_id
            if data.reports_to is not None:
                # Validate reports_to
                if data.reports_to:
                    manager = await self.repository.get_member_by_id(data.reports_to)
                    if not manager or manager.get("workspace_id") != workspace_id:
                        return None, "Reports to member not found"
                update_data["reports_to"] = data.reports_to
            if data.is_active is not None:
                update_data["is_active"] = data.is_active
                if not data.is_active:
                    update_data["status"] = "inactive"
            if data.feature_access is not None:
                update_data["feature_access"] = data.feature_access
            if data.data is not None:
                update_data["data"] = data.data

            if not update_data:
                return None, "No fields to update"
            
            updated = await self.repository.update_member(member_id, update_data)
            if not updated:
                return None, "Failed to update member"
            
            response = await self._build_member_response(updated, workspace_id)
            return response, None
            
        except Exception as e:
            logger.error(f"Error updating member: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # Remove Member
    # ========================================================================
    
    async def remove_member(
        self, 
        profile_id: str, 
        workspace_id: str,
        member_id: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Remove a member from the workspace"""
        try:
            workspace, actor, error = await self.get_actor_context(profile_id, workspace_id)
            if error:
                return None, error
            
            if not can_manage_team(actor):
                return None, "Only workspace owner can remove members"
            
            # Get target member
            target = await self.repository.get_member_by_id(member_id)
            if not target:
                return None, "Member not found"
            
            if target.get("workspace_id") != workspace_id:
                return None, "Member not in this workspace"
            
            # Cannot remove self (owner)
            if target["id"] == actor["id"]:
                return None, "Cannot remove yourself from the workspace"
            
            # Cannot remove another owner
            if target.get("is_owner"):
                return None, "Cannot remove workspace owner"
            
            # Soft delete (set inactive)
            success = await self.repository.delete_member(member_id)
            if not success:
                return None, "Failed to remove member"
            
            return {"message": f"Member {target['name']} has been removed from the workspace"}, None
            
        except Exception as e:
            logger.error(f"Error removing member: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # Accept Invitation (Public — token-based)
    # ========================================================================

    async def accept_invitation(
        self,
        token: str,
        profile_id: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Accept an invitation by token. If profile_id provided, link immediately."""
        try:
            member = await self.repository.get_member_by_invitation_token(token)
            if not member:
                return None, "Invalid invitation token"

            if member.get("status") == "active":
                workspace = await self.repository.get_workspace(member["workspace_id"])
                workspace_name = workspace.get("workspace_name", "Workspace") if workspace else "Workspace"
                return {
                    "message": "Invitation already accepted",
                    "workspace_id": member["workspace_id"],
                    "workspace_name": workspace_name,
                    "member_id": member["id"],
                    "email": member["email"],
                    "status": "active",
                    "already_active": True
                }, None

            if member.get("status") not in ("pending",):
                return None, f"Invitation is no longer pending (status: {member.get('status')})"

            expires_at = member.get("invitation_expires_at")
            if expires_at:
                if isinstance(expires_at, str):
                    exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                else:
                    exp = expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > exp:
                    await self.repository.update_member(member["id"], {
                        "status": "expired",
                        "invitation_token": None,
                        "invitation_expires_at": None,
                    })
                    return None, "Invitation has expired"

            workspace = await self.repository.get_workspace(member["workspace_id"])
            workspace_name = workspace.get("workspace_name", "Workspace") if workspace else "Workspace"

            if profile_id:
                profile = await self.repository.get_profile(profile_id)
                if not profile:
                    return None, "Profile not found for logged-in user"
                
                profile_email = (profile.get("email") or "").lower()
                invitation_email = (member.get("email") or "").lower()
                if profile_email != invitation_email:
                    return None, f"This invitation was sent to {invitation_email}. You are logged in as {profile_email}. Please log in with {invitation_email} to accept this invitation."

                activated = await self.repository.activate_member(member["id"], profile_id)
                if not activated:
                    return None, "Failed to activate membership"

                hierarchy = await self.repository.get_hierarchy_level(
                    member["workspace_id"], member.get("hierarchy_level", 1)
                )
                level_name = hierarchy.get("level_name") if hierarchy else f"Level {member.get('hierarchy_level', 1)}"

                return {
                    "message": "Invitation accepted successfully",
                    "workspace_id": member["workspace_id"],
                    "workspace_name": workspace_name,
                    "member_id": member["id"],
                    "role": level_name,
                    "email": member["email"],
                    "status": "active"
                }, None

            return {
                "message": "Invitation is valid. Please sign up or log in to accept.",
                "email": member["email"],
                "workspace_name": workspace_name,
                "workspace_id": member["workspace_id"],
                "requires_auth": True,
                "status": "pending"
            }, None

        except Exception as e:
            logger.error(f"Error accepting invitation: {str(e)}")
            return None, str(e)

    # ========================================================================
    # Revoke Invitation
    # ========================================================================

    async def revoke_invitation(
        self,
        profile_id: str,
        workspace_id: str,
        member_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Revoke a pending invitation. Owner only."""
        try:
            workspace, actor, error = await self.get_actor_context(profile_id, workspace_id)
            if error:
                return None, error

            if not can_manage_team(actor):
                return None, "Only workspace owner can revoke invitations"

            target = await self.repository.get_member_by_id(member_id)
            if not target:
                return None, "Invitation not found"

            if target.get("workspace_id") != workspace_id:
                return None, "Invitation not in this workspace"

            if target.get("status") != "pending":
                return None, f"Can only revoke pending invitations (current status: {target.get('status')})"

            revoked = await self.repository.revoke_invitation(member_id)
            if not revoked:
                return None, "Failed to revoke invitation"

            return {"message": f"Invitation for {target['email']} has been revoked"}, None

        except Exception as e:
            logger.error(f"Error revoking invitation: {str(e)}")
            return None, str(e)

    # ========================================================================
    # List Invitations
    # ========================================================================

    async def list_invitations(
        self,
        profile_id: str,
        workspace_id: str,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[Optional[InvitationListResponse], Optional[str]]:
        """List all invitations (pending/revoked/expired) for a workspace. Owner only."""
        try:
            workspace, actor, error = await self.get_actor_context(profile_id, workspace_id)
            if error:
                return None, error

            if not can_manage_team(actor):
                return None, "Only workspace owner can view invitations"

            invitations, total = await self.repository.get_pending_invitations(
                workspace_id, page, page_size
            )

            now = datetime.now(timezone.utc)
            items = []
            for inv in invitations:
                invited_by_name = None
                if inv.get("invited_by"):
                    inviter = await self.repository.get_member_by_id(inv["invited_by"])
                    if inviter:
                        invited_by_name = inviter.get("name")

                hierarchy = await self.repository.get_hierarchy_level(
                    workspace_id, inv.get("hierarchy_level", 1)
                )
                level_name = hierarchy.get("level_name") if hierarchy else None

                is_expired = False
                expires_at = inv.get("invitation_expires_at")
                if expires_at and inv.get("status") == "pending":
                    if isinstance(expires_at, str):
                        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    else:
                        exp = expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    is_expired = now > exp

                items.append(InvitationListItem(
                    id=inv["id"],
                    email=inv["email"],
                    name=inv.get("name", ""),
                    hierarchy_level=inv.get("hierarchy_level", 1),
                    level_name=level_name,
                    designation=inv.get("designation"),
                    department=inv.get("department"),
                    status="expired" if is_expired else inv.get("status", "pending"),
                    is_expired=is_expired,
                    invited_by_name=invited_by_name,
                    invited_at=inv.get("invited_at"),
                    invitation_expires_at=expires_at,
                    feature_access=inv.get("feature_access", {}),
                ))

            return InvitationListResponse(invitations=items, total=total), None

        except Exception as e:
            logger.error(f"Error listing invitations: {str(e)}")
            return None, str(e)

    # ========================================================================
    # Resend Invitation
    # ========================================================================

    async def resend_invitation(
        self,
        profile_id: str,
        workspace_id: str,
        member_id: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Resend invitation email with new token + expiry. Owner only."""
        try:
            workspace, actor, error = await self.get_actor_context(profile_id, workspace_id)
            if error:
                return None, error

            if not can_manage_team(actor):
                return None, "Only workspace owner can resend invitations"

            target = await self.repository.get_member_by_id(member_id)
            if not target:
                return None, "Invitation not found"

            if target.get("workspace_id") != workspace_id:
                return None, "Invitation not in this workspace"

            if target.get("status") not in ("pending", "expired"):
                return None, f"Can only resend pending or expired invitations (current: {target.get('status')})"

            now = datetime.now(timezone.utc)
            new_token = secrets.token_urlsafe(32)
            new_expires = (now + timedelta(days=INVITATION_EXPIRY_DAYS)).isoformat()

            updated = await self.repository.update_member(member_id, {
                "invitation_token": new_token,
                "invitation_expires_at": new_expires,
                "status": "pending",
                "is_active": True,
                "updated_at": now.isoformat()
            })
            if not updated:
                return None, "Failed to resend invitation"

            hierarchy = await self.repository.get_hierarchy_level(workspace_id, target.get("hierarchy_level", 1))
            level_name = hierarchy.get("level_name") if hierarchy else f"Level {target.get('hierarchy_level', 1)}"

            workspace_name = workspace.get("workspace_name", "Workspace") if workspace else "Workspace"
            inviter_name = actor.get("name", "Team Owner")
            await notify_member_invited(
                invitee_email=target["email"],
                workspace_name=workspace_name,
                inviter_name=inviter_name,
                role=level_name,
                designation=target.get("designation"),
                invitation_token=new_token,
            )

            return {
                "message": f"Invitation resent to {target['email']}",
                "invitation_token": new_token,
                "invitation_expires_at": new_expires
            }, None

        except Exception as e:
            logger.error(f"Error resending invitation: {str(e)}")
            return None, str(e)

    # ========================================================================
    # Hierarchy
    # ========================================================================
    
    async def get_hierarchy(
        self, 
        profile_id: str, 
        workspace_id: str
    ) -> Tuple[Optional[HierarchyListResponse], Optional[str]]:
        """Get hierarchy levels for a workspace"""
        try:
            workspace, actor, error = await self.get_actor_context(profile_id, workspace_id)
            if error:
                return None, error
            
            levels = await self.repository.get_hierarchy_levels(workspace_id)
            
            hierarchy_levels = [
                HierarchyLevel(
                    id=h["id"],
                    workspace_id=h["workspace_id"],
                    level=h["level"],
                    level_name=h["level_name"],
                    reports_to_level=h.get("reports_to_level"),
                    data=h.get("data", {}),
                    created_at=h["created_at"]
                )
                for h in levels
            ]
            
            return HierarchyListResponse(levels=hierarchy_levels, total=len(hierarchy_levels)), None
            
        except Exception as e:
            logger.error(f"Error getting hierarchy: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # My Workspaces
    # ========================================================================
    
    async def get_my_workspaces(
        self, 
        profile_id: str
    ) -> Tuple[Optional[MyWorkspacesResponse], Optional[str]]:
        """Get all workspaces (owned + shared) for the logged-in user"""
        try:
            # Get all workspaces for this profile
            data = await self.repository.get_all_workspaces_for_profile(profile_id)
            
            workspaces = []
            owned_count = 0
            shared_count = 0
            
            for item in data:
                m = item["membership"]
                ws = item["workspace"]
                
                # Get level name
                level_name = "Member"
                hierarchy = await self.repository.get_hierarchy_level(
                    m["workspace_id"], m.get("hierarchy_level", 1)
                )
                if hierarchy:
                    level_name = hierarchy.get("level_name", "Member")
                
                # Get invited_by name
                invited_by_name = None
                if m.get("invited_by"):
                    inviter = await self.repository.get_member_by_id(m["invited_by"])
                    if inviter:
                        invited_by_name = inviter.get("name")
                
                is_owner = m.get("is_owner", False)
                if is_owner:
                    owned_count += 1
                else:
                    shared_count += 1
                
                feature_access = get_member_feature_access(m)
                workspaces.append(WorkspaceInfo(
                    id=ws["id"],
                    workspace_name=ws.get("workspace_name", "Unnamed"),
                    is_owner=is_owner,
                    role=level_name,
                    hierarchy_level=m.get("hierarchy_level", 1),
                    member_id=m.get("id"),  # Can be None for virtual memberships
                    status=m.get("status", "active"),
                    feature_access=feature_access,
                    joined_at=m.get("invited_at") or m.get("created_at"),
                    invited_by_name=invited_by_name
                ))
            
            # Sort: owned first, then by name
            workspaces.sort(key=lambda x: (not x.is_owner, x.workspace_name.lower()))
            
            return MyWorkspacesResponse(
                workspaces=workspaces,
                total=len(workspaces),
                owned_count=owned_count,
                shared_count=shared_count
            ), None
            
        except Exception as e:
            logger.error(f"Error getting my workspaces: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    async def _build_member_response(
        self, 
        member: Dict[str, Any],
        workspace_id: str
    ) -> MemberResponse:
        """Build a MemberResponse with resolved names"""
        # Get level name
        level_name = None
        hierarchy = await self.repository.get_hierarchy_level(workspace_id, member.get("hierarchy_level", 1))
        if hierarchy:
            level_name = hierarchy.get("level_name")
        
        # Get reports_to name
        reports_to_name = None
        if member.get("reports_to"):
            manager = await self.repository.get_member_by_id(member["reports_to"])
            if manager:
                reports_to_name = manager.get("name")
        
        # Get invited_by name
        invited_by_name = None
        if member.get("invited_by"):
            inviter = await self.repository.get_member_by_id(member["invited_by"])
            if inviter:
                invited_by_name = inviter.get("name")
        
        feature_access = get_member_feature_access(member)
        return MemberResponse(
            id=member["id"],
            profile_id=member.get("profile_id"),
            workspace_id=member["workspace_id"],
            email=member["email"],
            name=member["name"],
            hierarchy_level=member.get("hierarchy_level", 1),
            level_name=level_name,
            designation=member.get("designation"),
            department=member.get("department"),
            employee_id=member.get("employee_id"),
            reports_to=member.get("reports_to"),
            reports_to_name=reports_to_name,
            status=member.get("status", "active"),
            is_owner=member.get("is_owner", False),
            is_active=member.get("is_active", True),
            feature_access=feature_access,
            invited_by=member.get("invited_by"),
            invited_by_name=invited_by_name,
            invited_at=member.get("invited_at"),
            delegations=member.get("delegations", []),
            data=member.get("data", {}),
            created_at=member["created_at"],
            updated_at=member.get("updated_at")
        )
    
    # ========================================================================
    # Profile Linking (for auto-adding owner)
    # ========================================================================
    
    async def ensure_owner_member(
        self, 
        profile_id: str, 
        workspace_id: str,
        email: str,
        name: str = "Workspace Owner"
    ) -> Optional[Dict[str, Any]]:
        """Ensure workspace owner is in members table"""
        try:
            # Check if owner already exists
            existing = await self.repository.get_member_by_profile_workspace(profile_id, workspace_id)
            if existing:
                return existing
            
            # Create owner member
            member_data = {
                "workspace_id": workspace_id,
                "profile_id": profile_id,
                "email": email.lower(),
                "name": name,
                "hierarchy_level": 6,  # CEO level
                "designation": "Owner",
                "status": "active",
                "is_owner": True,
                "is_active": True,
                "data": {"auto_created": True}
            }
            
            return await self.repository.create_member(member_data)
            
        except Exception as e:
            logger.error(f"Error ensuring owner member: {str(e)}")
            return None

    # ========================================================================
    # Notifications
    # ========================================================================

    async def get_notifications(
        self, profile_id: str
    ) -> Tuple[Optional[NotificationListResponse], Optional[str]]:
        """Get unseen workspace-addition notifications for the logged-in user"""
        try:
            unseen = await self.repository.get_unseen_memberships(profile_id)
            if not unseen:
                return NotificationListResponse(notifications=[], count=0), None

            items: List[NotificationItem] = []
            for m in unseen:
                ws = await self.repository.get_workspace(m["workspace_id"])
                workspace_name = ws.get("workspace_name", "Workspace") if ws else "Workspace"

                invited_by_name = None
                if m.get("invited_by"):
                    inviter = await self.repository.get_member_by_id(m["invited_by"])
                    invited_by_name = inviter.get("name") if inviter else None

                hierarchy = await self.repository.get_hierarchy_level(
                    m["workspace_id"], m.get("hierarchy_level", 1)
                )
                role = hierarchy.get("level_name") if hierarchy else None

                items.append(NotificationItem(
                    member_id=m["id"],
                    workspace_id=m["workspace_id"],
                    workspace_name=workspace_name,
                    invited_by_name=invited_by_name,
                    role=role,
                    designation=m.get("designation"),
                    added_at=m.get("created_at"),
                ))

            return NotificationListResponse(notifications=items, count=len(items)), None

        except Exception as e:
            logger.error(f"Error getting notifications: {str(e)}")
            return None, str(e)

    async def mark_seen(
        self, profile_id: str, member_ids: Optional[List[str]] = None, mark_all: bool = False
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Mark notifications as seen"""
        try:
            if not member_ids and not mark_all:
                return None, "Provide member_ids or set all=true"

            ids_to_mark = None if mark_all else member_ids
            count = await self.repository.mark_memberships_seen(profile_id, ids_to_mark)
            return {"marked_seen": count}, None

        except Exception as e:
            logger.error(f"Error marking seen: {str(e)}")
            return None, str(e)


# Create a singleton instance
member_service = MemberService()
