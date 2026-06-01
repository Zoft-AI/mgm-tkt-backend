"""
Request Service Layer

This module contains all business logic for request/ticket operations.
Following the LLD architecture pattern for proper separation of concerns.
"""

import asyncio
import json
import logging
import os
import uuid
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timedelta, timezone

from models.request import (
    RequestCreate, RequestUpdate, FinalizeRequest, RequestResponse, RequestListResponse,
    ApproveRequest, RejectRequest, EscalateRequest, ReassignRequest,
    MemberResponse, HierarchyResponse, RuleResponse, RequestStats,
    MyRequestStats, MyApprovalStats, DashboardResponse
)
from db.request_repository import RequestRepository
from utils.feature_access import can_view, can_edit
from utils.storage_operations import upload_ticket_attachment, delete_ticket_attachment, upload_temp_ticket_attachment, move_temp_to_request_attachment, generate_presigned_download_url
from utils.email_service import (
    notify_request_created,
    notify_request_approved,
    notify_request_rejected,
    notify_request_forwarded,
    notify_sla_auto_skipped,
)

logger = logging.getLogger(__name__)


def _utc_iso_now() -> str:
    """Return UTC timestamp as ISO string with Z suffix for correct client timezone display."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def _utc_iso(dt: datetime) -> str:
    """Format datetime as ISO string with Z (UTC). Use for sla_deadline etc."""
    d = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    return d.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


async def _noop_list() -> list:
    return []

async def _noop_dict() -> dict:
    return {}


class RequestService:
    """Service class for request business logic"""
    
    # Configuration: Minimum hierarchy level required to raise requests
    # Levels below this (1-2) cannot create requests (juniors/new joiners)
    MIN_LEVEL_FOR_REQUEST_CREATION = 0
    # Public/chatbot flow: allow override via env (0 = everyone can raise, 1+ = min level required)
    MIN_LEVEL_PUBLIC = int(os.environ.get("ALLOW_PUBLIC_REQUEST_MIN_LEVEL", "0"))
    # Approval flow: "sequential" = always start at HoD, amount decides approve vs forward; "skip" = assign to first eligible by amount
    APPROVAL_FLOW = (os.environ.get("REQUEST_APPROVAL_FLOW", "sequential") or "sequential").lower()
    
    def __init__(self):
        self.repository = RequestRepository()
    
    # ========================================================================
    # Context/Validation Methods
    # ========================================================================
    
    async def get_context(self, profile_id: str, agent_id: str) -> Tuple[Optional[Dict], Optional[Dict], Optional[str]]:
        """
        Get the context (agent, member) for a request operation.
        Returns (agent, member, error_message)
        """
        # Get chat agent
        agent = await self.repository.get_chat_agent(agent_id)
        if not agent:
            return None, None, "Chat agent not found"
        
        workspace_id = agent.get("workspace_id")
        
        # Get member for this profile in this workspace
        member = await self.repository.get_member_by_profile_and_workspace(profile_id, workspace_id)
        if not member:
            return agent, None, "You are not a member of this workspace"
        
        return agent, member, None

    def _check_tickets_view(self, member: Dict) -> Optional[str]:
        """Return error message if member cannot view tickets."""
        if not can_view(member, "tickets"):
            return "No view access to tickets"
        return None

    def _check_tickets_edit(self, member: Dict) -> Optional[str]:
        """Return error message if member cannot edit tickets."""
        if not can_edit(member, "tickets"):
            return "No edit access to tickets"
        return None
    
    # ========================================================================
    # Rules
    # ========================================================================

    async def get_rules(
        self,
        profile_id: str,
        agent_id: str,
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Get all active rules for an agent, with auth check."""
        agent, member, err = await self.get_context(profile_id, agent_id)
        if err:
            return None, err

        view_err = self._check_tickets_view(member)
        if view_err:
            return None, view_err

        workspace_id = agent.get("workspace_id")
        rules = await self.repository.get_rules_by_agent(workspace_id, agent_id)

        return {"rules": rules, "total": len(rules)}, None

    # ========================================================================
    # Request CRUD
    # ========================================================================
    
    async def create_request(
        self, 
        profile_id: str, 
        agent_id: str, 
        request_data: RequestCreate
    ) -> Tuple[Optional[RequestResponse], Optional[str]]:
        """Create a new request with auto-routing"""
        try:
            # Get context
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err
            
            workspace_id = agent["workspace_id"]
            member_id = member["id"]
            member_name = member.get("name", "Unknown")
            member_level = member.get("hierarchy_level", 1)
            
            # Check eligibility: Block juniors (levels 1-2) from raising requests
            if member_level < self.MIN_LEVEL_FOR_REQUEST_CREATION:
                return None, "You don't have the access to raise a request. Please reach out to your manager."
            
            # Merge request data for product-based flow
            req_data = dict(request_data.data or {})
            top_quantity = getattr(request_data, "quantity", None)
            if top_quantity is not None:
                req_data["quantity"] = top_quantity
            product_id = req_data.get("product_id")
            quantity = req_data.get("quantity", 1)
            is_draft = getattr(request_data, "is_draft", False)
            
            # Product-based: resolve amount and product name (needed for both draft and pending)
            current_approver = None
            current_approver_name = None
            required_level = None
            sla_hours = 48  # Default SLA
            rule = None
            approver_member = None
            
            if product_id and quantity is not None:
                amount, err, rule, prod_name = await self._resolve_amount_from_product(
                    workspace_id, agent_id, str(product_id), int(quantity),
                    rule_id=request_data.rule_id
                )
                if err:
                    return None, err
                req_data["amount"] = amount
                if prod_name:
                    req_data["product_name"] = prod_name
                if rule:
                    rdata = rule.get("data") or {}
                    if isinstance(rdata, str):
                        try:
                            rdata = json.loads(rdata)
                        except json.JSONDecodeError:
                            rdata = {}
                    sla_hours = rdata.get("sla_hours", 48)
            
            # Auto-generate subject when product is resolved
            resolved_subject = request_data.subject
            prod_name_resolved = req_data.get("product_name")
            if prod_name_resolved:
                resolved_subject = f"Request for {prod_name_resolved} ({quantity})"
            if not resolved_subject:
                resolved_subject = "New Request"
            
            # For drafts: skip approval routing, SLA, and email — just save the request
            if is_draft:
                now = _utc_iso_now()
                rule_id_val = rule.get("id") if rule else request_data.rule_id
                db_data = {
                    "workspace_id": workspace_id,
                    "chat_agent_id": agent_id,
                    "rule_id": rule_id_val,
                    "raised_by": member_id,
                    "raised_to": None,
                    "current_approver": None,
                    "subject": resolved_subject,
                    "description": request_data.description,
                    "request_type": request_data.request_type.value,
                    "category": request_data.category or "doa",
                    "priority": request_data.priority.value,
                    "data": req_data,
                    "attachments": request_data.attachments,
                    "status": "draft",
                    "current_level": member_level,
                    "required_level": None,
                    "sla_deadline": None,
                    "sla_auto_approve": getattr(request_data, "sla_auto_approve", True),
                    "messages": [],
                    "history": [
                        {
                            "action": "draft_created",
                            "by_id": member_id,
                            "by_name": member_name,
                            "at": now
                        }
                    ],
                    "approval_chain": [],
                    "escalation_chain": []
                }
                
                created = await self.repository.create_request(db_data)
                if not created:
                    return None, "Failed to create draft request"
                
                if request_data.attachments:
                    asyncio.create_task(self._move_temp_attachments_to_request(
                        created["id"], workspace_id, agent_id, member_id, member_name,
                        request_data.attachments
                    ))
                
                logger.info(f"[CREATE_REQ] Draft created: {created['id']} (request_number={created.get('request_number')})")
                response = await self._build_request_response(created, current_member_id=member_id)
                return response, None
            
            # --- Non-draft (pending) flow: full approval routing ---
            
            # Resolve rule by rule_name if provided (for explicit_chain / payment requests)
            if not rule and getattr(request_data, "rule_name", None):
                rule = await self.repository.get_rule_by_agent_and_name(
                    workspace_id, agent_id, request_data.rule_name
                )
                if rule:
                    rdata = rule.get("data") or {}
                    if isinstance(rdata, str):
                        try:
                            rdata = json.loads(rdata)
                        except json.JSONDecodeError:
                            rdata = {}
                    sla_hours = rdata.get("sla_hours", 48)

            # --- EXPLICIT CHAIN path (Payment Request etc.) ---
            rule_data = None
            if rule:
                rule_data = rule.get("data") or {}
                if isinstance(rule_data, str):
                    try:
                        rule_data = json.loads(rule_data)
                    except json.JSONDecodeError:
                        rule_data = {}

            if rule_data and rule_data.get("type") in ("explicit_chain", "explicit_chain_amount"):
                is_amount_chain = rule_data.get("type") == "explicit_chain_amount"
                sub_types = rule_data.get("sub_types", [])

                # For explicit_chain: key is payment_type; for explicit_chain_amount: key is department
                sub_type_key = req_data.get("department") if is_amount_chain else req_data.get("payment_type")
                if sub_types and sub_type_key and sub_type_key not in sub_types:
                    field_name = "department" if is_amount_chain else "payment_type"
                    return None, f"Invalid {field_name} '{sub_type_key}'. Must be one of: {', '.join(sub_types)}"

                chains_map = rule_data.get("chains", {})
                unit = (req_data.get("unit") or "").strip()
                entry = chains_map.get(sub_type_key) if sub_type_key else None

                if isinstance(entry, dict):
                    if is_amount_chain and not unit:
                        avail = sorted([k for k in entry.keys() if k != "_default"])
                        return None, f"Department '{sub_type_key}' requires 'data.unit'. Available units: {avail}"
                    required_units = rule_data.get("required_fields_per_type", {}).get(sub_type_key, [])
                    if not is_amount_chain and "unit" in required_units and not unit:
                        avail = sorted([k for k in entry.keys() if k != "_default"])
                        return None, f"Payment type '{sub_type_key}' requires 'data.unit'. Available units: {avail}"
                    chain_config = entry.get(unit) if unit else None
                    if not chain_config:
                        chain_config = entry.get("_default")
                    if not chain_config:
                        avail = sorted([k for k in entry.keys() if k != "_default"])
                        field_name = "department" if is_amount_chain else "payment_type"
                        return None, f"{field_name.title()} '{sub_type_key}' is not configured for unit '{unit}'. Available units: {avail}"
                elif isinstance(entry, list):
                    chain_config = entry
                else:
                    chain_config = rule_data.get("chain", [])

                if not chain_config:
                    rule_label = "DOA" if is_amount_chain else "Payment Request"
                    return None, f"{rule_label} rule has no approval chain configured"

                raiser_idx = next(
                    (i for i, e in enumerate(chain_config) if str(e.get("member_id") or "") == str(member_id)),
                    -1
                )
                if raiser_idx >= 0:
                    chain_config = chain_config[raiser_idx + 1:]
                    if not chain_config:
                        return None, "You are the last approver in this chain - no one above you to approve. Request not created."
                    logger.info(f"[CREATE_REQ] Raiser {member_name} is at chain idx {raiser_idx}; chain trimmed to {len(chain_config)} entries above them")

                now = _utc_iso_now()
                sla_deadline = datetime.now(timezone.utc) + timedelta(hours=sla_hours)
                sla_deadline_str = _utc_iso(sla_deadline)
                req_data["sla_hours"] = sla_hours

                approval_chain, current_approver, current_approver_name = await self._build_explicit_chain(
                    chain_config, assigned_at=now, sla_deadline=sla_deadline_str
                )
                if not current_approver:
                    rule_label = "DOA" if is_amount_chain else "payment request"
                    return None, f"No approver found in {rule_label} chain"

                approver_member = await self.repository.get_member_by_id(current_approver)
                current_level = approver_member.get("hierarchy_level", member_level) if approver_member else member_level

                default_subject = f"DOA Request - {sub_type_key}" if is_amount_chain else "Payment Request"
                assign_reason = f"DOA explicit chain ({sub_type_key}/{unit})" if is_amount_chain else "Payment Request explicit chain"

                db_data = {
                    "workspace_id": workspace_id,
                    "chat_agent_id": agent_id,
                    "rule_id": rule.get("id"),
                    "raised_by": member_id,
                    "raised_to": current_approver,
                    "current_approver": current_approver,
                    "subject": resolved_subject or default_subject,
                    "description": request_data.description,
                    "request_type": request_data.request_type.value,
                    "category": rule.get("category") or request_data.category or ("doa" if is_amount_chain else "payment_request"),
                    "priority": request_data.priority.value,
                    "data": req_data,
                    "attachments": request_data.attachments,
                    "status": "pending",
                    "current_level": current_level,
                    "required_level": None,
                    "sla_deadline": sla_deadline_str,
                    "sla_auto_approve": getattr(request_data, "sla_auto_approve", True),
                    "messages": [],
                    "history": [
                        {"action": "created", "by_id": member_id, "by_name": member_name, "at": now},
                        {"action": "auto_assigned", "to_id": current_approver, "to_name": current_approver_name, "reason": assign_reason, "at": now}
                    ],
                    "approval_chain": approval_chain,
                    "escalation_chain": []
                }

                created = await self.repository.create_request(db_data)
                if not created:
                    rule_label = "DOA" if is_amount_chain else "payment"
                    return None, f"Failed to create {rule_label} request"

                if request_data.attachments:
                    asyncio.create_task(self._move_temp_attachments_to_request(
                        created["id"], workspace_id, agent_id, member_id, member_name,
                        request_data.attachments
                    ))

                asyncio.create_task(notify_request_created(
                    requester_email=member.get("email"),
                    approver_email=approver_member.get("email") if approver_member else None,
                    request_number=created.get("request_number", created["id"]),
                    subject=db_data["subject"],
                    raised_by_name=member_name,
                ))

                logger.info(f"[CREATE_REQ] Explicit chain request created: {created['id']} sub_type={sub_type_key} unit={unit} first_approver={current_approver_name}")
                response = await self._build_request_response(created, current_member_id=member_id)
                return response, None

            # --- Standard approval routing (AOP/product-based) ---
            ignore_amount = False
            if rule and rule.get("rule_type") == "approval_chain":
                ignore_amount = True

            if product_id and quantity is not None:
                if self.APPROVAL_FLOW == "sequential":
                    current_approver, current_approver_name = await self._get_first_approver_in_chain(
                        workspace_id, member_id
                    )
                    if not current_approver:
                        logger.warning(f"[CREATE_REQ] _get_first_approver_in_chain returned None, falling back")
                else:
                    chain, current_approver, current_approver_name = await self._build_approval_chain_with_amount_skip(
                        workspace_id, member_id, req_data.get("amount", 0)
                    )
                    if not current_approver:
                        logger.warning(f"[CREATE_REQ] _build_approval_chain returned None, falling back")
            
            if not current_approver and request_data.rule_id:
                rule = await self.repository.get_rule_by_id(request_data.rule_id)
                if rule:
                    routing = await self._calculate_routing_from_rule(
                        rule, 
                        req_data, 
                        workspace_id,
                        member_level
                    )
                    current_approver = routing.get("approver_id")
                    current_approver_name = routing.get("approver_name")
                    required_level = routing.get("required_level")
                    sla_hours = rule.get("data", {}).get("sla_hours", 48)
            
            if not current_approver and request_data.raised_to:
                approver = await self.repository.get_member_by_id(request_data.raised_to)
                if approver:
                    current_approver = approver["id"]
                    current_approver_name = approver.get("name")
            
            if not current_approver:
                reports_to = member.get("reports_to")
                if reports_to:
                    manager = await self.repository.get_member_by_id(reports_to)
                    if manager:
                        current_approver = manager["id"]
                        current_approver_name = manager.get("name")
            
            # Calculate SLA deadline and store sla_hours for reuse on forwarding
            sla_deadline = datetime.now(timezone.utc) + timedelta(hours=sla_hours)
            req_data["sla_hours"] = sla_hours
            
            # Determine current_level: use approver's level if assigned, otherwise creator's level
            current_level = member_level
            if current_approver:
                approver_member = await self.repository.get_member_by_id(current_approver)
                if approver_member:
                    current_level = approver_member.get("hierarchy_level", member_level)
            
            # Build request data
            now = _utc_iso_now()
            sla_deadline_str = _utc_iso(sla_deadline)
            rule_id_val = rule.get("id") if rule else request_data.rule_id
            db_data = {
                "workspace_id": workspace_id,
                "chat_agent_id": agent_id,
                "rule_id": rule_id_val,
                "raised_by": member_id,
                "raised_to": request_data.raised_to or current_approver,
                "current_approver": current_approver,
                "subject": resolved_subject,
                "description": request_data.description,
                "request_type": request_data.request_type.value,
                "category": request_data.category or "doa",
                "priority": request_data.priority.value,
                "data": req_data,
                "attachments": request_data.attachments,
                "status": "pending",
                "current_level": current_level,
                "required_level": required_level,
                "sla_deadline": sla_deadline_str,
                "sla_auto_approve": getattr(request_data, "sla_auto_approve", True),
                "messages": [],
                "history": [
                    {
                        "action": "created",
                        "by_id": member_id,
                        "by_name": member_name,
                        "at": now
                    }
                ],
                "escalation_chain": []
            }
            
            # Add auto-assignment to history if applicable
            if current_approver:
                db_data["history"].append({
                    "action": "auto_assigned",
                    "to_id": current_approver,
                    "to_name": current_approver_name,
                    "reason": "Based on hierarchy/rule",
                    "at": now
                })
            
            # Build and store approval chain (with per-approver assigned_at + sla_deadline)
            if product_id and quantity is not None and current_approver:
                if self.APPROVAL_FLOW == "sequential":
                    db_data["approval_chain"] = await self._build_full_approval_chain_sequential(
                        workspace_id, member_id, current_approver, req_data.get("amount", 0),
                        assigned_at=now, sla_deadline=sla_deadline_str,
                        ignore_amount=ignore_amount
                    )
                else:
                    chain, _, _ = await self._build_approval_chain_with_amount_skip(
                        workspace_id, member_id, req_data.get("amount", 0),
                        assigned_at=now, sla_deadline=sla_deadline_str
                    )
                    db_data["approval_chain"] = chain
            else:
                db_data["approval_chain"] = await self._build_approval_chain(
                    workspace_id, current_approver,
                    assigned_at=now, sla_deadline=sla_deadline_str
                )
            
            # Create in database
            created = await self.repository.create_request(db_data)
            if not created:
                return None, "Failed to create request"
            
            # Move temp attachments to request folder (fire-and-forget)
            if request_data.attachments:
                asyncio.create_task(self._move_temp_attachments_to_request(
                    created["id"], workspace_id, agent_id, member_id, member_name,
                    request_data.attachments
                ))
            
            # Email notification (fire-and-forget)
            approver_m = approver_member if current_approver else None
            asyncio.create_task(notify_request_created(
                requester_email=member.get("email"),
                approver_email=approver_m.get("email") if approver_m else None,
                request_number=created.get("request_number", created["id"]),
                subject=resolved_subject,
                raised_by_name=member_name,
            ))
            
            # Build response with names
            response = await self._build_request_response(created, current_member_id=member_id)
            return response, None
            
        except Exception as e:
            logger.error(f"Error creating request: {str(e)}")
            return None, f"Failed to create request: {str(e)}"
    
    async def finalize_request(
        self,
        profile_id: str,
        agent_id: str,
        request_id: str,
        finalize_data: FinalizeRequest
    ) -> Tuple[Optional[RequestResponse], Optional[str]]:
        """Finalize a draft request: merge specs, build approval chain, flip draft→pending, send notifications."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err

            workspace_id = agent["workspace_id"]
            member_id = member["id"]
            member_name = member.get("name", "Unknown")
            member_level = member.get("hierarchy_level", 1)

            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            if request.get("chat_agent_id") != agent_id:
                return None, "Request not found"
            if request.get("status") != "draft":
                return None, "Only draft requests can be finalized"
            if request.get("raised_by") != member_id:
                return None, "Only the requester can finalize their draft"

            req_data = request.get("data") or {}
            if isinstance(req_data, str):
                try:
                    req_data = json.loads(req_data)
                except (json.JSONDecodeError, TypeError):
                    req_data = {}

            if finalize_data.specifications:
                req_data["specifications"] = finalize_data.specifications
            if finalize_data.conversation_id:
                req_data["conversation_id"] = finalize_data.conversation_id

            product_id = req_data.get("product_id")
            amount = req_data.get("amount", 0)

            # Build approval chain (same logic as non-draft create)
            current_approver = None
            current_approver_name = None
            required_level = None
            sla_hours = 48
            rule = None
            approver_member = None

            ignore_amount = False
            if product_id:
                rule_row = request.get("rule_id")
                if rule_row:
                    rule = await self.repository.get_rule_by_id(rule_row)
                    if rule:
                        rdata = rule.get("data") or {}
                        if isinstance(rdata, str):
                            try:
                                rdata = json.loads(rdata)
                            except json.JSONDecodeError:
                                rdata = {}
                        sla_hours = rdata.get("sla_hours", 48)
                        if rule.get("rule_type") == "approval_chain":
                            ignore_amount = True
                        logger.info(f"[FINALIZE] rule_type={rule.get('rule_type')}, ignore_amount={ignore_amount}, sla_hours={sla_hours}")

                if self.APPROVAL_FLOW == "sequential":
                    current_approver, current_approver_name = await self._get_first_approver_in_chain(
                        workspace_id, member_id
                    )
                else:
                    chain, current_approver, current_approver_name = await self._build_approval_chain_with_amount_skip(
                        workspace_id, member_id, amount
                    )

            if not current_approver:
                reports_to = member.get("reports_to")
                if reports_to:
                    manager = await self.repository.get_member_by_id(reports_to)
                    if manager:
                        current_approver = manager["id"]
                        current_approver_name = manager.get("name")

            sla_deadline = datetime.now(timezone.utc) + timedelta(hours=sla_hours)
            req_data["sla_hours"] = sla_hours

            current_level = member_level
            if current_approver:
                approver_member = await self.repository.get_member_by_id(current_approver)
                if approver_member:
                    current_level = approver_member.get("hierarchy_level", member_level)

            now = _utc_iso_now()
            sla_deadline_str = _utc_iso(sla_deadline)

            # Build approval chain with per-entry SLA
            approval_chain = []
            if product_id and current_approver:
                if self.APPROVAL_FLOW == "sequential":
                    approval_chain = await self._build_full_approval_chain_sequential(
                        workspace_id, member_id, current_approver, amount,
                        assigned_at=now, sla_deadline=sla_deadline_str,
                        ignore_amount=ignore_amount
                    )
                else:
                    chain, _, _ = await self._build_approval_chain_with_amount_skip(
                        workspace_id, member_id, amount,
                        assigned_at=now, sla_deadline=sla_deadline_str
                    )
                    approval_chain = chain
            elif current_approver:
                approval_chain = await self._build_approval_chain(
                    workspace_id, current_approver,
                    assigned_at=now, sla_deadline=sla_deadline_str
                )

            history = self._parse_json_field(request.get("history"), [])
            history.append({
                "action": "finalized",
                "by_id": member_id,
                "by_name": member_name,
                "at": now
            })
            if current_approver:
                history.append({
                    "action": "auto_assigned",
                    "to_id": current_approver,
                    "to_name": current_approver_name,
                    "reason": "Based on hierarchy/rule",
                    "at": now
                })

            update_data = {
                "status": "pending",
                "data": req_data,
                "raised_to": current_approver,
                "current_approver": current_approver,
                "current_level": current_level,
                "required_level": required_level,
                "approval_chain": approval_chain,
                "sla_deadline": sla_deadline_str,
                "history": history,
            }

            updated = await self.repository.update_request(request_id, update_data)
            if not updated:
                return None, "Failed to finalize request"

            logger.info(f"[FINALIZE_REQ] Draft {request_id} finalized to pending (approver={current_approver_name})")

            # Email notification (fire-and-forget)
            asyncio.create_task(notify_request_created(
                requester_email=member.get("email"),
                approver_email=approver_member.get("email") if approver_member else None,
                request_number=updated.get("request_number", updated["id"]),
                subject=updated.get("subject", ""),
                raised_by_name=member_name,
            ))

            response = await self._build_request_response(updated, current_member_id=member_id)
            return response, None

        except Exception as e:
            logger.error(f"Error finalizing request: {str(e)}")
            return None, f"Failed to finalize request: {str(e)}"

    async def get_request(self, profile_id: str, agent_id: str, request_id: str) -> Tuple[Optional[RequestResponse], Optional[str]]:
        """Get a single request by ID"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_view(member)
            if err:
                return None, err
            
            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            
            # Verify request belongs to this agent
            if request.get("chat_agent_id") != agent_id:
                return None, "Request not found"
            
            response = await self._build_request_response(request, include_conversation=True, current_member_id=member["id"])
            return response, None
            
        except Exception as e:
            logger.error(f"Error getting request: {str(e)}")
            return None, str(e)
    
    async def get_all_requests(
        self, 
        profile_id: str, 
        agent_id: str,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        include_conversation: bool = False
    ) -> Tuple[Optional[RequestListResponse], Optional[str]]:
        """Get all requests for an agent"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_view(member)
            if err:
                return None, err
            
            workspace_id = agent["workspace_id"]
            
            requests, total = await self.repository.get_requests_by_agent(
                agent_id, workspace_id, status, page, page_size
            )
            
            mid = member["id"]
            responses = await self._build_responses_batch(requests, include_conversation=include_conversation, current_member_id=mid)

            return RequestListResponse(
                requests=responses,
                total=total,
                page=page,
                page_size=page_size
            ), None
            
        except Exception as e:
            logger.error(f"Error getting requests: {str(e)}")
            return None, str(e)
    
    async def get_admin_requests(
        self,
        profile_id: str,
        agent_id: str,
        unit: Optional[str] = None,
        payment_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
        include_conversation: bool = False
    ) -> Tuple[Optional[RequestListResponse], Optional[str]]:
        """Admin view: all requests in the workspace.

        Permission: caller's member.data.is_admin must be true. If the admin member is
        scoped to a unit (member.unit_id IS NOT NULL), results are auto-restricted to
        that unit unless `unit` is explicitly provided AND matches.
        """
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_view(member)
            if err:
                return None, err

            mdata = member.get("data") or {}
            if isinstance(mdata, str):
                try:
                    mdata = json.loads(mdata)
                except (json.JSONDecodeError, TypeError):
                    mdata = {}
            if not mdata.get("is_admin"):
                return None, "Forbidden: admin privilege required (members.data.is_admin = true)"

            workspace_id = agent["workspace_id"]
            member_unit_id = member.get("unit_id")

            scoped_unit = unit
            if member_unit_id:
                unit_row = await self.repository.get_unit_by_id(member_unit_id) if hasattr(self.repository, "get_unit_by_id") else None
                admin_unit_code = (unit_row or {}).get("code") if unit_row else None
                if admin_unit_code:
                    if scoped_unit and scoped_unit != admin_unit_code:
                        return None, f"Forbidden: admin scoped to unit '{admin_unit_code}'"
                    scoped_unit = admin_unit_code

            requests, total = await self.repository.get_admin_requests(
                agent_id, workspace_id,
                unit=scoped_unit, payment_type=payment_type, status=status,
                page=page, page_size=page_size
            )

            mid = member["id"]
            responses = await self._build_responses_batch(
                requests, include_conversation=include_conversation, current_member_id=mid
            )

            return RequestListResponse(
                requests=responses,
                total=total,
                page=page,
                page_size=page_size
            ), None

        except Exception as e:
            logger.error(f"Error getting admin requests: {str(e)}")
            return None, str(e)

    async def get_raised_by_me(
        self,
        profile_id: str,
        agent_id: str,
        page: int = 1,
        page_size: int = 20,
        include_conversation: bool = False
    ) -> Tuple[Optional[RequestListResponse], Optional[str]]:
        """Get requests raised by the current user"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_view(member)
            if err:
                return None, err
            
            member_id = member["id"]
            
            requests, total = await self.repository.get_requests_raised_by_member(
                agent_id, member_id, page, page_size
            )
            
            responses = await self._build_responses_batch(requests, include_conversation=include_conversation, current_member_id=member_id)

            return RequestListResponse(
                requests=responses,
                total=total,
                page=page,
                page_size=page_size
            ), None

        except Exception as e:
            logger.error(f"Error getting raised by me: {str(e)}")
            return None, str(e)
    
    async def get_raised_to_me(
        self, 
        profile_id: str, 
        agent_id: str,
        page: int = 1,
        page_size: int = 20,
        include_conversation: bool = False
    ) -> Tuple[Optional[RequestListResponse], Optional[str]]:
        """Get requests assigned to the current user (pending action)"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_view(member)
            if err:
                return None, err
            
            member_id = member["id"]
            
            # Check for active delegation
            effective_member_id = await self._get_effective_member_id(member)
            
            requests, total = await self.repository.get_requests_raised_to_member(
                agent_id, effective_member_id, page, page_size
            )
            
            responses = await self._build_responses_batch(requests, include_conversation=include_conversation, current_member_id=member_id)

            return RequestListResponse(
                requests=responses,
                total=total,
                page=page,
                page_size=page_size
            ), None

        except Exception as e:
            logger.error(f"Error getting raised to me: {str(e)}")
            return None, str(e)

    async def get_acted_by_me(
        self,
        profile_id: str,
        agent_id: str,
        page: int = 1,
        page_size: int = 20,
        include_conversation: bool = False
    ) -> Tuple[Optional[RequestListResponse], Optional[str]]:
        """Get requests where current user approved, forwarded, or rejected"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_view(member)
            if err:
                return None, err

            member_id = member["id"]
            requests, total = await self.repository.get_requests_approved_by_member(
                agent_id, member_id, page, page_size
            )
            responses = await self._build_responses_batch(requests, include_conversation=include_conversation, current_member_id=member_id)
            return RequestListResponse(
                requests=responses,
                total=total,
                page=page,
                page_size=page_size
            ), None
        except Exception as e:
            logger.error(f"Error getting acted-by-me requests: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # Request Actions
    # ========================================================================
    
    async def approve_request(
        self, 
        profile_id: str, 
        agent_id: str, 
        request_id: str,
        data: ApproveRequest,
        file_data_list: Optional[list] = None
    ) -> Tuple[Optional[RequestResponse], Optional[str]]:
        """Approve a request"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err
            
            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            
            member_id = member["id"]
            member_name = member.get("name", "Unknown")

            if file_data_list:
                uploaded = await self._upload_files_to_attachments(
                    agent["workspace_id"], agent_id, request_id,
                    member_id, member_name, file_data_list
                )
                data.attachments = (data.attachments or []) + uploaded
            
            # Check if member is the current approver
            if request.get("current_approver") != member_id:
                # Check delegation
                is_delegate = await self._check_delegation(request.get("current_approver"), member_id)
                if not is_delegate:
                    return None, "You are not authorized to approve this request"
            
            now = _utc_iso_now()
            
            # Update history
            history = request.get("history", [])
            history.append({
                "action": "approved",
                "by_id": member_id,
                "by_name": member_name,
                "comment": data.comment,
                "at": now
            })
            
            # Add message if comment or attachments provided
            messages = request.get("messages", [])
            action_attachments = [dict(a) for a in (data.attachments or [])]
            if data.comment or action_attachments:
                messages.append({
                    "id": str(uuid.uuid4()),
                    "sender_id": member_id,
                    "sender_name": member_name,
                    "message": data.comment or "Approved",
                    "action": "approved",
                    "attachments": action_attachments,
                    "created_at": now
                })
            
            # Sync action attachments to request-level
            req_attachments = None
            if action_attachments:
                req_attachments = self._sync_attachments_to_request(
                    self._parse_json_field(request.get("attachments"), []),
                    action_attachments
                )
            
            # Check if delegate approved
            approved_by_delegate = request.get("current_approver") != member_id
            current_approver_obj = await self.repository.get_member_by_id(request.get("current_approver"))
            next_reports_to = current_approver_obj.get("reports_to") if current_approver_obj else None

            # For explicit_chain rules (payment_request etc.), advancement follows the
            # approval_chain array, NOT reports_to. Override next_reports_to with the
            # next chain entry's member id so the existing forward block does the rest.
            rule_for_advance = None
            if request.get("rule_id"):
                rule_for_advance = await self.repository.get_rule_by_id(request.get("rule_id"))
            rule_data_for_advance = (rule_for_advance or {}).get("data") or {}
            if isinstance(rule_data_for_advance, str):
                try:
                    rule_data_for_advance = json.loads(rule_data_for_advance)
                except (json.JSONDecodeError, TypeError):
                    rule_data_for_advance = {}
            is_explicit_chain = rule_data_for_advance.get("type") in ("explicit_chain", "explicit_chain_amount")
            is_amount_chain = rule_data_for_advance.get("type") == "explicit_chain_amount"
            if is_explicit_chain:
                existing_chain_for_advance = self._parse_json_field(request.get("approval_chain"), [])
                cur_idx = next(
                    (i for i, e in enumerate(existing_chain_for_advance)
                     if isinstance(e, dict) and str(e.get("id")) == str(request.get("current_approver"))),
                    -1
                )
                if 0 <= cur_idx < len(existing_chain_for_advance) - 1:
                    next_entry = existing_chain_for_advance[cur_idx + 1]
                    if isinstance(next_entry, dict) and next_entry.get("id"):
                        next_reports_to = next_entry["id"]
                else:
                    next_reports_to = None  # last in chain -> final approval

            # Sequential flow: amount decides approve vs forward. receives_only always forwards.
            should_forward = False
            if is_explicit_chain and next_reports_to:
                if is_amount_chain:
                    # Amount-based stopping: check max_amount on current chain entry
                    chain_entry = existing_chain_for_advance[cur_idx] if cur_idx >= 0 else {}
                    max_amt = chain_entry.get("max_amount")
                    req_data_for_amt = request.get("data") or {}
                    if isinstance(req_data_for_amt, str):
                        try:
                            req_data_for_amt = json.loads(req_data_for_amt)
                        except json.JSONDecodeError:
                            req_data_for_amt = {}
                    amount = float(req_data_for_amt.get("amount", 0) or 0)
                    if max_amt is None:
                        should_forward = False  # null = final approver, can approve any amount
                    elif max_amt == 0:
                        should_forward = True   # 0 = validation/receives only, always forward
                    else:
                        should_forward = amount > float(max_amt)
                else:
                    should_forward = True  # Pure explicit_chain: always forward to next
            if self.APPROVAL_FLOW == "sequential" and next_reports_to and not should_forward:
                req_data = request.get("data") or {}
                if isinstance(req_data, str):
                    try:
                        req_data = json.loads(req_data)
                    except json.JSONDecodeError:
                        req_data = {}
                amount = req_data.get("amount")
                has_amount = amount is not None
                if has_amount:
                    amount = float(amount)
                else:
                    existing_chain = self._parse_json_field(request.get("approval_chain"), [])
                    remaining = [e for e in existing_chain if isinstance(e, dict) and e.get("status") in ("", None)]
                    if remaining:
                        should_forward = True
                if not should_forward and has_amount:
                    hierarchy_list = await self.repository.get_hierarchy_by_workspace(request["workspace_id"])
                    hierarchy_by_level = {}
                    for h in hierarchy_list:
                        lvl = h.get("level")
                        if lvl is not None:
                            hdata = h.get("data") or {}
                            if isinstance(hdata, str):
                                try:
                                    hdata = json.loads(hdata)
                                except json.JSONDecodeError:
                                    hdata = {}
                            hierarchy_by_level[int(lvl)] = hdata
                    approver_level = current_approver_obj.get("hierarchy_level")
                    if approver_level is not None:
                        approver_level = int(approver_level)
                    h_data = hierarchy_by_level.get(approver_level, {})
                    if h_data.get("receives_only") and not h_data.get("can_approve"):
                        should_forward = True
                    else:
                        max_amt = h_data.get("max_approval_amount")
                        if max_amt is not None:
                            try:
                                max_amt = float(max_amt)
                            except (TypeError, ValueError):
                                max_amt = 0
                        else:
                            max_amt = float("inf")
                        should_forward = amount > max_amt

            # Multi-level: if current approver has reports_to and (skip mode or should_forward), move to next level
            if next_reports_to and (self.APPROVAL_FLOW != "sequential" or should_forward):
                next_approver = await self.repository.get_member_by_id(next_reports_to)
                if next_approver:
                    history.append({
                        "action": "forwarded",
                        "from_id": member_id,
                        "from_name": member_name,
                        "to_id": next_approver["id"],
                        "to_name": next_approver.get("name", "Unknown"),
                        "reason": "Approved, moved to next level",
                        "at": now
                    })
                    # Reset SLA for next approver
                    fwd_req_data = self._parse_json_field(request.get("data"), {})
                    fwd_sla_hours = fwd_req_data.get("sla_hours", 48) if isinstance(fwd_req_data, dict) else 48
                    new_sla_dt = datetime.now(timezone.utc) + timedelta(hours=fwd_sla_hours)
                    new_sla_str = _utc_iso(new_sla_dt)

                    # Update approval_chain: mark current_approver as approved, next as pending with SLA
                    approver_id = request.get("current_approver")
                    existing_chain = self._parse_json_field(request.get("approval_chain"), [])
                    if existing_chain and isinstance(existing_chain, list):
                        chain = self._update_approval_chain_entry(
                            existing_chain, approver_id, "approved", now
                        )
                        chain = self._set_approval_chain_pending(
                            chain, next_approver["id"],
                            assigned_at=now, sla_deadline=new_sla_str
                        )
                    else:
                        chain = await self._build_approval_chain(
                            request["workspace_id"], next_approver["id"], "pending", "",
                            assigned_at=now, sla_deadline=new_sla_str
                        )
                    update_data = {
                        "status": "pending",
                        "current_approver": next_approver["id"],
                        "raised_to": next_approver["id"],
                        "current_level": next_approver.get("hierarchy_level"),
                        "sla_deadline": new_sla_str,
                        "history": history,
                        "messages": messages,
                        "approval_chain": chain,
                        "approved_by_delegate": approved_by_delegate,
                        "original_approver": request.get("current_approver") if approved_by_delegate else None
                    }
                    if req_attachments is not None:
                        update_data["attachments"] = req_attachments
                else:
                    update_data = None
            else:
                update_data = None

            # Final approval (no next level) - update chain: mark current_approver as approved
            if not update_data:
                approver_id = request.get("current_approver")
                existing_chain = self._parse_json_field(request.get("approval_chain"), [])
                if existing_chain and isinstance(existing_chain, list):
                    chain = self._update_approval_chain_entry(
                        existing_chain, approver_id, "approved", now
                    )
                else:
                    chain = []
                update_data = {
                    "status": "approved",
                    "history": history,
                    "messages": messages,
                    "approval_chain": chain,
                    "resolved_at": now,
                    "approved_by_delegate": approved_by_delegate,
                    "original_approver": request.get("current_approver") if approved_by_delegate else None
                }
                if req_attachments is not None:
                    update_data["attachments"] = req_attachments
            
            updated = await self.repository.update_request(request_id, update_data)
            if not updated:
                return None, "Failed to approve request"
            
            # Email notification (fire-and-forget)
            requester_m = await self.repository.get_member_by_id(request.get("raised_by"))
            req_num = updated.get("request_number", request_id)
            subj = updated.get("subject", "")
            if updated.get("status") == "approved":
                asyncio.create_task(notify_request_approved(
                    requester_email=requester_m.get("email") if requester_m else None,
                    request_number=req_num,
                    subject=subj,
                    approver_name=member_name,
                ))
            elif updated.get("status") == "pending" and update_data and "current_approver" in update_data:
                next_ap = await self.repository.get_member_by_id(update_data["current_approver"])
                asyncio.create_task(notify_request_forwarded(
                    requester_email=requester_m.get("email") if requester_m else None,
                    next_approver_email=next_ap.get("email") if next_ap else None,
                    request_number=req_num,
                    subject=subj,
                    from_name=member_name,
                    to_name=next_ap.get("name", "Next approver") if next_ap else "Next approver",
                ))
            
            response = await self._build_request_response(updated, current_member_id=member_id)
            return response, None
            
        except Exception as e:
            logger.error(f"Error approving request: {str(e)}")
            return None, str(e)

    async def revise_budget(
        self,
        profile_id: str,
        agent_id: str,
        request_id: str,
        revised_amount: float,
        reason: Optional[str] = None
    ) -> Tuple[Optional[RequestResponse], Optional[str]]:
        """
        Allow Procurement (receives_only level) to revise the budget/amount.
        Recalculates approval chain for amount_based rules.
        """
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err

            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"

            member_id = member["id"]
            member_name = member.get("name", "Unknown")
            workspace_id = agent["workspace_id"]

            if request.get("current_approver") != member_id:
                is_delegate = await self._check_delegation(request.get("current_approver"), member_id)
                if not is_delegate:
                    return None, "You are not the current approver for this request"

            hierarchy_list = await self.repository.get_hierarchy_by_workspace(workspace_id)
            hierarchy_by_level = {}
            for h in hierarchy_list:
                lvl = h.get("level")
                if lvl is not None:
                    hdata = h.get("data") or {}
                    if isinstance(hdata, str):
                        try:
                            hdata = json.loads(hdata)
                        except json.JSONDecodeError:
                            hdata = {}
                    hierarchy_by_level[int(lvl)] = hdata

            member_level = member.get("hierarchy_level")
            if member_level is not None:
                member_level = int(member_level)
            h_data = hierarchy_by_level.get(member_level, {})
            if not h_data.get("receives_only"):
                return None, "Only procurement (receives_only) members can revise the budget"

            req_data = request.get("data") or {}
            if isinstance(req_data, str):
                try:
                    req_data = json.loads(req_data)
                except (json.JSONDecodeError, TypeError):
                    req_data = {}

            original_amount = req_data.get("original_amount") or req_data.get("amount", 0)
            old_amount = req_data.get("amount", 0)
            req_data["original_amount"] = original_amount
            req_data["amount"] = revised_amount

            now = _utc_iso_now()

            history = self._parse_json_field(request.get("history"), [])
            history.append({
                "action": "budget_revised",
                "by_id": member_id,
                "by_name": member_name,
                "old_amount": old_amount,
                "new_amount": revised_amount,
                "reason": reason,
                "at": now
            })

            messages = self._parse_json_field(request.get("messages"), [])
            msg_text = f"Budget revised from ₹{old_amount:,.0f} to ₹{revised_amount:,.0f}"
            if reason:
                msg_text += f" — {reason}"
            messages.append({
                "id": str(uuid.uuid4()),
                "sender_id": member_id,
                "sender_name": member_name,
                "message": msg_text,
                "action": "budget_revised",
                "attachments": [],
                "created_at": now
            })

            ignore_amount = False
            rule_id = request.get("rule_id")
            if rule_id:
                rule = await self.repository.get_rule_by_id(rule_id)
                if rule and rule.get("rule_type") == "approval_chain":
                    ignore_amount = True

            raised_by = request.get("raised_by")
            first_approver_id = member_id

            approval_chain = await self._build_full_approval_chain_sequential(
                workspace_id, raised_by, first_approver_id, revised_amount,
                assigned_at=request.get("sla_deadline"),
                sla_deadline=request.get("sla_deadline"),
                ignore_amount=ignore_amount
            )

            existing_chain = self._parse_json_field(request.get("approval_chain"), [])
            preserved = []
            for entry in existing_chain:
                if not isinstance(entry, dict):
                    continue
                if entry.get("status") == "approved":
                    preserved.append(entry)

            current_entry = None
            for entry in existing_chain:
                if isinstance(entry, dict) and entry.get("id") == member_id and entry.get("status") == "pending":
                    current_entry = dict(entry)
                    break

            if current_entry:
                preserved.append(current_entry)

            preserved_ids = {str(e.get("id")) for e in preserved}
            for entry in approval_chain:
                if str(entry.get("id")) not in preserved_ids:
                    preserved.append(entry)

            update_data = {
                "data": req_data,
                "approval_chain": preserved,
                "history": history,
                "messages": messages,
            }

            updated = await self.repository.update_request(request_id, update_data)
            if not updated:
                return None, "Failed to revise budget"

            logger.info(f"[REVISE_BUDGET] {request_id}: {old_amount} -> {revised_amount}, stays with {member_name}, chain_entries={len(preserved)}")

            response = await self._build_request_response(updated, current_member_id=member_id)
            return response, None

        except Exception as e:
            logger.error(f"Error revising budget: {str(e)}")
            return None, str(e)

    async def reject_request(
        self, 
        profile_id: str, 
        agent_id: str, 
        request_id: str,
        data: RejectRequest,
        file_data_list: Optional[list] = None
    ) -> Tuple[Optional[RequestResponse], Optional[str]]:
        """Reject a request"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err
            
            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            
            member_id = member["id"]
            member_name = member.get("name", "Unknown")

            if file_data_list:
                uploaded = await self._upload_files_to_attachments(
                    agent["workspace_id"], agent_id, request_id,
                    member_id, member_name, file_data_list
                )
                data.attachments = (data.attachments or []) + uploaded
            
            # Check if member is the current approver
            if request.get("current_approver") != member_id:
                is_delegate = await self._check_delegation(request.get("current_approver"), member_id)
                if not is_delegate:
                    return None, "You are not authorized to reject this request"
            
            now = _utc_iso_now()
            
            # Update history
            history = request.get("history", [])
            history.append({
                "action": "rejected",
                "by_id": member_id,
                "by_name": member_name,
                "reason": data.reason,
                "at": now
            })
            
            # Add rejection message
            messages = request.get("messages", [])
            action_attachments = [dict(a) for a in (data.attachments or [])]
            messages.append({
                "id": str(uuid.uuid4()),
                "sender_id": member_id,
                "sender_name": member_name,
                "message": f"Rejected: {data.reason}",
                "action": "rejected",
                "attachments": action_attachments,
                "created_at": now
            })
            
            # Update approval_chain: mark current_approver as rejected
            approver_id = request.get("current_approver")
            existing_chain = self._parse_json_field(request.get("approval_chain"), [])
            if existing_chain and isinstance(existing_chain, list):
                chain = self._update_approval_chain_entry(
                    existing_chain, approver_id, "rejected", now
                )
            else:
                chain = []
            
            update_data = {
                "status": "rejected",
                "history": history,
                "messages": messages,
                "approval_chain": chain,
                "resolved_at": now
            }
            if action_attachments:
                update_data["attachments"] = self._sync_attachments_to_request(
                    self._parse_json_field(request.get("attachments"), []),
                    action_attachments
                )
            
            updated = await self.repository.update_request(request_id, update_data)
            if not updated:
                return None, "Failed to reject request"
            
            # Email notification (fire-and-forget)
            requester_m = await self.repository.get_member_by_id(request.get("raised_by"))
            asyncio.create_task(notify_request_rejected(
                requester_email=requester_m.get("email") if requester_m else None,
                request_number=updated.get("request_number", request_id),
                subject=updated.get("subject", ""),
                approver_name=member_name,
                reason=data.reason,
            ))
            
            response = await self._build_request_response(updated, current_member_id=member_id)
            return response, None
            
        except Exception as e:
            logger.error(f"Error rejecting request: {str(e)}")
            return None, str(e)
    
    async def escalate_request(
        self, 
        profile_id: str, 
        agent_id: str, 
        request_id: str,
        data: EscalateRequest,
        file_data_list: Optional[list] = None
    ) -> Tuple[Optional[RequestResponse], Optional[str]]:
        """Escalate a request to the next level"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err
            
            workspace_id = agent["workspace_id"]
            
            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            
            member_id = member["id"]
            member_name = member.get("name", "Unknown")

            if file_data_list:
                uploaded = await self._upload_files_to_attachments(
                    workspace_id, agent_id, request_id,
                    member_id, member_name, file_data_list
                )
                data.attachments = (data.attachments or []) + uploaded
            member_level = member.get("hierarchy_level", 1)
            
            # Debug: Log member info
            logger.info(f"Escalation attempt by: {member_name} (ID: {member_id}, Level: {member_level})")
            logger.info(f"Member reports_to: {member.get('reports_to')}")
            if member.get("reports_to"):
                reports_to_member = await self.repository.get_member_by_id(member.get("reports_to"))
                if reports_to_member:
                    logger.info(f"Reports to: {reports_to_member.get('name')} (Level: {reports_to_member.get('hierarchy_level')})")
                else:
                    logger.warning(f"Member reports_to ID {member.get('reports_to')} not found in members table!")
            
            # Check if member is the current approver (or delegate)
            current_approver_id = request.get("current_approver")
            if current_approver_id != member_id:
                is_delegate = await self._check_delegation(current_approver_id, member_id)
                if not is_delegate:
                    return None, "Only the current approver can escalate this request"
            
            # Find next level approver (skip empty levels)
            # Ensure current_level is an integer
            current_level_raw = request.get("current_level", member_level)
            current_level = int(current_level_raw) if current_level_raw is not None else member_level
            logger.info(f"Request current_level: {request.get('current_level')} (type: {type(request.get('current_level'))}), member_level: {member_level}, using: {current_level} (type: {type(current_level)})")
            
            # Find next level that has a member (skip empty levels)
            next_level = None
            next_approver = None
            
            # Get all hierarchy levels sorted
            all_levels = await self.repository.get_hierarchy_by_workspace(workspace_id)
            sorted_levels = sorted([int(h["level"]) for h in all_levels])  # Ensure integers
            
            # Debug: Get all members at each level to help diagnose
            debug_info = []
            all_members = await self.repository.get_members_by_workspace(workspace_id)
            for level in sorted_levels:
                members_at_level = [m for m in all_members if int(m.get("hierarchy_level", 0)) == level]
                debug_info.append(f"Level {level}: {len(members_at_level)} member(s) - {[m.get('name') + ' (' + m.get('email') + ')' for m in members_at_level]}")
            
            logger.info(f"Escalation: current_level={current_level} (type: {type(current_level)}), member_level={member_level}, available_levels={sorted_levels}")
            logger.info(f"Members by level: {'; '.join(debug_info)}")
            
            # Find next level with a member
            for level in sorted_levels:
                if level > current_level:
                    try:
                        approver = await self.repository.get_member_by_level(workspace_id, level)
                        logger.info(f"Checking level {level}: found={approver is not None}")
                        if approver:
                            logger.info(f"Found approver at level {level}: {approver.get('name')} ({approver.get('email')}), status={approver.get('status')}, is_active={approver.get('is_active')}")
                            next_level = level
                            next_approver = approver
                            break
                        else:
                            logger.warning(f"No approver found at level {level} - checking if any members exist at this level")
                            # Debug: Check if any members exist at this level (even if inactive)
                            all_members_at_level = [m for m in all_members if int(m.get("hierarchy_level", 0)) == level]
                            if all_members_at_level:
                                logger.warning(f"Members exist at level {level} but don't meet criteria: {[(m.get('name'), m.get('status'), m.get('is_active')) for m in all_members_at_level]}")
                    except Exception as e:
                        logger.error(f"Error checking level {level}: {str(e)}")
                        continue
            
            if not next_level or not next_approver:
                logger.warning(f"Escalation failed: current_level={current_level}, available_levels={sorted_levels}, workspace_id={workspace_id}")
                # Check if there are any levels above current_level
                levels_above = [l for l in sorted_levels if l > current_level]
                if levels_above:
                    # Get detailed info about members at those levels
                    debug_details = []
                    for level in levels_above:
                        members_at_level = [m for m in all_members if int(m.get("hierarchy_level", 0)) == level]
                        if members_at_level:
                            for m in members_at_level:
                                debug_details.append(f"Level {level}: {m.get('name')} ({m.get('email')}) - status={m.get('status')}, is_active={m.get('is_active')}")
                        else:
                            debug_details.append(f"Level {level}: No members found")
                    
                    error_msg = f"Cannot escalate - no active approver found at levels {levels_above}.\n"
                    error_msg += f"Debug info: {'; '.join(debug_details)}\n"
                    error_msg += f"Please ensure a member exists at level {levels_above[0]} with status='active' and is_active=true."
                    return None, error_msg
                else:
                    return None, f"Cannot escalate - already at highest level ({current_level})"
            
            now = _utc_iso_now()
            
            # Update escalation chain
            escalation_chain = request.get("escalation_chain", [])
            escalation_chain.append({
                "level": current_level,
                "member_id": request.get("current_approver"),
                "at": now
            })
            
            # Update history
            history = request.get("history", [])
            history.append({
                "action": "escalated",
                "by_id": member_id,
                "by_name": member_name,
                "from_level": current_level,
                "to_level": next_level,
                "to_id": next_approver["id"],
                "to_name": next_approver.get("name"),
                "reason": data.reason,
                "is_emergency": data.is_emergency,
                "at": now
            })
            
            # Add message if escalation has attachments or reason
            action_attachments = [dict(a) for a in (data.attachments or [])]
            messages = self._parse_json_field(request.get("messages"), [])
            if data.reason or action_attachments:
                messages.append({
                    "id": str(uuid.uuid4()),
                    "sender_id": member_id,
                    "sender_name": member_name,
                    "message": data.reason or "Escalated",
                    "action": "escalated",
                    "attachments": action_attachments,
                    "created_at": now
                })

            # Rebuild approval_chain from new approver with per-entry SLA
            esc_req_data = self._parse_json_field(request.get("data"), {})
            esc_sla_hours = esc_req_data.get("sla_hours", 48) if isinstance(esc_req_data, dict) else 48
            esc_sla_str = _utc_iso(datetime.now(timezone.utc) + timedelta(hours=esc_sla_hours))
            approval_chain = await self._build_approval_chain(
                workspace_id, next_approver["id"], "pending", "",
                assigned_at=now, sla_deadline=esc_sla_str
            )
            update_data = {
                "status": "pending",
                "current_level": next_level,
                "current_approver": next_approver["id"],
                "raised_to": next_approver["id"],
                "sla_deadline": esc_sla_str,
                "escalation_chain": escalation_chain,
                "history": history,
                "messages": messages,
                "approval_chain": approval_chain,
                "is_emergency": data.is_emergency,
                "emergency_reason": data.reason if data.is_emergency else None
            }
            if action_attachments:
                update_data["attachments"] = self._sync_attachments_to_request(
                    self._parse_json_field(request.get("attachments"), []),
                    action_attachments
                )
            
            updated = await self.repository.update_request(request_id, update_data)
            if not updated:
                return None, "Failed to escalate request"
            
            response = await self._build_request_response(updated, current_member_id=member_id)
            return response, None
            
        except Exception as e:
            logger.error(f"Error escalating request: {str(e)}")
            return None, str(e)
    
    async def add_message(
        self,
        profile_id: str,
        agent_id: str,
        request_id: str,
        message: str,
        attachments: List[Dict] = None,
        file_data_list: Optional[list] = None
    ) -> Tuple[Optional[RequestResponse], Optional[str]]:
        """Add a message/comment to a request"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err
            
            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            
            member_id = member["id"]
            member_name = member.get("name", "Unknown")

            if file_data_list:
                uploaded = await self._upload_files_to_attachments(
                    agent["workspace_id"], agent_id, request_id,
                    member_id, member_name, file_data_list
                )
                attachments = (attachments or []) + uploaded
            
            now = _utc_iso_now()
            
            # Add message
            messages = request.get("messages", [])
            msg_attachments = attachments or []
            messages.append({
                "id": str(uuid.uuid4()),
                "sender_id": member_id,
                "sender_name": member_name,
                "message": message,
                "action": "comment",
                "attachments": msg_attachments,
                "created_at": now
            })
            
            update_data = {"messages": messages}
            if msg_attachments:
                update_data["attachments"] = self._sync_attachments_to_request(
                    self._parse_json_field(request.get("attachments"), []),
                    msg_attachments
                )
            
            updated = await self.repository.update_request(request_id, update_data)
            if not updated:
                return None, "Failed to add message"
            
            response = await self._build_request_response(updated, current_member_id=member_id)
            return response, None
            
        except Exception as e:
            logger.error(f"Error adding message: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # Attachment Upload
    # ========================================================================

    async def _upload_files_to_attachments(
        self, workspace_id: str, agent_id: str, request_id: str,
        member_id: str, member_name: str, file_data_list: list
    ) -> List[Dict]:
        """Upload files to storage and return attachment metadata dicts."""
        req = await self.repository.get_request_by_id(request_id)
        request_number = (req.get("request_number") if req else None) or request_id

        now = _utc_iso_now()
        attachments = []
        for fd in file_data_list:
            url, s3_key = await upload_ticket_attachment(
                workspace_id, agent_id, request_number,
                fd["file_content"], fd["file_name"], fd["content_type"]
            )
            attachments.append({
                "id": f"att_{uuid.uuid4().hex[:12]}",
                "name": fd["file_name"],
                "size": fd["file_size"],
                "content_type": fd["content_type"],
                "url": url,
                "s3_key": s3_key,
                "uploaded_by": member_id,
                "uploaded_by_name": member_name,
                "uploaded_at": now
            })
        return attachments

    def _normalize_category(self, category: Optional[str]) -> str:
        """Normalize request category. Maps legacy DOA-related categories to 'doa'."""
        if not category or category in ("finance", "capex_add_budget", "capex_non_aop"):
            return "doa"
        return category

    def _enrich_attachments_can_delete(
        self, attachments: List[Dict], current_member_id: str = None
    ) -> List[Dict]:
        """Add can_delete flag to each attachment based on uploader match."""
        if not attachments or not isinstance(attachments, list):
            return attachments
        result = []
        for att in attachments:
            if isinstance(att, dict):
                enriched = dict(att)
                enriched["can_delete"] = (
                    current_member_id is not None
                    and att.get("uploaded_by") == current_member_id
                )
                result.append(enriched)
            else:
                result.append(att)
        return result

    def _sync_attachments_to_request(
        self, existing_attachments: List[Dict], new_attachments: List[Dict]
    ) -> List[Dict]:
        """Append new attachments to request-level list, deduped by id."""
        result = list(existing_attachments)
        existing_ids = {a.get("id") for a in result if isinstance(a, dict) and a.get("id")}
        for att in new_attachments:
            if isinstance(att, dict) and att.get("id") and att["id"] not in existing_ids:
                result.append(att)
                existing_ids.add(att["id"])
        return result

    async def _move_temp_attachments_to_request(
        self, request_id: str, workspace_id: str, agent_id: str,
        member_id: str, member_name: str, temp_attachments: list
    ):
        """Move pre-uploaded temp attachments to the request folder and update DB."""
        try:
            req = await self.repository.get_request_by_id(request_id)
            request_number = (req.get("request_number") if req else None) or request_id

            now = _utc_iso_now()
            moved_attachments = []
            for att in temp_attachments:
                storage_path = att.get("storage_path")
                if not storage_path:
                    moved_attachments.append(att)
                    continue
                try:
                    new_url, new_s3_key = await move_temp_to_request_attachment(
                        storage_path, workspace_id, agent_id, request_number
                    )
                    clean_att = {k: v for k, v in att.items() if k != "storage_path"}
                    clean_att["url"] = new_url
                    clean_att["s3_key"] = new_s3_key
                    moved_attachments.append(clean_att)
                except Exception as move_err:
                    logger.warning(f"Failed to move temp attachment {storage_path}, keeping temp URL: {move_err}")
                    clean_att = {k: v for k, v in att.items() if k != "storage_path"}
                    moved_attachments.append(clean_att)

            if not moved_attachments:
                return

            file_names = ", ".join(a.get("name", "file") for a in moved_attachments)
            messages = [{
                "id": str(uuid.uuid4()),
                "sender_id": member_id,
                "sender_name": member_name,
                "message": f"Attached {len(moved_attachments)} file(s): {file_names}",
                "action": "attachment",
                "attachments": moved_attachments,
                "created_at": now
            }]

            await self.repository.update_request(request_id, {
                "attachments": moved_attachments,
                "messages": messages
            })
            logger.info(f"Moved {len(moved_attachments)} temp attachments to request {request_id}")

        except Exception as e:
            logger.error(f"Error moving temp attachments for request {request_id}: {str(e)}")

    async def upload_attachment(
        self, profile_id: str, agent_id: str, request_id: str,
        file_data_list: list
    ) -> Tuple[Optional[list], Optional[str]]:
        """Upload multiple files to storage, append to request.attachments, add audit messages."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err

            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            if request.get("chat_agent_id") != agent_id:
                return None, "Request not found"

            workspace_id = agent["workspace_id"]
            member_id = member["id"]
            member_name = member.get("name", "Unknown")
            now = _utc_iso_now()

            request_number = request.get("request_number") or request_id
            attachments = self._parse_json_field(request.get("attachments"), [])
            messages = self._parse_json_field(request.get("messages"), [])
            new_attachments = []

            for fd in file_data_list:
                url, s3_key = await upload_ticket_attachment(
                    workspace_id, agent_id, request_number,
                    fd["file_content"], fd["file_name"], fd["content_type"]
                )
                att = {
                    "id": f"att_{uuid.uuid4().hex[:12]}",
                    "name": fd["file_name"],
                    "size": fd["file_size"],
                    "content_type": fd["content_type"],
                    "url": url,
                    "s3_key": s3_key,
                    "uploaded_by": member_id,
                    "uploaded_by_name": member_name,
                    "uploaded_at": now
                }
                new_attachments.append(att)
                attachments.append(att)

            file_names = ", ".join(fd["file_name"] for fd in file_data_list)
            messages.append({
                "id": str(uuid.uuid4()),
                "sender_id": member_id,
                "sender_name": member_name,
                "message": f"Attached {len(new_attachments)} file(s): {file_names}",
                "action": "attachment",
                "attachments": new_attachments,
                "created_at": now
            })

            updated = await self.repository.update_request(request_id, {
                "attachments": attachments,
                "messages": messages
            })
            if not updated:
                return None, "Failed to update request"

            return new_attachments, None

        except Exception as e:
            logger.error(f"Error uploading attachment: {str(e)}")
            return None, str(e)

    async def public_upload_attachment(
        self, agent_id: str, request_id: str,
        email: Optional[str], profile_id: Optional[str],
        file_data_list: list
    ) -> Tuple[Optional[list], Optional[str]]:
        """Upload multiple files to a request (no auth, for chatbot/requester)."""
        try:
            agent = await self.repository.get_chat_agent(agent_id)
            if not agent:
                return None, "Chat agent not found"
            workspace_id = agent.get("workspace_id")

            if profile_id:
                member = await self.repository.get_member_by_profile_and_workspace(profile_id, workspace_id)
            elif email:
                member = await self.repository.get_member_by_email(workspace_id, email.lower())
            else:
                return None, "Either email or profile_id is required"
            if not member:
                return None, "Member not found"

            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            if request.get("chat_agent_id") != agent_id:
                return None, "Request not found"

            request_number = request.get("request_number") or request_id
            member_id = member["id"]
            member_name = member.get("name", "Unknown")
            now = _utc_iso_now()

            attachments = self._parse_json_field(request.get("attachments"), [])
            messages = self._parse_json_field(request.get("messages"), [])
            new_attachments = []

            for fd in file_data_list:
                url, s3_key = await upload_ticket_attachment(
                    workspace_id, agent_id, request_number,
                    fd["file_content"], fd["file_name"], fd["content_type"]
                )
                att = {
                    "id": f"att_{uuid.uuid4().hex[:12]}",
                    "name": fd["file_name"],
                    "size": fd["file_size"],
                    "content_type": fd["content_type"],
                    "url": url,
                    "s3_key": s3_key,
                    "uploaded_by": member_id,
                    "uploaded_by_name": member_name,
                    "uploaded_at": now
                }
                new_attachments.append(att)
                attachments.append(att)

            file_names = ", ".join(fd["file_name"] for fd in file_data_list)
            messages.append({
                "id": str(uuid.uuid4()),
                "sender_id": member_id,
                "sender_name": member_name,
                "message": f"Attached {len(new_attachments)} file(s): {file_names}",
                "action": "attachment",
                "attachments": new_attachments,
                "created_at": now
            })

            updated = await self.repository.update_request(request_id, {
                "attachments": attachments,
                "messages": messages
            })
            if not updated:
                return None, "Failed to update request"

            return new_attachments, None

        except Exception as e:
            logger.error(f"Error in public upload attachment: {str(e)}")
            return None, str(e)

    async def upload_temp_attachment(
        self, profile_id: str, agent_id: str, file_data_list: list
    ) -> Tuple[Optional[list], Optional[str]]:
        """Upload files to temp storage before request creation (auth required)."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err

            workspace_id = agent["workspace_id"]
            member_id = member["id"]
            member_name = member.get("name", "Unknown")
            now = _utc_iso_now()
            attachments = []

            for fd in file_data_list:
                url, storage_path = await upload_temp_ticket_attachment(
                    workspace_id, agent_id,
                    fd["file_content"], fd["file_name"], fd["content_type"]
                )
                attachments.append({
                    "id": f"att_{uuid.uuid4().hex[:12]}",
                    "name": fd["file_name"],
                    "size": fd["file_size"],
                    "content_type": fd["content_type"],
                    "url": url,
                    "s3_key": storage_path,
                    "storage_path": storage_path,
                    "uploaded_by": member_id,
                    "uploaded_by_name": member_name,
                    "uploaded_at": now
                })

            return attachments, None

        except Exception as e:
            logger.error(f"Error in upload temp attachment: {str(e)}")
            return None, str(e)

    async def delete_attachment(
        self, profile_id: str, agent_id: str, request_id: str, attachment_id: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Delete a single attachment. Only the uploader can delete their own file."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_edit(member)
            if err:
                return None, err

            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            if request.get("chat_agent_id") != agent_id:
                return None, "Request not found"

            member_id = member["id"]
            member_name = member.get("name", "Unknown")
            now = _utc_iso_now()

            attachments = self._parse_json_field(request.get("attachments"), [])
            target = next((a for a in attachments if isinstance(a, dict) and a.get("id") == attachment_id), None)
            if not target:
                return None, "Attachment not found"

            if target.get("uploaded_by") != member_id:
                return None, "You can only delete attachments you uploaded"

            delete_ref = target.get("s3_key") or target.get("url", "")
            await delete_ticket_attachment(delete_ref)

            updated_attachments = [a for a in attachments if not (isinstance(a, dict) and a.get("id") == attachment_id)]

            messages = self._parse_json_field(request.get("messages"), [])
            messages.append({
                "id": str(uuid.uuid4()),
                "sender_id": member_id,
                "sender_name": member_name,
                "message": f"Deleted attachment: {target.get('name', 'file')}",
                "action": "attachment_deleted",
                "created_at": now
            })

            updated = await self.repository.update_request(request_id, {
                "attachments": updated_attachments,
                "messages": messages
            })
            if not updated:
                return None, "Failed to update request"

            return {"attachment_id": attachment_id, "name": target.get("name")}, None

        except Exception as e:
            logger.error(f"Error deleting attachment: {str(e)}")
            return None, str(e)

    async def refresh_attachment_url(
        self, profile_id: str, agent_id: str, request_id: str, attachment_id: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Return a fresh presigned URL for an attachment using its stored s3_key."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error

            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            if request.get("chat_agent_id") != agent_id:
                return None, "Request not found"

            attachments = self._parse_json_field(request.get("attachments"), [])
            target = next(
                (a for a in attachments if isinstance(a, dict) and a.get("id") == attachment_id),
                None,
            )
            if not target:
                return None, "Attachment not found"

            s3_key = target.get("s3_key")
            if not s3_key:
                return None, "Attachment has no stored S3 key; cannot refresh URL"

            fresh_url = generate_presigned_download_url(s3_key)
            return {"attachment_id": attachment_id, "url": fresh_url, "name": target.get("name")}, None

        except Exception as e:
            logger.error(f"Error refreshing attachment URL: {str(e)}")
            return None, str(e)

    # ========================================================================
    # Dashboard/Stats
    # ========================================================================
    
    async def get_dashboard(self, profile_id: str, agent_id: str) -> Tuple[Optional[DashboardResponse], Optional[str]]:
        """Get dashboard with stats, my requests/approvals analytics, and recent requests"""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_view(member)
            if err:
                return None, err
            
            workspace_id = agent["workspace_id"]
            member_id = member["id"]
            
            # Get all stats in parallel
            stats_dict, my_req_dict, my_appr_dict = await asyncio.gather(
                self.repository.get_request_stats(agent_id, workspace_id),
                self.repository.get_my_request_stats(agent_id, member_id),
                self.repository.get_my_approval_stats(agent_id, member_id),
            )
            stats = RequestStats(**stats_dict)
            my_requests = MyRequestStats(**my_req_dict)
            my_approvals = MyApprovalStats(**my_appr_dict)
            
            # Get recent requests
            requests, _ = await self.repository.get_requests_by_agent(
                agent_id, workspace_id, page=1, page_size=5
            )
            recent = await self._build_responses_batch(requests)

            return DashboardResponse(stats=stats, my_requests=my_requests, my_approvals=my_approvals, recent_requests=recent), None
            
        except Exception as e:
            logger.error(f"Error getting dashboard: {str(e)}")
            return None, str(e)
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    async def _build_approval_chain(
        self,
        workspace_id: str,
        start_member_id: Optional[str],
        first_status: str = "pending",
        rest_status: str = "",
        assigned_at: Optional[str] = None,
        sla_deadline: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Build approval chain [{id, name, status, at, assigned_at, sla_deadline, max_approval_amount}].
        First gets first_status + assigned_at/sla_deadline, rest get rest_status."""
        hierarchy_list = await self.repository.get_hierarchy_by_workspace(workspace_id)
        hierarchy_by_level = {}
        for h in hierarchy_list:
            lvl = h.get("level")
            if lvl is not None:
                hdata = h.get("data") or {}
                if isinstance(hdata, str):
                    try:
                        hdata = json.loads(hdata)
                    except json.JSONDecodeError:
                        hdata = {}
                hierarchy_by_level[int(lvl)] = hdata

        chain = []
        seen = set()
        member_id = start_member_id
        first = True
        while member_id and str(member_id) not in seen:
            seen.add(str(member_id))
            member = await self.repository.get_member_by_id(member_id)
            if not member:
                break
            if str(member.get("workspace_id") or "") != str(workspace_id or ""):
                break
            level = member.get("hierarchy_level")
            max_amt_val = None
            if level is not None:
                h_data = hierarchy_by_level.get(int(level), {})
                max_amt_raw = h_data.get("max_approval_amount")
                if max_amt_raw is not None:
                    try:
                        max_amt_val = float(max_amt_raw)
                    except (TypeError, ValueError):
                        max_amt_val = None
            chain.append({
                "id": str(member["id"]),
                "name": member.get("name", "Unknown") or "Unknown",
                "status": first_status if first else rest_status,
                "at": None,
                "auto": False,
                "max_approval_amount": max_amt_val,
                "assigned_at": assigned_at if first else None,
                "sla_deadline": sla_deadline if first else None
            })
            first = False
            member_id = member.get("reports_to")
        return chain

    def _update_approval_chain_entry(
        self,
        chain: List[Dict[str, Any]],
        member_id: str,
        status: str,
        at_val: Optional[str] = None,
        auto: Optional[bool] = None
    ) -> List[Dict[str, Any]]:
        """Update chain entry by member_id. Returns new list."""
        result = []
        for entry in chain:
            e = dict(entry)
            if str(e.get("id", "")) == str(member_id):
                e["status"] = status
                if at_val is not None:
                    e["at"] = at_val
                if auto is not None:
                    e["auto"] = auto
            result.append(e)
        return result

    def _set_approval_chain_pending(
        self, chain: List[Dict[str, Any]], member_id: str,
        assigned_at: Optional[str] = None, sla_deadline: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Set given member's status to pending with assigned_at/sla_deadline, clear others who are not yet acted on."""
        result = []
        for entry in chain:
            e = dict(entry)
            if str(e.get("id", "")) == str(member_id):
                e["status"] = "pending"
                e["at"] = None
                e["assigned_at"] = assigned_at
                e["sla_deadline"] = sla_deadline
            elif e.get("status") not in ("approved", "rejected", "skipped"):
                e["status"] = ""
                e["assigned_at"] = None
                e["sla_deadline"] = None
            result.append(e)
        return result

    def _parse_json_field(self, value: Any, default: Any = None) -> Any:
        """Parse JSON field (history, messages) - handles dict, list, or JSON string from DB"""
        if value is None:
            return default if default is not None else []
        if isinstance(value, (list, dict)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value) if value.strip() else (default if default is not None else [])
            except (json.JSONDecodeError, TypeError):
                return default if default is not None else []
        return default if default is not None else []

    def _get_conversation_id_from_data(self, data: Any) -> Optional[str]:
        """Extract conversation_id from request data (handles dict, JSON string, camelCase)"""
        if data is None:
            return None
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, TypeError):
                logger.debug(f"Failed to parse data as JSON: {data[:100] if data else 'empty'}")
                return None
        if not isinstance(data, dict):
            return None
        conv_id = data.get("conversation_id") or data.get("conversationId")
        return str(conv_id).strip() if conv_id else None

    async def _build_responses_batch(
        self,
        requests: List[Dict[str, Any]],
        include_conversation: bool = False,
        current_member_id: str = None
    ) -> List["RequestResponse"]:
        """Build RequestResponse list with pre-fetched caches. 1 batch member query +
        1 hierarchy query + 1 batch conversation query instead of N*M individual calls."""
        if not requests:
            return []

        member_ids: set = set()
        conv_ids: set = set()
        workspace_id = None

        for r in requests:
            workspace_id = workspace_id or r.get("workspace_id")
            for key in ("raised_by", "raised_to", "current_approver"):
                mid = r.get(key)
                if mid:
                    member_ids.add(str(mid))
            chain = self._parse_json_field(r.get("approval_chain"), [])
            if isinstance(chain, list):
                for e in chain:
                    if isinstance(e, dict) and e.get("id"):
                        member_ids.add(str(e["id"]))
            if include_conversation:
                cid = self._get_conversation_id_from_data(r.get("data"))
                if cid:
                    conv_ids.add(str(cid))

        fetch_tasks: list = [self.repository.get_members_by_ids(list(member_ids))]
        fetch_tasks.append(
            self.repository.get_hierarchy_by_workspace(workspace_id) if workspace_id else _noop_list()
        )
        fetch_tasks.append(
            self.repository.get_conversations_by_ids(list(conv_ids)) if conv_ids else _noop_dict()
        )
        member_cache, hierarchy_cache, conversation_cache = await asyncio.gather(*fetch_tasks)

        h_by_level: Dict[int, Dict] = {}
        if isinstance(hierarchy_cache, list):
            for h in hierarchy_cache:
                lvl = h.get("level")
                if lvl is not None:
                    hdata = h.get("data") or {}
                    if isinstance(hdata, str):
                        try:
                            hdata = json.loads(hdata)
                        except json.JSONDecodeError:
                            hdata = {}
                    h_by_level[int(lvl)] = hdata

        tasks = [
            self._build_request_response(
                r,
                include_conversation=include_conversation,
                current_member_id=current_member_id,
                member_cache=member_cache,
                hierarchy_cache=h_by_level,
                conversation_cache=conversation_cache if include_conversation else None,
            )
            for r in requests
        ]
        return await asyncio.gather(*tasks)

    async def _build_request_response(
        self, request: Dict[str, Any], include_conversation: bool = False,
        current_member_id: str = None,
        member_cache: Dict[str, Dict] = None,
        hierarchy_cache: Dict[int, Dict] = None,
        conversation_cache: Dict[str, list] = None
    ) -> RequestResponse:
        """Build a RequestResponse with resolved names.
        Accepts optional pre-fetched caches to avoid N+1 queries in list endpoints.
        """
        _mc = member_cache or {}

        async def _get_member(mid: str) -> Optional[Dict]:
            if not mid:
                return None
            if mid in _mc:
                return _mc[mid]
            m = await self.repository.get_member_by_id(mid)
            if m:
                _mc[mid] = m
            return m

        raised_by_name = None
        raised_to_name = None
        current_approver_name = None
        raised_by_department = None

        if request.get("raised_by"):
            member = await _get_member(request["raised_by"])
            raised_by_name = member.get("name") if member else None
            raised_by_department = member.get("department") if member else None

        if request.get("raised_to"):
            member = await _get_member(request["raised_to"])
            raised_to_name = member.get("name") if member else None

        if request.get("current_approver"):
            member = await _get_member(request["current_approver"])
            current_approver_name = member.get("name") if member else None

        stored_chain = self._parse_json_field(request.get("approval_chain"), [])
        if stored_chain and isinstance(stored_chain, list):
            approval_chain = [
                {
                    "id": str(e.get("id", "")),
                    "name": e.get("name", "Unknown") or "Unknown",
                    "status": e.get("status", ""),
                    "at": e.get("at"),
                    "auto": e.get("auto", False),
                    "max_approval_amount": e.get("max_approval_amount"),
                    "assigned_at": e.get("assigned_at"),
                    "sla_deadline": e.get("sla_deadline")
                }
                for e in stored_chain if isinstance(e, dict) and e.get("id")
            ]
        else:
            approval_chain = await self._build_approval_chain(
                request["workspace_id"], request.get("current_approver")
            )

        needs_backfill = any(e.get("max_approval_amount") is None for e in approval_chain)
        if needs_backfill and approval_chain:
            h_by_level = hierarchy_cache
            if h_by_level is None:
                hierarchy_list = await self.repository.get_hierarchy_by_workspace(request["workspace_id"])
                h_by_level = {}
                for h in hierarchy_list:
                    lvl = h.get("level")
                    if lvl is not None:
                        hdata = h.get("data") or {}
                        if isinstance(hdata, str):
                            try:
                                hdata = json.loads(hdata)
                            except json.JSONDecodeError:
                                hdata = {}
                        h_by_level[int(lvl)] = hdata
            for entry in approval_chain:
                if entry.get("max_approval_amount") is None:
                    m = await _get_member(entry["id"])
                    if m and m.get("hierarchy_level") is not None:
                        h_data = h_by_level.get(int(m["hierarchy_level"]), {})
                        raw = h_data.get("max_approval_amount")
                        if raw is not None:
                            try:
                                entry["max_approval_amount"] = float(raw)
                            except (TypeError, ValueError):
                                pass

        req_data = self._parse_json_field(request.get("data"), {})
        if isinstance(req_data, dict) and req_data.get("product_id") and not req_data.get("product_name"):
            prod = await self.repository.get_product_by_id(str(req_data["product_id"]))
            if prod and prod.get("name"):
                req_data["product_name"] = prod["name"]

        conversation_history = None
        if include_conversation:
            conv_id = self._get_conversation_id_from_data(request.get("data"))
            if conv_id:
                if conversation_cache is not None:
                    conversation_history = conversation_cache.get(str(conv_id))
                else:
                    conversation_history = await self.repository.get_conversation_by_id(conv_id)
                if conversation_history is None:
                    logger.debug(f"No Chat_Agent_history record for conversation_id={conv_id}")
            elif request.get("data"):
                logger.debug(f"No conversation_id in request data: type={type(request.get('data')).__name__}")

        # Build last_action_message from history (e.g. "Krishan approved. Pending approval from Balakrishnan.")
        last_action_message = None
        history_list = self._parse_json_field(request.get("history"), [])
        if isinstance(history_list, list):
            for entry in reversed(history_list):
                if not isinstance(entry, dict):
                    continue
                if entry.get("action") == "forwarded":
                    tn = entry.get("to_name", "Next approver")
                    reason = entry.get("reason", "")
                    if reason and reason.startswith("Auto skipped to"):
                        last_action_message = reason
                    else:
                        fn = entry.get("from_name", "Manager")
                        last_action_message = f"{fn} approved. Pending approval from {tn}."
                    break
                if entry.get("action") == "auto_skipped":
                    last_action_message = entry.get("reason", "Auto skipped")
                    break
                if entry.get("action") == "sla_breached_final":
                    last_action_message = entry.get("reason", "SLA breached - final approver must take action")
                    break
                if entry.get("action") == "approved":
                    last_action_message = f"{entry.get('by_name', 'Manager')} approved."
                    break
                if entry.get("action") == "rejected":
                    last_action_message = f"{entry.get('by_name', 'Manager')} rejected."
                    break

        # Build action_timeline: list of approved/rejected with by_name, at, comment/reason, attachments
        action_timeline = []
        messages_list = self._parse_json_field(request.get("messages"), [])
        msg_lookup = {}
        for msg in (messages_list if isinstance(messages_list, list) else []):
            if isinstance(msg, dict) and msg.get("sender_id") and msg.get("action"):
                key = (msg["sender_id"], msg["action"], msg.get("created_at"))
                msg_lookup[key] = msg.get("attachments", [])

        for entry in history_list if isinstance(history_list, list) else []:
            if not isinstance(entry, dict):
                continue
            act = entry.get("action")
            if act == "approved":
                atts = msg_lookup.get((entry.get("by_id"), "approved", entry.get("at")), [])
                action_timeline.append({
                    "action": "approved",
                    "by_name": entry.get("by_name", "Unknown"),
                    "at": entry.get("at"),
                    "comment": entry.get("comment"),
                    "attachments": atts
                })
            elif act == "auto_skipped":
                action_timeline.append({
                    "action": "skipped",
                    "by_name": entry.get("by_name", "Unknown"),
                    "at": entry.get("at"),
                    "reason": entry.get("reason"),
                    "auto": entry.get("auto", True)
                })
            elif act == "rejected":
                atts = msg_lookup.get((entry.get("by_id"), "rejected", entry.get("at")), [])
                action_timeline.append({
                    "action": "rejected",
                    "by_name": entry.get("by_name", "Unknown"),
                    "at": entry.get("at"),
                    "reason": entry.get("reason"),
                    "attachments": atts
                })
        
        return RequestResponse(
            id=request["id"],
            request_number=request.get("request_number"),
            workspace_id=request["workspace_id"],
            chat_agent_id=request["chat_agent_id"],
            rule_id=request.get("rule_id"),
            raised_by=request["raised_by"],
            raised_by_name=raised_by_name,
            raised_by_department=raised_by_department,
            raised_to=request.get("raised_to"),
            raised_to_name=raised_to_name,
            current_approver=request.get("current_approver"),
            current_approver_name=current_approver_name,
            approval_chain=approval_chain,
            subject=request["subject"],
            description=request.get("description"),
            request_type=request.get("request_type", "support"),
            category=self._normalize_category(request.get("category")),
            priority=request.get("priority", "normal"),
            data=req_data if isinstance(req_data, dict) else request.get("data", {}),
            attachments=self._enrich_attachments_can_delete(
                self._parse_json_field(request.get("attachments"), []),
                current_member_id
            ),
            status=request.get("status", "pending"),
            current_level=request.get("current_level"),
            required_level=request.get("required_level"),
            messages=self._parse_json_field(request.get("messages"), []),
            history=self._parse_json_field(request.get("history"), []),
            conversation_history=conversation_history,
            action_timeline=action_timeline,
            last_action_message=last_action_message,
            escalation_chain=request.get("escalation_chain", []),
            is_emergency=request.get("is_emergency", False),
            emergency_reason=request.get("emergency_reason"),
            is_overridden=request.get("is_overridden", False),
            overridden_by=request.get("overridden_by"),
            override_reason=request.get("override_reason"),
            approved_by_delegate=request.get("approved_by_delegate", False),
            original_approver=request.get("original_approver"),
            sla_deadline=request.get("sla_deadline"),
            is_sla_breached=request.get("is_sla_breached", False),
            sla_auto_approve=request.get("sla_auto_approve", True),
            auto_approved=request.get("auto_approved", False),
            created_at=request["created_at"],
            updated_at=request.get("updated_at"),
            resolved_at=request.get("resolved_at")
        )
    
    async def _resolve_amount_from_product(
        self, workspace_id: str, agent_id: str, product_id: str, quantity: int,
        rule_id: str = None
    ) -> Tuple[Optional[float], Optional[str], Optional[Dict], Optional[str]]:
        """
        Resolve amount from product_id and quantity using products table.
        Returns (amount, error_message, rule, product_name) - amount is None on error.
        """
        rule = None
        if rule_id:
            rule = await self.repository.get_rule_by_id(rule_id)
        if not rule:
            rule = await self.repository.get_rule_by_agent_and_name(
                workspace_id, agent_id, "DOA CapEx"
            )
        if not rule:
            return None, "Purchase rule not found for this agent", None, None
        product = await self.repository.get_product_by_id(product_id)
        if not product:
            return None, f"Product '{product_id}' not found", None, None
        cost = product.get("cost")
        if cost is None:
            return None, f"Product '{product_id}' has no cost", None, None
        try:
            amount = float(cost) * int(quantity)
        except (TypeError, ValueError):
            return None, "Invalid product cost or quantity", None, None
        if amount < 0:
            return None, "Amount cannot be negative", None, None
        return amount, None, rule, product.get("name")

    async def _get_first_approver_in_chain(
        self, workspace_id: str, raised_by_member_id: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Get first approver in chain (no amount skip). Skips receives_only.
        Returns (first_approver_id, first_approver_name).
        """
        hierarchy_list = await self.repository.get_hierarchy_by_workspace(workspace_id)
        hierarchy_by_level = {}
        for h in hierarchy_list:
            lvl = h.get("level")
            if lvl is not None:
                data = h.get("data") or {}
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        data = {}
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        data = {}
                hierarchy_by_level[int(lvl)] = data

        logger.info(f"[APPROVER_CHAIN] workspace={workspace_id}, member={raised_by_member_id}, hierarchy_levels={len(hierarchy_list)}, parsed={list(hierarchy_by_level.keys())}")
        for lvl, hd in hierarchy_by_level.items():
            logger.info(f"[APPROVER_CHAIN] L{lvl}: can_approve={hd.get('can_approve')}, receives_only={hd.get('receives_only')}, type={type(hd)}")

        member = await self.repository.get_member_by_id(raised_by_member_id)
        if not member:
            logger.warning(f"[APPROVER_CHAIN] Member {raised_by_member_id} not found")
            return None, None
        member_id = member.get("reports_to")
        logger.info(f"[APPROVER_CHAIN] Requester={member.get('name')}, reports_to={member_id}")
        if not member_id:
            logger.warning(f"[APPROVER_CHAIN] Requester has no reports_to")
            return None, None

        seen = set()
        while member_id and str(member_id) not in seen:
            seen.add(str(member_id))
            m = await self.repository.get_member_by_id(member_id)
            if not m:
                logger.warning(f"[APPROVER_CHAIN] Member {member_id} not found in DB")
                break
            if str(m.get("workspace_id") or "") != str(workspace_id or ""):
                logger.warning(f"[APPROVER_CHAIN] Workspace mismatch: member_ws={m.get('workspace_id')}, expected={workspace_id}")
                break
            level = m.get("hierarchy_level")
            if level is not None:
                level = int(level)
            h_data = hierarchy_by_level.get(level, {})
            can_approve = h_data.get("can_approve")
            receives_only = h_data.get("receives_only")
            logger.info(f"[APPROVER_CHAIN] Checking {m.get('name')} (L{level}): can_approve={can_approve}({type(can_approve).__name__}), receives_only={receives_only}")
            if can_approve:
                logger.info(f"[APPROVER_CHAIN] Found approver: {m.get('name')} ({m['id']})")
                return m["id"], m.get("name", "Unknown")
            member_id = m.get("reports_to")
        logger.warning(f"[APPROVER_CHAIN] No approver found after traversing chain")
        return None, None

    async def _build_full_approval_chain_sequential(
        self, workspace_id: str, raised_by_member_id: str, first_approver_id: Optional[str], amount: float,
        assigned_at: Optional[str] = None, sla_deadline: Optional[str] = None,
        ignore_amount: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Build approval chain from requester's reports_to upward.
        If ignore_amount=False (default): stops when amount <= max_approval_amount.
        If ignore_amount=True: includes ALL approvers up the full chain (for approval_chain type rules).
        First (pending) entry gets assigned_at + sla_deadline.
        """
        chain = []
        seen = set()
        member = await self.repository.get_member_by_id(raised_by_member_id)
        if not member:
            return []
        member_id = member.get("reports_to")
        if not member_id:
            return []

        hierarchy_list = await self.repository.get_hierarchy_by_workspace(workspace_id)
        hierarchy_by_level = {}
        for h in hierarchy_list:
            lvl = h.get("level")
            if lvl is not None:
                data = h.get("data") or {}
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        data = {}
                hierarchy_by_level[int(lvl)] = data

        while member_id and str(member_id) not in seen:
            seen.add(str(member_id))
            m = await self.repository.get_member_by_id(member_id)
            if not m or str(m.get("workspace_id") or "") != str(workspace_id or ""):
                break
            level = m.get("hierarchy_level")
            if level is not None:
                level = int(level)
            h_data = hierarchy_by_level.get(level, {})
            if h_data.get("can_approve") or h_data.get("receives_only"):
                max_amt_raw = h_data.get("max_approval_amount")
                max_amt_val = None
                if max_amt_raw is not None:
                    try:
                        max_amt_val = float(max_amt_raw)
                    except (TypeError, ValueError):
                        max_amt_val = 0
                is_first_approver = str(m["id"]) == str(first_approver_id)
                chain.append({
                    "id": str(m["id"]),
                    "name": m.get("name", "Unknown") or "Unknown",
                    "status": "pending" if is_first_approver else "",
                    "at": None,
                    "auto": False,
                    "max_approval_amount": max_amt_val,
                    "assigned_at": assigned_at if is_first_approver else None,
                    "sla_deadline": sla_deadline if is_first_approver else None
                })
                if not ignore_amount and h_data.get("can_approve") and not h_data.get("receives_only"):
                    if max_amt_val is not None and amount <= max_amt_val:
                        logger.info(f"[CHAIN] Stopping at L{level} {m.get('name')}: amount={amount} <= max={max_amt_val}, ignore_amount={ignore_amount}")
                        break
                    elif max_amt_val is None:
                        logger.info(f"[CHAIN] Stopping at L{level} {m.get('name')}: final approver (max=None), ignore_amount={ignore_amount}")
                        break
            member_id = m.get("reports_to")
        logger.info(f"[CHAIN] Built chain with {len(chain)} entries, ignore_amount={ignore_amount}")
        return chain

    async def _build_explicit_chain(
        self, chain_config: List[Dict[str, Any]], assigned_at: Optional[str] = None,
        sla_deadline: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
        """
        Build approval chain from explicit rule-defined member list (no reports_to traversal).
        Used for payment_request and other explicit_chain rule types.
        Returns (approval_chain, first_approver_id, first_approver_name).
        """
        chain = []
        first_approver_id = None
        first_approver_name = None

        for idx, entry in enumerate(chain_config):
            mid = entry.get("member_id")
            role = entry.get("role", "Unknown")
            if not mid:
                continue
            m = await self.repository.get_member_by_id(mid)
            name = m.get("name", role) if m else role
            is_first = (idx == 0)
            if is_first:
                first_approver_id = mid
                first_approver_name = name
            chain.append({
                "id": str(mid),
                "name": name,
                "role": role,
                "status": "pending" if is_first else "",
                "at": None,
                "auto": False,
                "max_approval_amount": entry.get("max_amount"),
                "max_amount": entry.get("max_amount"),
                "assigned_at": assigned_at if is_first else None,
                "sla_deadline": sla_deadline if is_first else None
            })

        logger.info(f"[EXPLICIT_CHAIN] Built chain with {len(chain)} entries, first={first_approver_name}")
        return chain, first_approver_id, first_approver_name

    async def _build_approval_chain_with_amount_skip(
        self, workspace_id: str, raised_by_member_id: str, amount: float,
        assigned_at: Optional[str] = None, sla_deadline: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
        """
        Build approval chain by walking reports_to, skipping members where amount > max_approval_amount.
        Returns (chain, first_approver_id, first_approver_name). First entry gets assigned_at/sla_deadline.
        """
        hierarchy_list = await self.repository.get_hierarchy_by_workspace(workspace_id)
        hierarchy_by_level = {}
        for h in hierarchy_list:
            lvl = h.get("level")
            if lvl is not None:
                data = h.get("data") or {}
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        data = {}
                hierarchy_by_level[int(lvl)] = data

        chain = []
        seen = set()
        member_id = raised_by_member_id
        first_approver_id = None
        first_approver_name = None

        # Start from raised_by's reports_to (their manager)
        member = await self.repository.get_member_by_id(member_id)
        if not member:
            return [], None, None
        member_id = member.get("reports_to")
        if not member_id:
            return [], None, None

        while member_id and str(member_id) not in seen:
            seen.add(str(member_id))
            m = await self.repository.get_member_by_id(member_id)
            if not m or str(m.get("workspace_id") or "") != str(workspace_id or ""):
                break
            level = m.get("hierarchy_level")
            if level is not None:
                level = int(level)
            h_data = hierarchy_by_level.get(level, {})
            max_amt = h_data.get("max_approval_amount")
            can_approve = h_data.get("can_approve", True)
            if max_amt is not None:
                try:
                    max_amt = float(max_amt)
                except (TypeError, ValueError):
                    max_amt = 0
            else:
                max_amt = float("inf")  # null = unlimited
            if can_approve and amount <= max_amt:
                is_first = first_approver_id is None
                chain.append({
                    "id": str(m["id"]),
                    "name": m.get("name", "Unknown") or "Unknown",
                    "status": "pending" if is_first else "",
                    "at": None,
                    "auto": False,
                    "max_approval_amount": max_amt if max_amt != float("inf") else None,
                    "assigned_at": assigned_at if is_first else None,
                    "sla_deadline": sla_deadline if is_first else None
                })
                if is_first:
                    first_approver_id = m["id"]
                    first_approver_name = m.get("name", "Unknown")
            member_id = m.get("reports_to")
        return chain, first_approver_id, first_approver_name

    async def _calculate_routing_from_rule(
        self, 
        rule: Dict, 
        request_data: Dict, 
        workspace_id: str,
        requester_level: int
    ) -> Dict[str, Any]:
        """Calculate routing based on rule configuration"""
        rule_data = rule.get("data", {})
        if isinstance(rule_data, str):
            try:
                rule_data = json.loads(rule_data)
            except json.JSONDecodeError:
                rule_data = {}
        rule_type = rule_data.get("type", "simple")
        
        required_level = None
        
        if rule_type == "amount_based":
            # Get amount from request data
            field = rule_data.get("field", "amount")
            amount = request_data.get(field, 0)
            amount = float(amount) if amount is not None else 0
            levels = rule_data.get("levels", {})
            
            # Find required level based on amount
            for level_str, config in sorted(levels.items(), key=lambda x: int(x[0])):
                level = int(level_str)
                max_amount = config.get("max")
                
                if max_amount is None or amount <= max_amount:
                    required_level = level
                    break
            
            if required_level is None:
                # Amount exceeds all limits, use highest level
                required_level = max(int(l) for l in levels.keys())
        
        elif rule_type == "simple":
            required_level = rule_data.get("min_level", requester_level + 1)
        
        else:
            # Default: next level above requester
            required_level = requester_level + 1
        
        # Find approver at required level
        approver = await self.repository.get_member_by_level(workspace_id, required_level)
        
        return {
            "required_level": required_level,
            "approver_id": approver["id"] if approver else None,
            "approver_name": approver.get("name") if approver else None
        }
    
    async def _check_delegation(self, original_approver_id: str, actor_id: str) -> bool:
        """Check if actor has active delegation from original approver"""
        if not original_approver_id:
            return False
        
        original = await self.repository.get_member_by_id(original_approver_id)
        if not original:
            return False
        
        delegations = original.get("delegations", [])
        now = datetime.now(timezone.utc)
        
        for delegation in delegations:
            if delegation.get("delegated_to") == actor_id:
                start = datetime.fromisoformat(delegation.get("start", "").replace("Z", "+00:00"))
                end = datetime.fromisoformat(delegation.get("end", "").replace("Z", "+00:00"))
                
                if start <= now <= end and delegation.get("is_active", True):
                    return True
        
        return False
    
    async def _get_effective_member_id(self, member: Dict) -> str:
        """Get effective member ID considering delegation"""
        # For now, just return the member's own ID
        # In a full implementation, we'd check if anyone has delegated to this member
        return member["id"]
    
    async def process_sla_auto_approvals(
        self, agent_id: str
    ) -> Tuple[int, Optional[str]]:
        """Auto-approve or move to next level for pending requests past sla_deadline."""
        try:
            overdue = await self.repository.get_overdue_pending_requests(agent_id)
            count = 0
            now = _utc_iso_now()
            for req in overdue:
                history = req.get("history", [])
                current_approver_id = req.get("current_approver")
                current_approver_obj = await self.repository.get_member_by_id(current_approver_id) if current_approver_id else None
                next_reports_to = current_approver_obj.get("reports_to") if current_approver_obj else None

                if next_reports_to:
                    next_approver = await self.repository.get_member_by_id(next_reports_to)
                    if next_approver:
                        next_approver_name = next_approver.get("name", "Unknown")
                        history.append({
                            "action": "auto_skipped",
                            "by_id": current_approver_id,
                            "by_name": current_approver_obj.get("name", "Unknown") if current_approver_obj else None,
                            "reason": f"Auto skipped to {next_approver_name}",
                            "auto": True,
                            "at": now
                        })
                        history.append({
                            "action": "forwarded",
                            "from_id": current_approver_id,
                            "to_id": next_approver["id"],
                            "to_name": next_approver_name,
                            "reason": f"Auto skipped to {next_approver_name}",
                            "at": now
                        })
                        # Update chain: mark current approver as skipped (SLA), next as pending with SLA
                        sla_req_data = self._parse_json_field(req.get("data"), {})
                        skip_sla_hours = sla_req_data.get("sla_hours", 48) if isinstance(sla_req_data, dict) else 48
                        new_sla = _utc_iso(datetime.now(timezone.utc) + timedelta(hours=skip_sla_hours))
                        existing_chain = self._parse_json_field(req.get("approval_chain"), [])
                        if existing_chain and isinstance(existing_chain, list):
                            chain = self._update_approval_chain_entry(
                                existing_chain, current_approver_id, "skipped", now, auto=True
                            )
                            chain = self._set_approval_chain_pending(
                                chain, next_approver["id"],
                                assigned_at=now, sla_deadline=new_sla
                            )
                        else:
                            chain = await self._build_approval_chain(
                                req["workspace_id"], next_approver["id"], "pending", "",
                                assigned_at=now, sla_deadline=new_sla
                            )
                        updated = await self.repository.update_request(req["id"], {
                            "status": "pending",
                            "current_approver": next_approver["id"],
                            "raised_to": next_approver["id"],
                            "current_level": next_approver.get("hierarchy_level"),
                            "sla_deadline": new_sla,
                            "is_sla_breached": True,
                            "approval_chain": chain,
                            "history": history
                        })
                        if updated:
                            requester_m = await self.repository.get_member_by_id(req.get("raised_by"))
                            asyncio.create_task(notify_sla_auto_skipped(
                                requester_email=requester_m.get("email") if requester_m else None,
                                next_approver_email=next_approver.get("email"),
                                request_number=req.get("request_number", req["id"]),
                                subject=req.get("subject", ""),
                                skipped_name=current_approver_obj.get("name", "Unknown") if current_approver_obj else "Unknown",
                                next_name=next_approver_name,
                            ))
                    else:
                        # No next approver found - final approver: do NOT auto-approve, only mark breached
                        if not any(h.get("action") == "sla_breached_final" for h in history if isinstance(h, dict)):
                            history.append({
                                "action": "sla_breached_final",
                                "by_id": current_approver_id,
                                "by_name": current_approver_obj.get("name", "Unknown") if current_approver_obj else None,
                                "reason": "SLA breached - final approver must take action",
                                "at": now
                            })
                            updated = await self.repository.update_request(req["id"], {
                                "is_sla_breached": True,
                                "history": history
                            })
                        else:
                            updated = False
                else:
                    # No next level - final approver: do NOT auto-approve, only mark breached
                    if not any(h.get("action") == "sla_breached_final" for h in history if isinstance(h, dict)):
                        history.append({
                            "action": "sla_breached_final",
                            "by_id": current_approver_id,
                            "by_name": current_approver_obj.get("name", "Unknown") if current_approver_obj else None,
                            "reason": "SLA breached - final approver must take action",
                            "at": now
                        })
                        updated = await self.repository.update_request(req["id"], {
                            "is_sla_breached": True,
                            "history": history
                        })
                    else:
                        updated = False
                if updated:
                    count += 1
                    logger.info(f"SLA processed request {req.get('request_number', req['id'])}")
            return count, None
        except Exception as e:
            logger.error(f"Error in process_sla_auto_approvals: {str(e)}")
            return 0, str(e)

    async def process_sla_auto_approvals_all(self) -> Tuple[int, Optional[str]]:
        """Process SLA for all agents that have overdue requests. Returns total count."""
        try:
            agent_ids = await self.repository.get_agent_ids_with_overdue_requests()
            total = 0
            for agent_id in agent_ids:
                count, err = await self.process_sla_auto_approvals(agent_id)
                if err:
                    logger.warning(f"SLA process failed for agent {agent_id}: {err}")
                else:
                    total += count
            return total, None
        except Exception as e:
            logger.error(f"Error in process_sla_auto_approvals_all: {str(e)}")
            return 0, str(e)

    # ========================================================================
    # Products API (for agent product-based purchase flow)
    # ========================================================================
    
    async def get_products_for_agent(
        self, profile_id: str, agent_id: str,
        category: Optional[str] = None, search: Optional[str] = None
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Get products from products table. Auth required."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            err = self._check_tickets_view(member)
            if err:
                return None, err
            products = await self.repository.get_products(
                agent["workspace_id"], agent_id, category=category, search=search
            )
            return products, None
        except Exception as e:
            logger.error(f"Error getting products: {str(e)}")
            return None, str(e)

    async def get_products_for_agent_public(
        self, agent_id: str,
        category: Optional[str] = None, search: Optional[str] = None
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """Get products from products table. No auth (for chatbot)."""
        try:
            agent = await self.repository.get_chat_agent(agent_id)
            if not agent:
                return None, "Chat agent not found"
            products = await self.repository.get_products(
                agent["workspace_id"], agent_id, category=category, search=search
            )
            return products, None
        except Exception as e:
            logger.error(f"Error getting products: {str(e)}")
            return None, str(e)

    async def get_product_categories_public(
        self, agent_id: str
    ) -> Tuple[Optional[List[str]], Optional[str]]:
        """Get distinct product categories. No auth (for chatbot)."""
        try:
            agent = await self.repository.get_chat_agent(agent_id)
            if not agent:
                return None, "Chat agent not found"
            categories = await self.repository.get_product_categories(agent["workspace_id"], agent_id)
            return categories, None
        except Exception as e:
            logger.error(f"Error getting categories: {str(e)}")
            return None, str(e)

    async def get_product_categories(
        self, profile_id: str, agent_id: str
    ) -> Tuple[Optional[List[str]], Optional[str]]:
        """Get distinct product categories. Auth required."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            categories = await self.repository.get_product_categories(agent["workspace_id"], agent_id)
            return categories, None
        except Exception as e:
            logger.error(f"Error getting categories: {str(e)}")
            return None, str(e)

    async def add_product(
        self, profile_id: str, agent_id: str, name: str, cost: float,
        aliases: Optional[List[str]] = None, category: Optional[str] = None,
        fields: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Add product to products table. Auth required."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            product_data = {
                "workspace_id": agent["workspace_id"],
                "chat_agent_id": agent_id,
                "name": name,
                "cost": float(cost),
                "aliases": aliases or [name.lower()],
                "category": category or "General",
                "fields": fields or [],
            }
            product = await self.repository.create_product(product_data)
            if not product:
                return None, "Failed to create product"
            return product, None
        except Exception as e:
            logger.error(f"Error adding product: {str(e)}")
            return None, str(e)

    async def update_product(
        self, profile_id: str, agent_id: str, product_id: str,
        name: Optional[str] = None, cost: Optional[float] = None,
        aliases: Optional[List[str]] = None, category: Optional[str] = None,
        fields: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Update an existing product. Auth required."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return None, error
            existing = await self.repository.get_product_by_id(product_id)
            if not existing:
                return None, f"Product '{product_id}' not found"
            if str(existing.get("workspace_id", "")) != str(agent["workspace_id"]):
                return None, "Product does not belong to this workspace"
            update_data = {}
            if name is not None:
                update_data["name"] = name
            if cost is not None:
                update_data["cost"] = float(cost)
            if aliases is not None:
                update_data["aliases"] = aliases
            if category is not None:
                update_data["category"] = category
            if fields is not None:
                update_data["fields"] = fields
            if not update_data:
                return existing, None
            product = await self.repository.update_product(product_id, update_data)
            if not product:
                return None, "Failed to update product"
            return product, None
        except Exception as e:
            logger.error(f"Error updating product: {str(e)}")
            return None, str(e)

    async def remove_product(
        self, profile_id: str, agent_id: str, product_id: str
    ) -> Tuple[bool, Optional[str]]:
        """Soft-delete a product. Auth required."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return False, error
            existing = await self.repository.get_product_by_id(product_id)
            if not existing:
                return False, f"Product '{product_id}' not found"
            result = await self.repository.delete_product(product_id)
            if not result:
                return False, "Failed to delete product"
            return True, None
        except Exception as e:
            logger.error(f"Error removing product: {str(e)}")
            return False, str(e)

    async def remove_products_bulk(
        self, profile_id: str, agent_id: str, product_ids: List[str]
    ) -> Tuple[int, Optional[str]]:
        """Soft-delete multiple products. Returns count removed."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return 0, error
            count = await self.repository.delete_products_bulk(product_ids)
            if count == 0:
                return 0, "No matching products found"
            return count, None
        except Exception as e:
            logger.error(f"Error bulk removing products: {str(e)}")
            return 0, str(e)

    async def bulk_import_products(
        self, profile_id: str, agent_id: str, products_list: List[Dict[str, Any]]
    ) -> Tuple[int, Optional[str]]:
        """Bulk import products from JSON array. Auth required."""
        try:
            agent, member, error = await self.get_context(profile_id, agent_id)
            if error:
                return 0, error
            workspace_id = agent["workspace_id"]
            rows = []
            for p in products_list:
                rows.append({
                    "workspace_id": workspace_id,
                    "chat_agent_id": agent_id,
                    "name": p.get("name", ""),
                    "cost": float(p.get("cost", 0)),
                    "aliases": p.get("aliases", []),
                    "category": p.get("category", "General"),
                    "fields": p.get("fields", []),
                })
            count = await self.repository.create_products_bulk(rows)
            return count, None
        except Exception as e:
            logger.error(f"Error bulk importing products: {str(e)}")
            return 0, str(e)

    async def public_finalize_request(
        self,
        agent_id: str,
        request_id: str,
        email: Optional[str],
        profile_id: Optional[str],
        specifications: Dict[str, Any],
        conversation_id: Optional[str]
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Finalize a draft request from chatbot (no auth). Use email OR profile_id to identify user."""
        try:
            agent = await self.repository.get_chat_agent(agent_id)
            if not agent:
                return None, "Chat agent not found"

            workspace_id = agent.get("workspace_id")

            if profile_id:
                member = await self.repository.get_member_by_profile_and_workspace(profile_id, workspace_id)
            else:
                if not email:
                    return None, "Either email or profile_id is required"
                member = await self.repository.get_member_by_email(workspace_id, email.lower())

            if not member:
                return None, "Member not found"

            member_id = member["id"]
            member_name = member.get("name", "Unknown")
            member_level = member.get("hierarchy_level", 1)

            request = await self.repository.get_request_by_id(request_id)
            if not request:
                return None, "Request not found"
            if request.get("chat_agent_id") != agent_id:
                return None, "Request not found"
            if request.get("status") != "draft":
                return None, "Only draft requests can be finalized"
            if request.get("raised_by") != member_id:
                return None, "Only the requester can finalize their draft"

            req_data = request.get("data") or {}
            if isinstance(req_data, str):
                try:
                    req_data = json.loads(req_data)
                except (json.JSONDecodeError, TypeError):
                    req_data = {}

            if specifications:
                req_data["specifications"] = specifications
            if conversation_id:
                req_data["conversation_id"] = conversation_id

            product_id = req_data.get("product_id")
            amount = req_data.get("amount", 0)

            current_approver = None
            current_approver_name = None
            sla_hours = 48
            approver_member = None

            ignore_amount = False
            if product_id:
                rule_row = request.get("rule_id")
                if rule_row:
                    rule = await self.repository.get_rule_by_id(rule_row)
                    if rule:
                        rdata = rule.get("data") or {}
                        if isinstance(rdata, str):
                            try:
                                rdata = json.loads(rdata)
                            except json.JSONDecodeError:
                                rdata = {}
                        sla_hours = rdata.get("sla_hours", 48)
                        if rule.get("rule_type") == "approval_chain":
                            ignore_amount = True
                        logger.info(f"[PUBLIC_FINALIZE] rule_type={rule.get('rule_type')}, ignore_amount={ignore_amount}, sla_hours={sla_hours}")

                if self.APPROVAL_FLOW == "sequential":
                    current_approver, current_approver_name = await self._get_first_approver_in_chain(
                        workspace_id, member_id
                    )
                else:
                    chain, current_approver, current_approver_name = await self._build_approval_chain_with_amount_skip(
                        workspace_id, member_id, amount
                    )

            if not current_approver:
                reports_to = member.get("reports_to")
                if reports_to:
                    manager = await self.repository.get_member_by_id(reports_to)
                    if manager:
                        current_approver = manager["id"]
                        current_approver_name = manager.get("name")

            sla_deadline = datetime.now(timezone.utc) + timedelta(hours=sla_hours)
            req_data["sla_hours"] = sla_hours

            current_level = member_level
            if current_approver:
                approver_member = await self.repository.get_member_by_id(current_approver)
                if approver_member:
                    current_level = approver_member.get("hierarchy_level", member_level)

            now = _utc_iso_now()
            sla_deadline_str = _utc_iso(sla_deadline)

            approval_chain = []
            if product_id and current_approver:
                if self.APPROVAL_FLOW == "sequential":
                    approval_chain = await self._build_full_approval_chain_sequential(
                        workspace_id, member_id, current_approver, amount,
                        assigned_at=now, sla_deadline=sla_deadline_str,
                        ignore_amount=ignore_amount
                    )
                else:
                    chain, _, _ = await self._build_approval_chain_with_amount_skip(
                        workspace_id, member_id, amount,
                        assigned_at=now, sla_deadline=sla_deadline_str
                    )
                    approval_chain = chain
            elif current_approver:
                approval_chain = await self._build_approval_chain(
                    workspace_id, current_approver,
                    assigned_at=now, sla_deadline=sla_deadline_str
                )

            history = self._parse_json_field(request.get("history"), [])
            history.append({"action": "finalized", "by_id": member_id, "by_name": member_name, "at": now})
            if current_approver:
                history.append({
                    "action": "auto_assigned",
                    "to_id": current_approver,
                    "to_name": current_approver_name,
                    "reason": "Based on hierarchy/rule",
                    "at": now
                })

            update_data = {
                "status": "pending",
                "data": req_data,
                "raised_to": current_approver,
                "current_approver": current_approver,
                "current_level": current_level,
                "approval_chain": approval_chain,
                "sla_deadline": sla_deadline_str,
                "history": history,
            }

            updated = await self.repository.update_request(request_id, update_data)
            if not updated:
                return None, "Failed to finalize request"

            logger.info(f"[PUBLIC_FINALIZE] Draft {request_id} finalized to pending (approver={current_approver_name})")

            asyncio.create_task(notify_request_created(
                requester_email=member.get("email"),
                approver_email=approver_member.get("email") if approver_member else None,
                request_number=updated.get("request_number", updated["id"]),
                subject=updated.get("subject", ""),
                raised_by_name=member_name,
            ))

            return {
                "id": updated["id"],
                "request_number": updated.get("request_number"),
                "subject": updated.get("subject"),
                "status": updated.get("status"),
                "current_approver_name": current_approver_name,
                "message": "Request finalized and submitted for approval"
            }, None

        except Exception as e:
            logger.error(f"Error in public finalize: {str(e)}")
            return None, f"Failed to finalize request: {str(e)}"

    # ========================================================================
    # Public Endpoints (No Auth - For Chatbot)
    # ========================================================================
    
    async def public_create_request(
        self, 
        agent_id: str, 
        email: Optional[str],
        profile_id: Optional[str],
        name: Optional[str],
        phone: Optional[str],
        subject: Optional[str],
        description: Optional[str],
        request_type: str,
        category: Optional[str],
        priority: str,
        quantity: Optional[int] = None,
        conversation_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Create request from chatbot (no auth). Use email OR profile_id to identify user."""
        try:
            # Get chat agent
            agent = await self.repository.get_chat_agent(agent_id)
            if not agent:
                return None, "Chat agent not found"
            
            workspace_id = agent.get("workspace_id")
            
            # Get member: prefer profile_id if provided, else use email
            if profile_id:
                member = await self.repository.get_member_by_profile_and_workspace(profile_id, workspace_id)
            else:
                if not email:
                    return None, "Either email or profile_id is required"
                member = await self.repository.get_member_by_email(workspace_id, email.lower())
            
            if not member:
                return None, "Member not found. Your email/profile must be registered in this workspace. Contact your admin."
            
            member_id = member["id"]
            member_name = member.get("name") or name or "Unknown"
            member_level = member.get("hierarchy_level", 1)
            
            # Check eligibility: Use MIN_LEVEL_PUBLIC for chatbot (configurable via ALLOW_PUBLIC_REQUEST_MIN_LEVEL)
            min_level = self.MIN_LEVEL_PUBLIC
            if member_level < min_level:
                return None, (
                    f"You don't have the access to raise a request (level {member_level} < {min_level}). "
                    "Please ensure your account is added to this workspace with proper hierarchy. Contact your admin."
                )
            
            # Find approver: product-based (skip logic) OR reports_to
            current_approver = None
            current_approver_name = None
            req_data = dict(data or {})
            if quantity is not None:
                req_data["quantity"] = quantity
            product_id = req_data.get("product_id")
            qty = req_data.get("quantity", 1)
            
            logger.info(f"[PUBLIC_CREATE] member={member_name}({member_id}), product_id={product_id}, quantity={qty}, flow={self.APPROVAL_FLOW}")
            
            if product_id and qty is not None:
                amount, err, rule, prod_name = await self._resolve_amount_from_product(
                    workspace_id, agent_id, str(product_id), int(qty)
                )
                if err:
                    return None, err
                req_data["amount"] = amount
                if prod_name:
                    req_data["product_name"] = prod_name
                logger.info(f"[PUBLIC_CREATE] Product resolved: amount={amount}, product_name={prod_name}")
                if self.APPROVAL_FLOW == "sequential":
                    current_approver, current_approver_name = await self._get_first_approver_in_chain(
                        workspace_id, member_id
                    )
                    if not current_approver:
                        logger.warning(f"[PUBLIC_CREATE] _get_first_approver_in_chain returned None, falling back to reports_to")
                else:
                    chain, current_approver, current_approver_name = await self._build_approval_chain_with_amount_skip(
                        workspace_id, member_id, amount
                    )
                    if not current_approver:
                        logger.warning(f"[PUBLIC_CREATE] _build_approval_chain returned None, falling back to reports_to")
            
            if not current_approver:
                reports_to_id = member.get("reports_to")
                logger.info(f"[PUBLIC_CREATE] Fallback to reports_to: {reports_to_id}")
                if reports_to_id:
                    manager = await self.repository.get_member_by_id(reports_to_id)
                    if manager:
                        current_approver = manager["id"]
                        current_approver_name = manager.get("name")
                        logger.info(f"[PUBLIC_CREATE] Assigned to manager: {current_approver_name}")
                    else:
                        return None, f"Manager not found (reports_to ID: {reports_to_id})"
                else:
                    return None, f"You don't have a manager assigned (reports_to is null). Please contact admin."
            
            # Determine current_level: use approver's level if assigned, otherwise creator's level
            current_level = member_level
            if current_approver:
                approver_member = await self.repository.get_member_by_id(current_approver)
                if approver_member:
                    current_level = approver_member.get("hierarchy_level", member_level)
            
            # Calculate SLA deadline (48 hours default)
            sla_hours = 48
            sla_deadline = datetime.now(timezone.utc) + timedelta(hours=sla_hours)
            
            now = _utc_iso_now()
            sla_deadline_str = _utc_iso(sla_deadline)
            
            # Auto-generate subject when product is resolved
            resolved_subject = subject
            prod_name_resolved = req_data.get("product_name")
            if prod_name_resolved:
                resolved_subject = f"Request for {prod_name_resolved} ({qty})"
            if not resolved_subject:
                resolved_subject = "New Request"
            
            # Merge conversation_id, source, and sla_hours into data
            request_data = {**req_data, "source": "chatbot", "sla_hours": sla_hours}
            if conversation_id:
                request_data["conversation_id"] = conversation_id

            # Extract pre-uploaded temp attachments from data.attachments
            temp_attachments = req_data.pop("attachments", []) or []
            request_data.pop("attachments", None)
            
            # Build request data
            db_data = {
                "workspace_id": workspace_id,
                "chat_agent_id": agent_id,
                "raised_by": member_id,
                "raised_to": current_approver,
                "current_approver": current_approver,
                "subject": resolved_subject,
                "description": description,
                "request_type": request_type,
                "category": category or "doa",
                "priority": priority,
                "data": request_data,
                "attachments": [],
                "status": "pending",
                "current_level": current_level,
                "sla_deadline": sla_deadline_str,
                "sla_auto_approve": (data or {}).get("sla_auto_approve", True),
                "messages": [],
                "history": [
                    {
                        "action": "created",
                        "by_id": member_id,
                        "by_name": member_name,
                        "source": "chatbot",
                        "at": now
                    }
                ],
                "escalation_chain": []
            }
            
            if current_approver:
                db_data["history"].append({
                    "action": "auto_assigned",
                    "to_id": current_approver,
                    "to_name": current_approver_name,
                    "reason": "Auto-assigned to support team",
                    "at": now
                })
            
            if product_id and qty is not None and current_approver:
                if self.APPROVAL_FLOW == "sequential":
                    db_data["approval_chain"] = await self._build_full_approval_chain_sequential(
                        workspace_id, member_id, current_approver, req_data.get("amount", 0),
                        assigned_at=now, sla_deadline=sla_deadline_str
                    )
                else:
                    chain, _, _ = await self._build_approval_chain_with_amount_skip(
                        workspace_id, member_id, req_data.get("amount", 0),
                        assigned_at=now, sla_deadline=sla_deadline_str
                    )
                    db_data["approval_chain"] = chain
            else:
                db_data["approval_chain"] = await self._build_approval_chain(
                    workspace_id, current_approver,
                    assigned_at=now, sla_deadline=sla_deadline_str
                )
            
            # Create in database
            created = await self.repository.create_request(db_data)
            if not created:
                return None, "Failed to create request"
            
            # Move temp attachments to request folder (fire-and-forget)
            if temp_attachments:
                asyncio.create_task(self._move_temp_attachments_to_request(
                    created["id"], workspace_id, agent_id, member_id, member_name,
                    temp_attachments
                ))

            # Email notification (fire-and-forget)
            approver_m = await self.repository.get_member_by_id(current_approver) if current_approver else None
            asyncio.create_task(notify_request_created(
                requester_email=member.get("email"),
                approver_email=approver_m.get("email") if approver_m else None,
                request_number=created.get("request_number", created["id"]),
                subject=resolved_subject,
                raised_by_name=member_name,
            ))
            
            approval_chain = db_data.get("approval_chain") or await self._build_approval_chain(workspace_id, current_approver)
            return {
                "id": created["id"],
                "request_number": created.get("request_number"),
                "subject": created["subject"],
                "status": created["status"],
                "priority": created["priority"],
                "created_at": created["created_at"],
                "current_approver_name": current_approver_name,
                "raised_by_name": member_name,
                "raised_by_department": member.get("department") if member else None,
                "approval_chain": approval_chain,
                "message": f"Your request has been submitted successfully. Reference number: {created.get('request_number', created['id'])}"
            }, None

        except Exception as e:
            logger.error(f"Error in public_create_request: {str(e)}")
            return None, f"Failed to create request: {str(e)}"
    
    async def public_get_status(
        self, 
        agent_id: str, 
        request_number: str
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Get ticket status by request number (no auth)"""
        try:
            request = await self.repository.get_request_by_number(agent_id, request_number)
            if not request:
                return None, "Request not found"
            
            current_approver_name = None
            raised_by_name = None
            raised_by_department = None
            if request.get("current_approver"):
                approver = await self.repository.get_member_by_id(request["current_approver"])
                current_approver_name = approver.get("name") if approver else None
            if request.get("raised_by"):
                member = await self.repository.get_member_by_id(request["raised_by"])
                raised_by_name = member.get("name") if member else None
                raised_by_department = member.get("department") if member else None
            messages = request.get("messages", [])
            last_message = messages[-1].get("message") if messages else None

            return {
                "request_number": request.get("request_number"),
                "subject": request["subject"],
                "status": request["status"],
                "priority": request["priority"],
                "current_approver_name": current_approver_name,
                "raised_by_name": raised_by_name,
                "raised_by_department": raised_by_department,
                "created_at": request["created_at"],
                "updated_at": request.get("updated_at"),
                "last_message": last_message
            }, None

        except Exception as e:
            logger.error(f"Error in public_get_status: {str(e)}")
            return None, str(e)
    
    async def public_get_my_tickets(
        self, 
        agent_id: str, 
        email: str,
        page: int = 1,
        page_size: int = 10
    ) -> Tuple[Optional[Dict], Optional[str]]:
        """Get user's tickets by email (no auth)"""
        try:
            # Get agent to get workspace_id
            agent = await self.repository.get_chat_agent(agent_id)
            if not agent:
                return None, "Chat agent not found"
            
            workspace_id = agent.get("workspace_id")
            
            # Get requests by email
            requests, total = await self.repository.get_requests_by_email(
                agent_id, workspace_id, email, page, page_size
            )
            
            tickets = []
            for req in requests:
                current_approver_name = None
                raised_by_name = None
                raised_by_department = None
                if req.get("current_approver"):
                    approver = await self.repository.get_member_by_id(req["current_approver"])
                    current_approver_name = approver.get("name") if approver else None
                if req.get("raised_by"):
                    member = await self.repository.get_member_by_id(req["raised_by"])
                    raised_by_name = member.get("name") if member else None
                    raised_by_department = member.get("department") if member else None
                messages = req.get("messages", [])
                last_message = messages[-1].get("message") if messages else None
                tickets.append({
                    "request_number": req.get("request_number"),
                    "subject": req["subject"],
                    "status": req["status"],
                    "priority": req["priority"],
                    "current_approver_name": current_approver_name,
                    "raised_by_name": raised_by_name,
                    "raised_by_department": raised_by_department,
                    "created_at": req["created_at"],
                    "updated_at": req.get("updated_at"),
                    "last_message": last_message
                })
            
            return {
                "tickets": tickets,
                "total": total
            }, None
            
        except Exception as e:
            logger.error(f"Error in public_get_my_tickets: {str(e)}")
            return None, str(e)


# Create a singleton instance
request_service = RequestService()
