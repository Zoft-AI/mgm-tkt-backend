"""
Request API Endpoints

This module contains all request/ticket-related endpoints.
Following the LLD architecture pattern for better code organization.
"""

import logging
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Header, Query, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse

from models.request import (
    RequestCreate, RequestUpdate, FinalizeRequest, RequestResponse, RequestListResponse,
    ApproveRequest, RejectRequest, EscalateRequest, ReassignRequest, ReviseBudgetRequest,
    MessageCreate, DashboardResponse, APIError,
    PublicRequestCreate, PublicFinalizeRequest, PublicRequestResponse, PublicStatusResponse, PublicTicketListResponse,
    ProductAdd, ProductUpdate, ProductBulkImport, ProductBulkDelete,
    RuleListResponse,
)
from services.auth import auth_service
from services.request_service import request_service
from utils.email_service import send_test_email
from utils.sanitize import sanitize_user_input

logger = logging.getLogger(__name__)

# Create routers for request endpoints
request_router = APIRouter(prefix="/requests", tags=["requests"])
public_request_router = APIRouter(prefix="/public/requests", tags=["public_requests"])


async def get_current_user(authorization: str = Header(...)) -> str:
    """Dependency to get current authenticated user"""
    authorization = sanitize_user_input(authorization, strict=True) if authorization else ""
    profile_id = await auth_service.verify_login(authorization)
    if not profile_id:
        raise HTTPException(status_code=401, detail="Login required")
    return profile_id


async def verify_cron_auth(
    authorization: Optional[str] = Header(None),
    x_sla_cron_secret: Optional[str] = Header(None, alias="X-SLA-Cron-Secret")
) -> None:
    """Verify cron caller: X-SLA-Cron-Secret OR Authorization: Bearer SERVICE_ROLE_KEY"""
    cron_secret = (os.environ.get("SLA_CRON_SECRET") or "").strip()
    service_role = (os.environ.get("SERVICE_ROLE_KEY") or "").strip()
    token = (authorization or "").replace("Bearer ", "").strip() if authorization else ""
    incoming_secret = (x_sla_cron_secret or "").strip()
    if incoming_secret and cron_secret and incoming_secret == cron_secret:
        return
    if token and service_role and token == service_role:
        return
    raise HTTPException(status_code=401, detail="Invalid cron auth")


# ============================================================================
# List/Get Endpoints
# ============================================================================

@request_router.get("/{agent_id}", response_model=RequestListResponse)
async def get_all_requests(
    agent_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_conversation: bool = Query(False, description="Include chatbot conversation history when data.conversation_id exists"),
    profile_id: str = Depends(get_current_user)
):
    """
    Get all requests for a chat agent.
    
    - **agent_id**: Chat Agent ID
    - **status**: Optional filter (pending, approved, rejected)
    - **page**: Page number (default: 1)
    - **page_size**: Items per page (default: 20, max: 100)
    - **include_conversation**: Include conversation_history for chatbot-originated requests
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        
        result, error = await request_service.get_all_requests(
            profile_id, agent_id, status, page, page_size, include_conversation
        )
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting requests: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get requests")


@request_router.get("/{agent_id}/admin/all", response_model=RequestListResponse)
async def get_admin_requests(
    agent_id: str,
    unit: Optional[str] = Query(None, description="Filter by unit code: HC | CI | Malar | SH"),
    payment_type: Optional[str] = Query(None, description="Filter by payment_type"),
    status: Optional[str] = Query(None, description="Filter by status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_conversation: bool = Query(False),
    profile_id: str = Depends(get_current_user)
):
    """
    Admin view of all requests for the agent.

    Permission: caller's `members.data.is_admin` must be true (e.g. MD).
    If the admin is unit-scoped (`members.unit_id` set), results are auto-restricted
    to that unit and a different `unit` query param will be rejected.

    - **unit**: HC | CI | Malar | SH
    - **payment_type**: DRT, Corporate Payouts, IPS, Events, Regular Payments, Implant Surgery, Patient Refund
    - **status**: pending | approved | rejected | draft
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        if unit:
            unit = sanitize_user_input(unit, strict=True)
        if payment_type:
            payment_type = sanitize_user_input(payment_type, strict=False)

        result, error = await request_service.get_admin_requests(
            profile_id, agent_id,
            unit=unit, payment_type=payment_type, status=status,
            page=page, page_size=page_size, include_conversation=include_conversation
        )
        if error:
            status_code = 403 if error.startswith("Forbidden") else 400
            raise HTTPException(status_code=status_code, detail=error)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting admin requests: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get admin requests")


