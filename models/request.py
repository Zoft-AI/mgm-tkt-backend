"""
Request Pydantic Models

This module contains all Pydantic models for request/ticket operations.
Following the LLD architecture pattern for proper data validation and serialization.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class RequestStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class RequestType(str, Enum):
    SUPPORT = "support"
    APPROVAL = "approval"
    QUERY = "query"
    COMPLAINT = "complaint"


class Priority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


# ============================================================================
# Message Models (for embedded JSONB)
# ============================================================================

class MessageCreate(BaseModel):
    """Model for creating a new message"""
    message: str = Field(..., min_length=1, description="Message content")
    action: str = Field(default="comment", description="Action type: comment, approved, rejected, etc.")
    attachments: List[Dict[str, Any]] = Field(default_factory=list)


class MessageResponse(BaseModel):
    """Model for message in response"""
    id: str
    sender_id: str
    sender_name: str
    message: str
    action: str
    attachments: List[Dict[str, Any]] = []
    created_at: datetime


# ============================================================================
# History Models (for embedded JSONB)
# ============================================================================

class HistoryEntry(BaseModel):
    """Model for history entry"""
    action: str
    by_id: Optional[str] = None
    by_name: Optional[str] = None
    to_id: Optional[str] = None
    to_name: Optional[str] = None
    from_status: Optional[str] = Field(None, alias="from")
    to_status: Optional[str] = Field(None, alias="to")
    reason: Optional[str] = None
    comment: Optional[str] = None
    at: datetime

    class Config:
        populate_by_name = True


# ============================================================================
# Request Models
# ============================================================================

class RequestCreate(BaseModel):
    """Model for creating a new request"""
    subject: Optional[str] = Field(None, max_length=500, description="Request subject (auto-generated as 'Request for {product_name} ({quantity})' when product_id provided)")
    description: Optional[str] = Field(None, description="Request description")
    request_type: RequestType = Field(default=RequestType.SUPPORT)
    category: Optional[str] = Field(None, description="Request category")
    priority: Priority = Field(default=Priority.NORMAL)
    quantity: Optional[int] = Field(None, ge=1, description="Quantity of product requested (also stored in data)")
    data: Dict[str, Any] = Field(default_factory=dict, description="Request-specific data (amount, etc.)")
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    rule_id: Optional[str] = Field(None, description="Rule ID for auto-routing")
    rule_name: Optional[str] = Field(None, description="Rule name for auto-routing (alternative to rule_id)")
    raised_to: Optional[str] = Field(None, description="Member ID to assign to")
    sla_auto_approve: bool = Field(True, description="If True, auto-approve when sla_deadline passes")
    is_draft: bool = Field(False, description="If True, creates as draft (Phase 1 of CapEx flow). Finalize via /finalize endpoint after AI spec collection.")

    @field_validator('subject')
    @classmethod
    def validate_subject(cls, v):
        if v is not None:
            return v.strip()
        return v


class FinalizeRequest(BaseModel):
    """Model for finalizing a draft request after AI spec collection (Phase 2)"""
    specifications: Dict[str, Any] = Field(default_factory=dict, description="Collected specs from AI chat (merged into data.specifications)")
    conversation_id: Optional[str] = Field(None, description="Chat conversation ID for linking")


class RequestUpdate(BaseModel):
    """Model for updating a request"""
    subject: Optional[str] = Field(None, max_length=500)
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[Priority] = None
    data: Optional[Dict[str, Any]] = None
    attachments: Optional[List[Dict[str, Any]]] = None


class ProductField(BaseModel):
    """A dynamic field definition for product-specific specs collection"""
    key: str = Field(..., min_length=1, description="Field key (e.g. ram, storage)")
    description: str = Field(..., min_length=1, description="Human-readable prompt for this field")
    required: bool = Field(default=False, description="Whether this field is mandatory")


class ProductAdd(BaseModel):
    """Model for adding a product to Purchase rule"""
    name: str = Field(..., min_length=1, description="Product name")
    cost: float = Field(..., gt=0, description="Product cost")
    aliases: Optional[List[str]] = Field(None, description="Search aliases (e.g. laptop, notebook)")
    category: Optional[str] = Field(None, description="Product category")
    fields: Optional[List[ProductField]] = Field(None, description="Product-specific spec fields for dynamic collection")


class ProductUpdate(BaseModel):
    """Model for updating a product"""
    name: Optional[str] = Field(None, min_length=1, description="Product name")
    cost: Optional[float] = Field(None, gt=0, description="Product cost")
    aliases: Optional[List[str]] = Field(None, description="Search aliases")
    category: Optional[str] = Field(None, description="Product category")
    fields: Optional[List[ProductField]] = Field(None, description="Product-specific spec fields")


class ProductBulkImport(BaseModel):
    """Model for bulk importing products"""
    products: List[ProductAdd] = Field(..., min_length=1, description="List of products to import")


class ProductBulkDelete(BaseModel):
    """Model for bulk deleting products"""
    product_ids: List[str] = Field(..., min_length=1, description="List of product ids to remove")


class RequestResponse(BaseModel):
    """Model for request response"""
    id: str
    request_number: Optional[str] = None
    workspace_id: str
    chat_agent_id: str
    rule_id: Optional[str] = None
    
    # WHO
    raised_by: str
    raised_by_name: Optional[str] = None
    raised_by_department: Optional[str] = None
    raised_to: Optional[str] = None
    raised_to_name: Optional[str] = None
    current_approver: Optional[str] = None
    current_approver_name: Optional[str] = None
    approval_chain: List[Dict[str, Any]] = []  # [{id, name}] reporting managers chain for tags
    
    # WHAT
    subject: str
    description: Optional[str] = None
    request_type: str
    category: Optional[str] = None
    priority: str
    data: Dict[str, Any] = {}
    attachments: List[Dict[str, Any]] = []
    
    # STATUS
    status: str
    current_level: Optional[int] = None
    required_level: Optional[int] = None
    
    # MESSAGES & HISTORY
    messages: List[Dict[str, Any]] = []
    history: List[Dict[str, Any]] = []
    conversation_history: Optional[List[Dict[str, Any]]] = None  # Chatbot messages when conversation_id in data
    action_timeline: List[Dict[str, Any]] = []  # List of approved/rejected with by_name, at, comment/reason
    last_action_message: Optional[str] = None  # e.g. "Karthik approved. Pending Krishan."
    
    # ESCALATION
    escalation_chain: List[Dict[str, Any]] = []
    is_emergency: bool = False
    emergency_reason: Optional[str] = None
    
    # OVERRIDE
    is_overridden: bool = False
    overridden_by: Optional[str] = None
    override_reason: Optional[str] = None
    
    # DELEGATION
    approved_by_delegate: bool = False
    original_approver: Optional[str] = None
    
    # SLA
    sla_deadline: Optional[datetime] = None
    is_sla_breached: bool = False
    sla_auto_approve: bool = True
    auto_approved: bool = False
    
    # TIMESTAMPS
    created_at: datetime
    updated_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RequestListResponse(BaseModel):
    """Model for request list response"""
    requests: List[RequestResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ============================================================================
# Action Models
# ============================================================================

class ApproveRequest(BaseModel):
    """Model for approving a request"""
    comment: Optional[str] = Field(None, description="Approval comment")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="File attachments (pre-uploaded via /upload-attachment)")


class RejectRequest(BaseModel):
    """Model for rejecting a request"""
    reason: str = Field(..., min_length=1, description="Rejection reason")
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="File attachments (pre-uploaded via /upload-attachment)")


class ReviseBudgetRequest(BaseModel):
    """Model for procurement revising the budget/amount of a request"""
    revised_amount: float = Field(..., gt=0, description="New revised amount")
    reason: Optional[str] = Field(None, description="Reason for budget revision")


class EscalateRequest(BaseModel):
    """Model for escalating a request"""
    reason: Optional[str] = Field(None, description="Escalation reason")
    is_emergency: bool = Field(default=False)
    attachments: List[Dict[str, Any]] = Field(default_factory=list, description="File attachments (pre-uploaded via /upload-attachment)")


class ReassignRequest(BaseModel):
    """Model for reassigning a request"""
    new_approver_id: str = Field(..., description="New approver member ID")
    reason: Optional[str] = Field(None)


# ============================================================================
# Member Models
# ============================================================================

class MemberResponse(BaseModel):
    """Model for member response"""
    id: str
    profile_id: str
    workspace_id: str
    name: Optional[str] = None
    email: Optional[str] = None
    employee_id: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    hierarchy_level: Optional[int] = None
    reports_to: Optional[str] = None
    delegations: List[Dict[str, Any]] = []
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MemberCreate(BaseModel):
    """Model for creating a member"""
    name: str = Field(..., min_length=1)
    email: Optional[str] = None
    employee_id: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    hierarchy_level: Optional[int] = None
    reports_to: Optional[str] = None


# ============================================================================
# Hierarchy Models
# ============================================================================

class HierarchyResponse(BaseModel):
    """Model for hierarchy response"""
    id: str
    workspace_id: str
    level: int
    level_name: str
    reports_to_level: Optional[int] = None
    data: Dict[str, Any] = {}
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ============================================================================
# Rule Models
# ============================================================================

class RuleResponse(BaseModel):
    """Model for rule response"""
    id: str
    workspace_id: str
    chat_agent_id: Optional[str] = None
    rule_name: str
    rule_type: str
    category: Optional[str] = None
    data: Dict[str, Any] = {}
    is_active: bool = True
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RuleListResponse(BaseModel):
    """Model for listing rules"""
    rules: List[RuleResponse] = []
    total: int = 0


# ============================================================================
# Dashboard/Stats Models
# ============================================================================

class RequestStats(BaseModel):
    """Model for request statistics"""
    total: int = 0
    pending: int = 0
    approved: int = 0
    rejected: int = 0
    sla_breached: int = 0


class MyRequestStats(BaseModel):
    """Stats for requests raised by me"""
    total: int = 0
    pending: int = 0
    approved: int = 0
    rejected: int = 0


class MyApprovalStats(BaseModel):
    """Stats for requests I approved/rejected or pending for my approval"""
    total: int = 0
    pending: int = 0
    approved: int = 0
    rejected: int = 0


class DashboardResponse(BaseModel):
    """Model for dashboard response"""
    stats: RequestStats
    my_requests: MyRequestStats
    my_approvals: MyApprovalStats
    recent_requests: List[RequestResponse] = []


# ============================================================================
# Public Request Models (No Auth - For Chatbot)
# ============================================================================

class PublicRequestCreate(BaseModel):
    """Model for creating request via chatbot (no auth). Provide email OR profile_id."""
    email: Optional[str] = Field(None, description="User's email for identification")
    profile_id: Optional[str] = Field(None, description="User's profile ID (profiles.id) for identification")
    name: Optional[str] = Field(None, description="User's name (optional when profile_id provided)")
    phone: Optional[str] = Field(None, description="User's phone number")
    subject: Optional[str] = Field(None, max_length=500, description="Request subject (auto-generated as 'Request for {product_name} ({quantity})' when product_id provided)")
    description: Optional[str] = Field(None, description="Request description")
    request_type: RequestType = Field(default=RequestType.SUPPORT)
    category: Optional[str] = Field(None, description="Request category")
    priority: Priority = Field(default=Priority.NORMAL)
    quantity: Optional[int] = Field(None, ge=1, description="Quantity of product requested (also stored in data)")
    conversation_id: Optional[str] = Field(None, description="Chatbot conversation ID for linking")
    data: Dict[str, Any] = Field(default_factory=dict, description="Additional data")

    @field_validator('email')
    @classmethod
    def validate_email(cls, v):
        if v is not None and v:
            if '@' not in v:
                raise ValueError('Valid email format required')
            return v.strip().lower()
        return v

    @field_validator('subject')
    @classmethod
    def validate_subject(cls, v):
        if v is not None:
            return v.strip()
        return v

    @model_validator(mode='after')
    def validate_email_or_profile_id(self):
        if not self.email and not self.profile_id:
            raise ValueError('Either email or profile_id is required')
        return self


class PublicFinalizeRequest(BaseModel):
    """Model for public finalize (no auth) — used by chat agent tool calling"""
    email: Optional[str] = Field(None, description="User's email for identification")
    profile_id: Optional[str] = Field(None, description="User's profile ID (profiles.id)")
    specifications: Dict[str, Any] = Field(default_factory=dict, description="Collected specs from AI chat")
    conversation_id: Optional[str] = Field(None, description="Chat conversation ID for linking")

    @model_validator(mode='after')
    def validate_email_or_profile_id(self):
        if not self.email and not self.profile_id:
            raise ValueError('Either email or profile_id is required')
        return self


class PublicRequestResponse(BaseModel):
    """Simplified response for public endpoints"""
    id: str
    request_number: Optional[str] = None
    subject: str
    status: str
    priority: str
    created_at: datetime
    message: str = Field(default="Request created successfully")
    current_approver_name: Optional[str] = None
    raised_by_name: Optional[str] = None
    raised_by_department: Optional[str] = None


class PublicStatusResponse(BaseModel):
    """Response for ticket status check"""
    request_number: str
    subject: str
    status: str
    priority: str
    current_approver_name: Optional[str] = None
    raised_by_name: Optional[str] = None
    raised_by_department: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_message: Optional[str] = None


class PublicTicketListResponse(BaseModel):
    """Response for listing user's tickets"""
    tickets: List[PublicStatusResponse]
    total: int


# ============================================================================
# Error Models
# ============================================================================

class APIError(BaseModel):
    """Model for API error responses"""
    error: str
    details: Optional[str] = None
