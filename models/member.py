"""
Pydantic models for Team Management
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class MemberStatus(str, Enum):
    """Member status in workspace"""
    ACTIVE = "active"
    PENDING = "pending"
    INACTIVE = "inactive"
    REVOKED = "revoked"
    EXPIRED = "expired"


# ============================================================================
# Request Models
# ============================================================================

class InviteMember(BaseModel):
    """Model for inviting a new team member"""
    email: str = Field(..., description="Email address of the member to invite")
    name: Optional[str] = Field(None, description="Full name. Auto-resolved from profile or email if omitted")
    hierarchy_level: int = Field(default=1, ge=1, le=7, description="Hierarchy level (1-7)")
    designation: Optional[str] = Field(None, description="Job title/designation")
    department: Optional[str] = Field(None, description="Department name")
    employee_id: Optional[str] = Field(None, description="Employee ID")
    reports_to: Optional[str] = Field(None, description="Member ID of manager")
    feature_access: Optional[Dict[str, str]] = Field(None, description="Per-feature access: campaigns, tickets, help_desk. Values: none, viewer, editor")
    data: Dict[str, Any] = Field(default_factory=dict, description="Additional data")

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if not v or '@' not in v:
            raise ValueError('Valid email is required')
        return v.strip().lower()


class UpdateMember(BaseModel):
    """Model for updating a team member"""
    name: Optional[str] = Field(None, min_length=1, description="Full name")
    hierarchy_level: Optional[int] = Field(None, ge=1, le=7, description="Hierarchy level")
    designation: Optional[str] = Field(None, description="Job title")
    department: Optional[str] = Field(None, description="Department")
    employee_id: Optional[str] = Field(None, description="Employee ID")
    reports_to: Optional[str] = Field(None, description="Manager member ID")
    is_active: Optional[bool] = Field(None, description="Active status")
    feature_access: Optional[Dict[str, str]] = Field(None, description="Per-feature access: campaigns, tickets, help_desk. Values: none, viewer, editor")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional data")


# ============================================================================
# Response Models
# ============================================================================

class MemberResponse(BaseModel):
    """Model for member response"""
    id: str
    profile_id: Optional[str] = None
    workspace_id: str
    email: str
    name: str
    hierarchy_level: int
    level_name: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    employee_id: Optional[str] = None
    reports_to: Optional[str] = None
    reports_to_name: Optional[str] = None
    status: str = "active"
    is_owner: bool = False
    is_active: bool = True
    feature_access: Dict[str, str] = Field(default_factory=dict, description="Per-feature access: campaigns, tickets, help_desk")
    invited_by: Optional[str] = None
    invited_by_name: Optional[str] = None
    invited_at: Optional[datetime] = None
    delegations: List[Dict[str, Any]] = []
    data: Dict[str, Any] = {}
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MemberListResponse(BaseModel):
    """Model for listing members"""
    members: List[MemberResponse]
    total: int


class AcceptInvitation(BaseModel):
    """Model for accepting an invitation via token"""
    token: str = Field(..., description="Invitation token from email link")


class ResendInvitation(BaseModel):
    """Model for resending an invitation"""
    member_id: str = Field(..., description="Member ID of the pending invitation")


class InviteResponse(BaseModel):
    """Model for invite response"""
    id: str
    email: str
    name: str
    hierarchy_level: int
    level_name: Optional[str] = None
    status: str
    invitation_token: Optional[str] = None
    invitation_expires_at: Optional[datetime] = None
    message: str


class InvitationListItem(BaseModel):
    """Model for a single invitation in list response"""
    id: str
    email: str
    name: str
    hierarchy_level: int
    level_name: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    status: str
    is_expired: bool = False
    invited_by_name: Optional[str] = None
    invited_at: Optional[datetime] = None
    invitation_expires_at: Optional[datetime] = None
    feature_access: Dict[str, str] = Field(default_factory=dict)


class InvitationListResponse(BaseModel):
    """Model for listing invitations"""
    invitations: List[InvitationListItem]
    total: int


# ============================================================================
# Hierarchy Models
# ============================================================================

class HierarchyLevel(BaseModel):
    """Model for hierarchy level"""
    id: str
    workspace_id: str
    level: int
    level_name: str
    reports_to_level: Optional[int] = None
    data: Dict[str, Any] = {}
    created_at: datetime

    class Config:
        from_attributes = True


class HierarchyListResponse(BaseModel):
    """Model for listing hierarchy levels"""
    levels: List[HierarchyLevel]
    total: int


# ============================================================================
# Workspace Models
# ============================================================================

class WorkspaceInfo(BaseModel):
    """Model for workspace info in my-workspaces response"""
    id: str
    workspace_name: str
    is_owner: bool
    role: str  # Level name
    hierarchy_level: int
    member_id: Optional[str] = None  # None for workspaces owned via Workspaces.profile_id (backward compatibility)
    status: str
    feature_access: Dict[str, str] = Field(default_factory=dict, description="Per-feature access for this workspace")
    joined_at: Optional[datetime] = None
    invited_by_name: Optional[str] = None


class MyWorkspacesResponse(BaseModel):
    """Model for listing all workspaces (owned + shared)"""
    workspaces: List[WorkspaceInfo]
    total: int
    owned_count: int
    shared_count: int


# ============================================================================
# Notification Models
# ============================================================================

class NotificationItem(BaseModel):
    """A single workspace addition notification"""
    member_id: str
    workspace_id: str
    workspace_name: str
    invited_by_name: Optional[str] = None
    role: Optional[str] = None
    designation: Optional[str] = None
    added_at: Optional[datetime] = None


class NotificationListResponse(BaseModel):
    """Response for listing notifications"""
    notifications: List[NotificationItem]
    count: int


class MarkSeenRequest(BaseModel):
    """Request to mark notifications as seen"""
    member_ids: Optional[List[str]] = Field(None, description="Specific member_ids to mark seen")
    all: Optional[bool] = Field(False, description="Mark all unseen as seen")


# ============================================================================
# Error Models
# ============================================================================

class TeamAPIError(BaseModel):
    """Model for API error responses"""
    error: str
    details: Optional[str] = None