@request_router.get("/{agent_id}/raised-by-me", response_model=RequestListResponse)
async def get_raised_by_me(
    agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_conversation: bool = Query(False, description="Include chatbot conversation history"),
    profile_id: str = Depends(get_current_user)
):
    """
    Get requests raised by the current user.
    
    - **agent_id**: Chat Agent ID
    - **include_conversation**: Include conversation_history for chatbot-originated requests
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        
        result, error = await request_service.get_raised_by_me(
            profile_id, agent_id, page, page_size, include_conversation
        )
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting raised-by-me: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get requests")


@request_router.get("/{agent_id}/acted-by-me", response_model=RequestListResponse)
async def get_acted_by_me(
    agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_conversation: bool = Query(True, description="Include chatbot conversation history (default True)"),
    profile_id: str = Depends(get_current_user)
):
    """
    Get requests where you approved, forwarded, or rejected.
    Shows both approved (pending with next person or fully approved) and rejected.
    Use this so approvers can see all requests they acted on after they leave raised-to-me.
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        result, error = await request_service.get_acted_by_me(
            profile_id, agent_id, page, page_size, include_conversation
        )
        if error:
            raise HTTPException(status_code=400, detail=error)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting acted-by-me: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get requests")


@request_router.get("/{agent_id}/raised-to-me", response_model=RequestListResponse)
async def get_raised_to_me(
    agent_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_conversation: bool = Query(False, description="Include chatbot conversation history"),
    profile_id: str = Depends(get_current_user)
):
    """
    Get requests assigned to the current user (pending action).
    
    - **agent_id**: Chat Agent ID
    - **include_conversation**: Include conversation_history for chatbot-originated requests
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        
        result, error = await request_service.get_raised_to_me(
            profile_id, agent_id, page, page_size, include_conversation
        )
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting raised-to-me: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get requests")


@request_router.get("/{agent_id}/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    agent_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Get dashboard with stats and recent requests.
    
    - **agent_id**: Chat Agent ID
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        
        result, error = await request_service.get_dashboard(profile_id, agent_id)
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dashboard: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get dashboard")


# Products must be before /{request_id} to avoid "products" being matched as request_id
@request_router.get("/{agent_id}/products")
async def get_products(
    agent_id: str,
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search by name or alias"),
    profile_id: str = Depends(get_current_user)
):
    """Get products list. Optional ?category=IT&search=laptop. Auth required."""
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        result, error = await request_service.get_products_for_agent(profile_id, agent_id, category=category, search=search)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"products": result or []}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting products: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get products")


@request_router.get("/{agent_id}/products/categories")
async def get_product_categories(
    agent_id: str,
    profile_id: str = Depends(get_current_user)
):
    """Get distinct product categories. Auth required."""
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        result, error = await request_service.get_product_categories(profile_id, agent_id)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"categories": result or []}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting categories: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get categories")


@request_router.get("/{agent_id}/rules", response_model=RuleListResponse)
async def get_rules(
    agent_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Get all active rules for a chat agent.
    
    - **agent_id**: Chat Agent ID
    
    Returns rules that can be used when creating requests (rule picker).
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        result, error = await request_service.get_rules(profile_id, agent_id)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting rules: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get rules")


@request_router.get("/{agent_id}/{request_id}", response_model=RequestResponse)
async def get_request(
    agent_id: str,
    request_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Get a single request by ID.
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)
        
        result, error = await request_service.get_request(profile_id, agent_id, request_id)
        
        if error:
            raise HTTPException(status_code=404 if "not found" in error.lower() else 400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting request: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get request")


# ============================================================================
# Products Endpoint (for product-based purchase flow)
# ============================================================================

@request_router.post("/{agent_id}/products")
async def add_product(
    agent_id: str,
    data: ProductAdd,
    profile_id: str = Depends(get_current_user)
):
    """
    Add product to Purchase rule. Auto-increments id (p5, p6...).
    Auth required.
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        result, error = await request_service.add_product(
            profile_id, agent_id,
            name=data.name,
            cost=data.cost,
            aliases=data.aliases,
            category=data.category,
            fields=[f.model_dump() for f in data.fields] if data.fields else None,
        )
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"product": result, "message": f"Product {result.get('id')} added"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding product: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add product")


