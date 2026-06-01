"""
API endpoints for Team Management
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Header

from services.member_service import member_service
from services.auth import auth_service
from models.member import (
    InviteMember, UpdateMember, MemberResponse, MemberListResponse,
    InviteResponse, HierarchyListResponse, MyWorkspacesResponse,
    AcceptInvitation, InvitationListResponse, ResendInvitation,
    NotificationListResponse, MarkSeenRequest
)
from utils.sanitize import sanitize_user_input

logger = logging.getLogger(__name__)

# Create router for team management endpoints
member_router = APIRouter(prefix="/workspace", tags=["team"])

# Public router for invitation accept (no auth required)
public_invitation_router = APIRouter(prefix="/public/invitation", tags=["invitation"])


# ============================================================================
# Auth Dependency
# ============================================================================

async def get_current_user(authorization: str = Header(...)) -> str:
    """Extract profile_id from authorization header"""
    try:
        # Sanitize authorization header
        authorization = sanitize_user_input(authorization, strict=True) if authorization else ""
        
        # Pass full authorization header to verify_login (it expects "Bearer token")
        profile_id = await auth_service.verify_login(authorization)
        
        if not profile_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        return profile_id
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auth error: {str(e)}")
        raise HTTPException(status_code=401, detail="Authentication failed")


# ============================================================================
# My Workspaces (All - Owned + Shared)
# ============================================================================

@member_router.get("/all", response_model=MyWorkspacesResponse)
async def get_my_workspaces(
    profile_id: str = Depends(get_current_user)
):
    """
    Get all workspaces for the logged-in user (owned + shared).
    
    Returns both:
    - Workspaces you own (`is_owner: true`)
    - Workspaces you were invited to (`is_owner: false`)
    
    Sorted: owned workspaces first, then alphabetically.
    """
    try:
        result, error = await member_service.get_my_workspaces(profile_id)
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting my workspaces: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get workspaces")


# ============================================================================
# List Members
# ============================================================================

@member_router.get("/{workspace_id}/team", response_model=MemberListResponse)
async def list_members(
    workspace_id: str,
    status: Optional[str] = Query(None, description="Filter by status: active, pending, inactive"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    profile_id: str = Depends(get_current_user)
):
    """
    List all team members in a workspace.
    
    - **workspace_id**: Workspace ID
    - **status**: Optional filter by status (active, pending, inactive)
    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 50, max: 100)
    
    Returns all members with their roles and hierarchy levels.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        
        result, error = await member_service.list_members(
            profile_id, workspace_id, status, page, page_size
        )
        
        if error:
            status_code = 403 if "not a member" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing members: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list members")


# ============================================================================
# Get Single Member
# ============================================================================