@request_router.put("/{agent_id}/products/{product_id}")
async def update_product(
    agent_id: str,
    product_id: str,
    data: ProductUpdate,
    profile_id: str = Depends(get_current_user)
):
    """Update a product. Auth required."""
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        product_id = sanitize_user_input(product_id, strict=True)
        result, error = await request_service.update_product(
            profile_id, agent_id, product_id,
            name=data.name, cost=data.cost, aliases=data.aliases,
            category=data.category,
            fields=[f.model_dump() for f in data.fields] if data.fields else None,
        )
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"product": result, "message": "Product updated"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating product: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update product")


@request_router.post("/{agent_id}/products/bulk")
async def bulk_import_products(
    agent_id: str,
    data: ProductBulkImport,
    profile_id: str = Depends(get_current_user)
):
    """Bulk import products from JSON array. Auth required."""
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        products_dicts = []
        for p in data.products:
            d = {"name": p.name, "cost": p.cost, "aliases": p.aliases or [p.name.lower()], "category": p.category or "General"}
            if p.fields:
                d["fields"] = [f.model_dump() for f in p.fields]
            products_dicts.append(d)
        count, error = await request_service.bulk_import_products(profile_id, agent_id, products_dicts)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"success": True, "imported_count": count, "message": f"{count} product(s) imported"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error bulk importing products: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to bulk import products")


@request_router.delete("/{agent_id}/products")
async def remove_products(
    agent_id: str,
    data: ProductBulkDelete,
    profile_id: str = Depends(get_current_user)
):
    """Remove product(s) by ids. Body: {"product_ids": ["uuid1", "uuid2"]}. Auth required."""
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        count, error = await request_service.remove_products_bulk(profile_id, agent_id, data.product_ids)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"success": True, "removed_count": count, "message": f"{count} product(s) removed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing products: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to remove products")


@public_request_router.get("/{agent_id}/products/categories")
async def public_get_product_categories(agent_id: str):
    """Get distinct product categories (NO AUTH - for chatbot). Agent asks user to pick category first."""
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        result, error = await request_service.get_product_categories_public(agent_id)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"categories": result or []}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting categories: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get categories")


@public_request_router.get("/{agent_id}/products")
async def public_get_products(
    agent_id: str,
    category: Optional[str] = Query(None, description="Filter by category"),
    search: Optional[str] = Query(None, description="Search by name or alias"),
):
    """Get products list (NO AUTH - for chatbot). Optional ?category=IT&search=laptop."""
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        result, error = await request_service.get_products_for_agent_public(agent_id, category=category, search=search)
        if error:
            raise HTTPException(status_code=400, detail=error)
        return {"products": result or []}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting products: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get products")


# ============================================================================
# Create Endpoint
# ============================================================================

@request_router.post("/{agent_id}", response_model=RequestResponse)
async def create_request(
    agent_id: str,
    request_data: RequestCreate,
    profile_id: str = Depends(get_current_user)
):
    """
    Create a new request/ticket.
    
    - **agent_id**: Chat Agent ID
    - **request_data**: Request details
    
    Auto-routing:
    - If `rule_id` is provided, routes based on rule configuration
    - If `raised_to` is provided, assigns directly to that member
    - Otherwise, routes to the requester's direct manager
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        
        result, error = await request_service.create_request(profile_id, agent_id, request_data)
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating request: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create request")


@request_router.post("/{agent_id}/{request_id}/finalize", response_model=RequestResponse)
async def finalize_request(
    agent_id: str,
    request_id: str,
    finalize_data: FinalizeRequest,
    profile_id: str = Depends(get_current_user)
):
    """
    Finalize a draft request after AI spec collection (Phase 2).
    Merges specifications into data, builds approval chain, flips status draft→pending,
    and sends notifications.
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Draft request ID from Phase 1
    - **finalize_data**: Collected specs and optional conversation_id
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)
        
        result, error = await request_service.finalize_request(
            profile_id, agent_id, request_id, finalize_data
        )
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error finalizing request: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to finalize request")


# ============================================================================
# Action Endpoints
# ============================================================================

@request_router.post("/{agent_id}/{request_id}/approve", response_model=RequestResponse)
async def approve_request(
    agent_id: str,
    request_id: str,
    comment: Optional[str] = Form(None),
    files: Optional[List[UploadFile]] = File(None),
    profile_id: str = Depends(get_current_user)
):
    """
    Approve a request. Accepts multipart/form-data with optional file uploads.
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    - **comment**: Optional approval comment (form field)
    - **files**: Optional file attachments (multipart, multiple allowed)
    
    Only the current approver (or their delegate) can approve.
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)

        data = ApproveRequest(comment=comment)

        file_data_list = None
        if files:
            file_data_list = []
            for f in files:
                content = await f.read()
                file_data_list.append({
                    "file_content": content,
                    "file_name": f.filename or "attachment",
                    "file_size": len(content),
                    "content_type": f.content_type or "application/octet-stream"
                })

        result, error = await request_service.approve_request(
            profile_id, agent_id, request_id, data, file_data_list
        )
        
        if error:
            status_code = 403 if "not authorized" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving request: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to approve request")


@request_router.post("/{agent_id}/{request_id}/revise-budget", response_model=RequestResponse)
async def revise_budget(
    agent_id: str,
    request_id: str,
    data: ReviseBudgetRequest,
    profile_id: str = Depends(get_current_user)
):
    """
    Revise the budget/amount of a request. Only procurement (receives_only) members can do this.
    Recalculates approval chain for amount_based rules and forwards to next approver.
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    - **data**: Revised amount and optional reason
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)

        result, error = await request_service.revise_budget(
            profile_id, agent_id, request_id,
            data.revised_amount, data.reason
        )

        if error:
            status_code = 403 if "not authorized" in error.lower() or "not the current" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error revising budget: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to revise budget")


@request_router.post("/{agent_id}/{request_id}/reject", response_model=RequestResponse)
async def reject_request(
    agent_id: str,
    request_id: str,
    reason: str = Form(...),
    files: Optional[List[UploadFile]] = File(None),
    profile_id: str = Depends(get_current_user)
):
    """
    Reject a request. Accepts multipart/form-data with optional file uploads.
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    - **reason**: Required rejection reason (form field)
    - **files**: Optional file attachments (multipart, multiple allowed)
    
    Only the current approver (or their delegate) can reject.
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)

        data = RejectRequest(reason=reason)

        file_data_list = None
        if files:
            file_data_list = []
            for f in files:
                content = await f.read()
                file_data_list.append({
                    "file_content": content,
                    "file_name": f.filename or "attachment",
                    "file_size": len(content),
                    "content_type": f.content_type or "application/octet-stream"
                })

        result, error = await request_service.reject_request(
            profile_id, agent_id, request_id, data, file_data_list
        )
        
        if error:
            status_code = 403 if "not authorized" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rejecting request: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to reject request")


@request_router.post("/{agent_id}/{request_id}/escalate", response_model=RequestResponse)
async def escalate_request(
    agent_id: str,
    request_id: str,
    reason: Optional[str] = Form(None),
    is_emergency: bool = Form(False),
    files: Optional[List[UploadFile]] = File(None),
    profile_id: str = Depends(get_current_user)
):
    """
    Escalate a request to the next hierarchy level. Accepts multipart/form-data with optional file uploads.
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    - **reason**: Optional escalation reason (form field)
    - **is_emergency**: Mark as emergency escalation (form field, default false)
    - **files**: Optional file attachments (multipart, multiple allowed)
    
    Emergency escalations can skip levels (requires Level 3+).
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)

        data = EscalateRequest(reason=reason, is_emergency=is_emergency)

        file_data_list = None
        if files:
            file_data_list = []
            for f in files:
                content = await f.read()
                file_data_list.append({
                    "file_content": content,
                    "file_name": f.filename or "attachment",
                    "file_size": len(content),
                    "content_type": f.content_type or "application/octet-stream"
                })

        result, error = await request_service.escalate_request(
            profile_id, agent_id, request_id, data, file_data_list
        )
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error escalating request: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to escalate request")