@member_router.get("/{workspace_id}/team/by-profile/{target_profile_id}", response_model=MemberResponse)
async def get_member_by_profile(
    workspace_id: str,
    target_profile_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Get a single team member by profile_id and workspace_id.

    - **workspace_id**: Workspace ID
    - **target_profile_id**: Profile ID (profiles.id) of the member to look up

    Use this when you have profile_id but not member_id.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        target_profile_id = sanitize_user_input(target_profile_id, strict=True)

        result, error = await member_service.get_member_by_profile(
            profile_id, workspace_id, target_profile_id
        )

        if error:
            status_code = 404 if "not found" in error.lower() else 403
            raise HTTPException(status_code=status_code, detail=error)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting member by profile: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get member")


@member_router.get("/{workspace_id}/team/{member_id}", response_model=MemberResponse)
async def get_member(
    workspace_id: str,
    member_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Get a single team member by ID.
    
    - **workspace_id**: Workspace ID
    - **member_id**: Member ID
    
    Returns member details including role, hierarchy, and reporting structure.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        member_id = sanitize_user_input(member_id, strict=True)
        
        result, error = await member_service.get_member(
            profile_id, workspace_id, member_id
        )
        
        if error:
            status_code = 404 if "not found" in error.lower() else 403
            raise HTTPException(status_code=status_code, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting member: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get member")


# ============================================================================
# Invite Member
# ============================================================================

@member_router.post("/{workspace_id}/team/invite", response_model=InviteResponse)
async def invite_member(
    workspace_id: str,
    data: InviteMember,
    profile_id: str = Depends(get_current_user)
):
    """
    Invite a new member to the workspace.
    
    - **workspace_id**: Workspace ID
    - **email**: Email of the person to invite
    - **name**: Full name
    - **hierarchy_level**: Role level (1-7)
    - **designation**: Job title (optional)
    - **department**: Department (optional)
    - **reports_to**: Manager's member ID (optional)
    
    Only workspace owner (Level 6+) can invite members.
    If user already has an account, they're added immediately.
    If not, they'll be linked when they sign up.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        
        result, error = await member_service.invite_member(
            profile_id, workspace_id, data
        )
        
        if error:
            status_code = 403 if "permission" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error inviting member: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to invite member")


# ============================================================================
# Update Member
# ============================================================================

@member_router.put("/{workspace_id}/team/{member_id}", response_model=MemberResponse)
async def update_member(
    workspace_id: str,
    member_id: str,
    data: UpdateMember,
    profile_id: str = Depends(get_current_user)
):
    """
    Update a team member's details.
    
    - **workspace_id**: Workspace ID
    - **member_id**: Member ID to update
    - **name**: New name (optional)
    - **hierarchy_level**: New level (optional)
    - **designation**: New job title (optional)
    - **department**: New department (optional)
    - **reports_to**: New manager ID (optional)
    - **is_active**: Active status (optional)
    
    You can only modify members at a lower level than yourself.
    Cannot promote members to your level or higher.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        member_id = sanitize_user_input(member_id, strict=True)
        
        result, error = await member_service.update_member(
            profile_id, workspace_id, member_id, data
        )
        
        if error:
            status_code = 403 if "permission" in error.lower() or "cannot" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating member: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update member")


# ============================================================================
# Remove Member
# ============================================================================

@member_router.delete("/{workspace_id}/team/{member_id}")
async def remove_member(
    workspace_id: str,
    member_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Remove a member from the workspace.
    
    - **workspace_id**: Workspace ID
    - **member_id**: Member ID to remove
    
    Only workspace owner can remove members.
    Cannot remove yourself or the workspace owner.
    Soft delete - member is set to inactive.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        member_id = sanitize_user_input(member_id, strict=True)
        
        result, error = await member_service.remove_member(
            profile_id, workspace_id, member_id
        )
        
        if error:
            status_code = 403 if "only" in error.lower() or "cannot" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing member: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to remove member")


# ============================================================================
# Get Hierarchy
# ============================================================================

@member_router.get("/{workspace_id}/hierarchy", response_model=HierarchyListResponse)
async def get_hierarchy(
    workspace_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Get hierarchy levels for a workspace.
    
    - **workspace_id**: Workspace ID
    
    Returns all defined hierarchy levels with their names and permissions.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        
        result, error = await member_service.get_hierarchy(
            profile_id, workspace_id
        )
        
        if error:
            status_code = 403 if "not a member" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hierarchy: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get hierarchy")


# ============================================================================
# Notifications (Auth - for logged-in user)
# ============================================================================

@member_router.get("/notifications", response_model=NotificationListResponse)
async def get_notifications(
    profile_id: str = Depends(get_current_user)
):
    """
    Get unseen workspace-addition notifications for the logged-in user.
    Returns workspaces the user was recently added to but hasn't seen yet.
    """
    try:
        result, error = await member_service.get_notifications(profile_id)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting notifications: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get notifications")


@member_router.post("/notifications/mark-seen")
async def mark_notifications_seen(
    data: MarkSeenRequest,
    profile_id: str = Depends(get_current_user)
):
    """
    Mark workspace-addition notifications as seen.
    Pass specific member_ids or set all=true to mark everything.
    """
    try:
        result, error = await member_service.mark_seen(
            profile_id, member_ids=data.member_ids, mark_all=data.all or False
        )
        if error:
            raise HTTPException(status_code=400, detail=error)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking notifications seen: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to mark notifications seen")


# ============================================================================
# List Invitations (Auth - Owner only)
# ============================================================================

@member_router.get("/{workspace_id}/invitations", response_model=InvitationListResponse)
async def list_invitations(
    workspace_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    profile_id: str = Depends(get_current_user)
):
    """
    List all invitations for a workspace (pending, revoked, expired).
    Owner only.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)

        result, error = await member_service.list_invitations(
            profile_id, workspace_id, page, page_size
        )

        if error:
            status_code = 403 if "owner" in error.lower() or "not a member" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing invitations: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to list invitations")


# ============================================================================
# Revoke Invitation (Auth - Owner only)
# ============================================================================

@member_router.delete("/{workspace_id}/invitations/{member_id}")
async def revoke_invitation(
    workspace_id: str,
    member_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Revoke a pending invitation. Sets status to 'revoked' and clears the token.
    Owner only. Can only revoke pending invitations.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        member_id = sanitize_user_input(member_id, strict=True)

        result, error = await member_service.revoke_invitation(
            profile_id, workspace_id, member_id
        )

        if error:
            status_code = 403 if "owner" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revoking invitation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to revoke invitation")


# ============================================================================
# Resend Invitation (Auth - Owner only)
# ============================================================================

@member_router.post("/{workspace_id}/invitations/{member_id}/resend")
async def resend_invitation(
    workspace_id: str,
    member_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Resend an invitation with a new token and extended expiry.
    Owner only. Works for pending or expired invitations.
    """
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        member_id = sanitize_user_input(member_id, strict=True)

        result, error = await member_service.resend_invitation(
            profile_id, workspace_id, member_id
        )

        if error:
            status_code = 403 if "owner" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resending invitation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to resend invitation")


# ============================================================================
# Accept Invitation (Public - token-based)
# ============================================================================

@public_invitation_router.post("/accept")
async def accept_invitation(
    data: AcceptInvitation,
    authorization: Optional[str] = Header(None)
):
    """
    Accept an invitation using the token from the email link.
    
    - **No auth required** to validate token (returns workspace info)
    - **With auth** (Bearer token): links the invitation to the logged-in user and activates membership
    
    Flow:
    1. Frontend opens `/accept-invitation?token=xxx`
    2. Calls this endpoint with `{ "token": "xxx" }`
    3. If user is logged in (sends Bearer token) → membership activated immediately
    4. If not logged in → returns workspace info + `requires_auth: true` → redirect to signup/login
    5. After login, frontend calls this again with Bearer token → activated
    """
    try:
        token = sanitize_user_input(data.token, strict=True)

        profile_id = None
        if authorization:
            try:
                auth_header = sanitize_user_input(authorization, strict=True) if authorization else ""
                profile_id = await auth_service.verify_login(auth_header)
            except Exception:
                pass

        result, error = await member_service.accept_invitation(token, profile_id)

        if error:
            if "expired" in error.lower():
                raise HTTPException(status_code=410, detail=error)
            if "invalid" in error.lower():
                raise HTTPException(status_code=404, detail=error)
            raise HTTPException(status_code=400, detail=error)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error accepting invitation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to accept invitation")


# ============================================================================
# Validate Invitation Token (Public - GET for frontend preflight)
# ============================================================================

@public_invitation_router.get("/validate")
async def validate_invitation(
    token: str = Query(..., description="Invitation token to validate")
):
    """
    Validate an invitation token without accepting it.
    Returns workspace info if token is valid. Used by frontend to show
    the accept-invitation page with workspace details.
    """
    try:
        token = sanitize_user_input(token, strict=True)

        result, error = await member_service.accept_invitation(token, profile_id=None)

        if error:
            if "expired" in error.lower():
                raise HTTPException(status_code=410, detail=error)
            if "invalid" in error.lower():
                raise HTTPException(status_code=404, detail=error)
            raise HTTPException(status_code=400, detail=error)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating invitation: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to validate invitation")