@request_router.post("/{agent_id}/{request_id}/message", response_model=RequestResponse)
async def add_message(
    agent_id: str,
    request_id: str,
    message: str = Form(...),
    files: Optional[List[UploadFile]] = File(None),
    profile_id: str = Depends(get_current_user)
):
    """
    Add a comment/message to a request. Accepts multipart/form-data with optional file uploads.
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    - **message**: Message content (form field, required)
    - **files**: Optional file attachments (multipart, multiple allowed)
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)

        file_data_list = None
        if files:
            file_data_list = []
            for f in files:
                content = await f.read()
                file_data_list.append({
                    "file_content": content,
                    "file_name": f.filename or "attachment",
                    "file_size": len(content),
                    "content_type": f.content_type or "application/octet-stream"
                })

        result, error = await request_service.add_message(
            profile_id, agent_id, request_id,
            message, file_data_list=file_data_list
        )
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding message: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add message")


@request_router.post("/{agent_id}/upload-temp")
async def upload_temp(
    agent_id: str,
    files: List[UploadFile] = File(...),
    profile_id: str = Depends(get_current_user)
):
    """
    Upload file(s) to temp storage before creating a request (AUTH REQUIRED).
    Returns attachment metadata to pass in the create request payload.

    - **agent_id**: Chat Agent ID
    - **files**: Files to upload (multipart/form-data, multiple allowed)
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)

        file_data_list = []
        for f in files:
            content = await f.read()
            file_data_list.append({
                "file_content": content,
                "file_name": f.filename or "attachment",
                "file_size": len(content),
                "content_type": f.content_type or "application/octet-stream"
            })

        results, error = await request_service.upload_temp_attachment(
            profile_id, agent_id, file_data_list
        )

        if error:
            raise HTTPException(status_code=400, detail=error)

        names = ", ".join(fd["file_name"] for fd in file_data_list)
        return {"attachments": results, "message": f"Uploaded: {names}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading temp attachment: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upload temp attachment")


@request_router.post("/{agent_id}/{request_id}/upload-attachment")
async def upload_attachment(
    agent_id: str,
    request_id: str,
    files: List[UploadFile] = File(...),
    profile_id: str = Depends(get_current_user)
):
    """
    Upload one or more file attachments to a request/ticket.
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    - **files**: Files to upload (multipart/form-data, multiple allowed)
    
    Uploads to Supabase storage, appends to request.attachments, adds audit message.
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)

        file_data_list = []
        for f in files:
            content = await f.read()
            file_data_list.append({
                "file_content": content,
                "file_name": f.filename or "attachment",
                "file_size": len(content),
                "content_type": f.content_type or "application/octet-stream"
            })

        results, error = await request_service.upload_attachment(
            profile_id, agent_id, request_id, file_data_list
        )

        if error:
            raise HTTPException(status_code=400, detail=error)

        names = ", ".join(fd["file_name"] for fd in file_data_list)
        return {"attachments": results, "message": f"Uploaded: {names}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading attachment: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upload attachment")


@request_router.delete("/{agent_id}/{request_id}/delete-attachment/{attachment_id}")
async def delete_attachment(
    agent_id: str,
    request_id: str,
    attachment_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Delete a single attachment from a request. Only the person who uploaded the file can delete it.

    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    - **attachment_id**: Attachment ID (e.g. att_xxxxxxxxxxxx)
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)
        attachment_id = sanitize_user_input(attachment_id, strict=True)

        result, error = await request_service.delete_attachment(
            profile_id, agent_id, request_id, attachment_id
        )

        if error:
            status_code = 403 if "only delete" in error.lower() else 400
            raise HTTPException(status_code=status_code, detail=error)

        return {"success": True, "deleted": result, "message": f"Attachment '{result.get('name')}' deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting attachment: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete attachment")


@request_router.get("/{agent_id}/{request_id}/attachment/{attachment_id}/url")
async def refresh_attachment_url(
    agent_id: str,
    request_id: str,
    attachment_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Get a fresh presigned download URL for an attachment.

    Presigned URLs expire after 1 hour. Call this endpoint to obtain a new one
    using the stored S3 key (attachments uploaded after the S3 migration include
    an ``s3_key`` field).

    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    - **attachment_id**: Attachment ID (e.g. att_xxxxxxxxxxxx)
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)
        attachment_id = sanitize_user_input(attachment_id, strict=True)

        result, error = await request_service.refresh_attachment_url(
            profile_id, agent_id, request_id, attachment_id
        )

        if error:
            raise HTTPException(
                status_code=404 if "not found" in error.lower() else 400,
                detail=error,
            )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing attachment URL: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to refresh attachment URL")


@request_router.post("/{agent_id}/process-sla")
async def process_sla_auto_approvals(
    agent_id: str,
    profile_id: str = Depends(get_current_user)
):
    """
    Process SLA for one agent: skip intermediate approvers, mark final as breached.
    Call via cron. Requires auth.
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        count, error = await request_service.process_sla_auto_approvals(agent_id)
        if error:
            raise HTTPException(status_code=500, detail=error)
        return {"processed_count": count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing SLA: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process SLA")


@request_router.post("/process-sla-all")
async def process_sla_auto_approvals_all(
    profile_id: str = Depends(get_current_user)
):
    """
    Process SLA for ALL agents with overdue requests. Use this for cron.
    Requires auth.
    """
    try:
        count, error = await request_service.process_sla_auto_approvals_all()
        if error:
            raise HTTPException(status_code=500, detail=error)
        return {"processed_count": count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing SLA: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process SLA")


# ============================================================================
# Public Endpoints (No Auth - For Chatbot)
# ============================================================================

@public_request_router.get("/test-email")
async def test_email(to: Optional[str] = Query(None, description="Recipient email (default: REQUEST_EMAIL_TEST_RECIPIENT)")):
    """Send a dummy test email to verify SMTP config. No auth required."""
    success, msg = await send_test_email(to)
    if not success:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@public_request_router.post("/process-sla-all")
async def public_process_sla_all(_: None = Depends(verify_cron_auth)):
    """
    Process SLA for all agents. For cron jobs.
    Auth: X-SLA-Cron-Secret header OR Authorization: Bearer SERVICE_ROLE_KEY.
    """
    try:
        count, error = await request_service.process_sla_auto_approvals_all()
        if error:
            raise HTTPException(status_code=500, detail=error)
        return {"processed_count": count}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing SLA: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process SLA")


@public_request_router.post("/{agent_id}/{request_id}/finalize")
async def public_finalize_request(
    agent_id: str,
    request_id: str,
    finalize_data: PublicFinalizeRequest
):
    """
    Finalize a draft request from chatbot/agent tool calling (NO AUTH REQUIRED).
    Merges specifications, builds approval chain, flips draft→pending.
    
    User identified by email OR profile_id (at least one required).
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Draft request ID from Phase 1
    - **email**: User's email for identification
    - **profile_id**: User's profile ID (alternative to email)
    - **specifications**: Collected specs from AI chat
    - **conversation_id**: Chat conversation ID for linking
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)
        
        result, error = await request_service.public_finalize_request(
            agent_id=agent_id,
            request_id=request_id,
            email=finalize_data.email,
            profile_id=finalize_data.profile_id,
            specifications=finalize_data.specifications,
            conversation_id=finalize_data.conversation_id
        )
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in public finalize: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to finalize request")


@public_request_router.post("/{agent_id}/create", response_model=PublicRequestResponse)
async def public_create_request(
    agent_id: str,
    request_data: PublicRequestCreate
):
    """
    Create a new request/ticket from chatbot (NO AUTH REQUIRED).
    
    User identified by email OR profile_id (at least one required).
    
    - **agent_id**: Chat Agent ID
    - **email**: User's email (use when profile_id not available)
    - **profile_id**: User's profile ID (profiles.id) - alternative to email
    - **name**: User's name (optional when profile_id provided)
    - **phone**: User's phone (optional)
    - **subject**: Request subject
    - **description**: Request description
    - **request_type**: support, approval, query, complaint
    - **priority**: low, normal, high, urgent
    - **conversation_id**: Chatbot conversation ID (for "View Conversation" link)
    - **data**: Additional data (amount, vendor, etc.)
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        
        result, error = await request_service.public_create_request(
            agent_id=agent_id,
            email=request_data.email,
            profile_id=request_data.profile_id,
            name=request_data.name,
            phone=request_data.phone,
            subject=request_data.subject,
            description=request_data.description,
            request_type=request_data.request_type.value,
            category=request_data.category,
            priority=request_data.priority.value,
            quantity=request_data.quantity,
            conversation_id=request_data.conversation_id,
            data=request_data.data
        )
        
        if error:
            # Level restrictions → 403 Forbidden
            if "don't have the access" in error.lower() or "reach out to your manager" in error.lower() or "contact manager" in error.lower():
                raise HTTPException(status_code=403, detail=error)
            # Member not found → 404
            if "member not found" in error.lower():
                raise HTTPException(status_code=404, detail=error)
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in public create request: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create request")


@public_request_router.post("/{agent_id}/{request_id}/upload-attachment")
async def public_upload_attachment(
    agent_id: str,
    request_id: str,
    files: List[UploadFile] = File(...),
    email: Optional[str] = Form(None),
    profile_id: Optional[str] = Form(None),
):
    """
    Upload one or more file attachments to a request (NO AUTH - for chatbot/requester).
    
    - **agent_id**: Chat Agent ID
    - **request_id**: Request ID
    - **files**: Files to upload (multipart/form-data, multiple allowed)
    - **email**: User's email (form field)
    - **profile_id**: User's profile_id (form field, alternative to email)
    
    At least one of email or profile_id is required.
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_id = sanitize_user_input(request_id, strict=True)

        if not email and not profile_id:
            raise HTTPException(status_code=400, detail="Either email or profile_id is required")

        file_data_list = []
        for f in files:
            content = await f.read()
            file_data_list.append({
                "file_content": content,
                "file_name": f.filename or "attachment",
                "file_size": len(content),
                "content_type": f.content_type or "application/octet-stream"
            })

        results, error = await request_service.public_upload_attachment(
            agent_id, request_id,
            email=email, profile_id=profile_id,
            file_data_list=file_data_list
        )

        if error:
            raise HTTPException(status_code=400, detail=error)

        names = ", ".join(fd["file_name"] for fd in file_data_list)
        return {"attachments": results, "message": f"Uploaded: {names}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in public upload attachment: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to upload attachment")


@public_request_router.get("/{agent_id}/status/{request_number}", response_model=PublicStatusResponse)
async def public_get_status(
    agent_id: str,
    request_number: str
):
    """
    Check ticket status by request number (NO AUTH REQUIRED).
    
    - **agent_id**: Chat Agent ID
    - **request_number**: Request number (e.g., REQ-2026-00001)
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        request_number = sanitize_user_input(request_number, strict=True)
        
        result, error = await request_service.public_get_status(agent_id, request_number)
        
        if error:
            raise HTTPException(
                status_code=404 if "not found" in error.lower() else 400, 
                detail=error
            )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in public get status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get status")


@public_request_router.get("/{agent_id}/my-tickets", response_model=PublicTicketListResponse)
async def public_get_my_tickets(
    agent_id: str,
    email: str = Query(..., description="User's email to lookup tickets"),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50)
):
    """
    Get user's tickets by email (NO AUTH REQUIRED).
    
    - **agent_id**: Chat Agent ID
    - **email**: User's email to lookup tickets
    - **page**: Page number
    - **page_size**: Items per page (max 50)
    """
    try:
        agent_id = sanitize_user_input(agent_id, strict=True)
        email = sanitize_user_input(email, strict=True)
        
        result, error = await request_service.public_get_my_tickets(
            agent_id, email, page, page_size
        )
        
        if error:
            raise HTTPException(status_code=400, detail=error)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in public get my tickets: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get tickets")
