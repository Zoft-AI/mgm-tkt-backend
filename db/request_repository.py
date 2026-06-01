"""
Request Repository

Database operations for request/ticket management using asyncpg (direct PostgreSQL).
"""

import logging
import json
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone, date
from dateutil import parser as dateutil_parser

from utils.database import get_db, record_to_dict, records_to_list

logger = logging.getLogger(__name__)

DATETIME_COLUMNS = {
    "sla_deadline", "created_at", "updated_at", "resolved_at",
}


def _coerce_datetimes(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert ISO-8601 string values to datetime objects for known timestamp columns.
    asyncpg requires native datetime instances, not strings."""
    out = dict(data)
    for col in DATETIME_COLUMNS:
        val = out.get(col)
        if isinstance(val, str):
            try:
                out[col] = dateutil_parser.isoparse(val)
            except (ValueError, TypeError):
                pass
        elif isinstance(val, date) and not isinstance(val, datetime):
            out[col] = datetime(val.year, val.month, val.day, tzinfo=timezone.utc)
    return out


class RequestRepository:
    """Repository class for request database operations"""

    def __init__(self):
        self.db = get_db()

    # ========================================================================
    # Chat Agent Operations
    # ========================================================================

    async def get_chat_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get chat agent by ID"""
        try:
            row = await self.db.fetchrow(
                """SELECT id, workspace_id, profile_id, bot_name FROM "Chat_Agents" WHERE id = $1""",
                agent_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting chat agent: {str(e)}")
            return None

    async def get_conversation_by_id(self, conversation_id: str) -> Optional[List[Dict[str, Any]]]:
        """Get conversation messages from Chat_Agent_history"""
        try:
            row = await self.db.fetchrow(
                """SELECT conversation FROM "Chat_Agent_history" WHERE conversation_id = $1""",
                conversation_id
            )
            if row and row["conversation"]:
                conv = row["conversation"]
                return conv if isinstance(conv, list) else []
            return None
        except Exception as e:
            logger.error(f"Error getting conversation: {str(e)}")
            return None

    # ========================================================================
    # Member Operations
    # ========================================================================

    async def get_member_by_profile_and_workspace(self, profile_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        """Get member by profile ID and workspace ID"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM members WHERE profile_id = $1 AND workspace_id = $2",
                profile_id, workspace_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting member: {str(e)}")
            return None

    async def get_member_by_id(self, member_id: str) -> Optional[Dict[str, Any]]:
        """Get member by ID"""
        try:
            row = await self.db.fetchrow("SELECT * FROM members WHERE id = $1", member_id)
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting member by ID: {str(e)}")
            return None

    async def get_members_by_ids(self, member_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Batch fetch members by IDs. Returns {member_id: member_dict}."""
        if not member_ids:
            return {}
        try:
            unique_ids = list(set(member_ids))
            rows = await self.db.fetch(
                "SELECT * FROM members WHERE id = ANY($1)", unique_ids
            )
            return {str(r["id"]): record_to_dict(r) for r in rows}
        except Exception as e:
            logger.error(f"Error batch fetching members: {str(e)}")
            return {}

    async def get_conversations_by_ids(self, conversation_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Batch fetch conversations by IDs."""
        if not conversation_ids:
            return {}
        try:
            unique_ids = list(set(conversation_ids))
            rows = await self.db.fetch(
                """SELECT conversation_id, conversation FROM "Chat_Agent_history"
                   WHERE conversation_id = ANY($1)""",
                unique_ids
            )
            result = {}
            for row in rows:
                cid = str(row["conversation_id"])
                conv = row["conversation"]
                if conv and isinstance(conv, list):
                    result[cid] = conv
            return result
        except Exception as e:
            logger.error(f"Error batch fetching conversations: {str(e)}")
            return {}

    async def get_members_by_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Get all active members for a workspace"""
        try:
            rows = await self.db.fetch(
                """SELECT * FROM members
                   WHERE workspace_id = $1 AND is_active = true AND status = 'active'
                   ORDER BY hierarchy_level""",
                workspace_id
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Error getting members: {str(e)}")
            return []

    async def get_member_by_level(self, workspace_id: str, level: int) -> Optional[Dict[str, Any]]:
        """Get a member at a specific hierarchy level"""
        try:
            row = await self.db.fetchrow(
                """SELECT * FROM members
                   WHERE workspace_id = $1 AND hierarchy_level = $2
                     AND is_active = true AND status = 'active'
                   LIMIT 1""",
                workspace_id, level
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting member by level: {str(e)}")
            return None

    # ========================================================================
    # Hierarchy Operations
    # ========================================================================

    async def get_hierarchy_by_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Get hierarchy levels for a workspace"""
        try:
            rows = await self.db.fetch(
                "SELECT * FROM hierarchy WHERE workspace_id = $1 ORDER BY level",
                workspace_id
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Error getting hierarchy: {str(e)}")
            return []

    async def get_hierarchy_level(self, workspace_id: str, level: int) -> Optional[Dict[str, Any]]:
        """Get a specific hierarchy level"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM hierarchy WHERE workspace_id = $1 AND level = $2",
                workspace_id, level
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting hierarchy level: {str(e)}")
            return None

    # ========================================================================
    # Rule Operations
    # ========================================================================

    async def get_rules_by_agent(self, workspace_id: str, agent_id: str) -> List[Dict[str, Any]]:
        """Get active rules for an agent (agent-specific + workspace-wide)"""
        try:
            rows = await self.db.fetch(
                """SELECT * FROM rules
                   WHERE workspace_id = $1 AND is_active = true
                     AND (chat_agent_id = $2 OR chat_agent_id IS NULL)""",
                workspace_id, agent_id
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Error getting rules: {str(e)}")
            return []

    async def get_rule_by_id(self, rule_id: str) -> Optional[Dict[str, Any]]:
        """Get rule by ID"""
        try:
            row = await self.db.fetchrow("SELECT * FROM rules WHERE id = $1", rule_id)
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting rule: {str(e)}")
            return None

    async def get_rule_by_agent_and_name(
        self, workspace_id: str, agent_id: str, rule_name: str
    ) -> Optional[Dict[str, Any]]:
        """Get rule by workspace, agent, and rule name"""
        try:
            row = await self.db.fetchrow(
                """SELECT * FROM rules
                   WHERE workspace_id = $1 AND chat_agent_id = $2
                     AND rule_name = $3 AND is_active = true
                   LIMIT 1""",
                workspace_id, agent_id, rule_name
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting rule by name: {str(e)}")
            return None

    async def update_rule_data(self, rule_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update rule's data JSONB column"""
        try:
            row = await self.db.fetchrow(
                "UPDATE rules SET data = $1, updated_at = NOW() WHERE id = $2 RETURNING *",
                data, rule_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error updating rule data: {str(e)}")
            return None

    # ========================================================================
    # Product Operations
    # ========================================================================

    async def get_products(
        self, workspace_id: str, agent_id: str,
        category: Optional[str] = None,
        search: Optional[str] = None,
        is_active: bool = True
    ) -> List[Dict[str, Any]]:
        """Get products for a workspace+agent"""
        try:
            query = """SELECT * FROM products
                       WHERE workspace_id = $1 AND chat_agent_id = $2 AND is_active = $3"""
            params: list = [workspace_id, agent_id, is_active]
            idx = 4

            if category:
                query += f" AND category = ${idx}"
                params.append(category)
                idx += 1
            if search:
                query += f" AND (name ILIKE ${idx} OR aliases::text ILIKE ${idx})"
                params.append(f"%{search}%")
                idx += 1

            query += " ORDER BY category, name"
            rows = await self.db.fetch(query, *params)
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Error getting products: {str(e)}")
            return []

    async def get_product_by_id(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Get a single product by ID"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM products WHERE id = $1 AND is_active = true", product_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting product by id: {str(e)}")
            return None

    async def get_product_categories(self, workspace_id: str, agent_id: str) -> List[str]:
        """Get distinct product categories"""
        try:
            rows = await self.db.fetch(
                """SELECT DISTINCT category FROM products
                   WHERE workspace_id = $1 AND chat_agent_id = $2 AND is_active = true
                   ORDER BY category""",
                workspace_id, agent_id
            )
            return [r["category"] for r in rows if r["category"]]
        except Exception as e:
            logger.error(f"Error getting product categories: {str(e)}")
            return []

    async def create_product(self, product_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Insert a new product"""
        try:
            columns = list(product_data.keys())
            values = list(product_data.values())
            placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
            col_names = ", ".join(columns)

            row = await self.db.fetchrow(
                f"INSERT INTO products ({col_names}) VALUES ({placeholders}) RETURNING *",
                *values
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            return None

    async def create_products_bulk(self, products_list: List[Dict[str, Any]]) -> int:
        """Bulk insert products"""
        try:
            if not products_list:
                return 0
            count = 0
            for p in products_list:
                result = await self.create_product(p)
                if result:
                    count += 1
            return count
        except Exception as e:
            logger.error(f"Error bulk creating products: {str(e)}")
            return 0

    async def update_product(self, product_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update a product"""
        try:
            update_data["updated_at"] = datetime.now(timezone.utc).isoformat()

            set_clauses = []
            values = []
            for i, (col, val) in enumerate(update_data.items(), 1):
                set_clauses.append(f"{col} = ${i}")
                values.append(val)

            values.append(product_id)
            query = f"UPDATE products SET {', '.join(set_clauses)} WHERE id = ${len(values)} RETURNING *"

            row = await self.db.fetchrow(query, *values)
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error updating product: {str(e)}")
            return None

    async def delete_product(self, product_id: str) -> bool:
        """Soft-delete a product"""
        try:
            result = await self.db.execute(
                "UPDATE products SET is_active = false, updated_at = NOW() WHERE id = $1",
                product_id
            )
            return result.split()[-1] != "0"
        except Exception as e:
            logger.error(f"Error deleting product: {str(e)}")
            return False

    async def delete_products_bulk(self, product_ids: List[str]) -> int:
        """Soft-delete multiple products"""
        try:
            result = await self.db.execute(
                "UPDATE products SET is_active = false, updated_at = NOW() WHERE id = ANY($1)",
                product_ids
            )
            return int(result.split()[-1])
        except Exception as e:
            logger.error(f"Error bulk deleting products: {str(e)}")
            return 0

    # ========================================================================
    # Request CRUD Operations
    # ========================================================================

    async def create_request(self, request_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new request"""
        try:
            request_data = _coerce_datetimes(request_data)
            columns = list(request_data.keys())
            values = list(request_data.values())
            placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
            col_names = ", ".join(columns)

            row = await self.db.fetchrow(
                f"INSERT INTO requests ({col_names}) VALUES ({placeholders}) RETURNING *",
                *values
            )
            if row:
                logger.info(f"Request created: {row['id']}")
                return record_to_dict(row)
            return None
        except Exception as e:
            logger.error(f"Error creating request: {str(e)}")
            raise Exception(f"Failed to create request: {str(e)}")

    async def get_request_by_id(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get request by ID"""
        try:
            row = await self.db.fetchrow("SELECT * FROM requests WHERE id = $1", request_id)
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting request: {str(e)}")
            return None

    async def update_request(self, request_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update a request"""
        try:
            update_data = _coerce_datetimes(update_data)
            set_clauses = []
            values = []
            for i, (col, val) in enumerate(update_data.items(), 1):
                set_clauses.append(f"{col} = ${i}")
                values.append(val)

            values.append(request_id)
            query = f"UPDATE requests SET {', '.join(set_clauses)} WHERE id = ${len(values)} RETURNING *"

            row = await self.db.fetchrow(query, *values)
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error updating request: {str(e)}")
            return None

    async def get_requests_by_agent(
        self,
        agent_id: str,
        workspace_id: str,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get all requests for an agent with pagination"""
        try:
            offset = (page - 1) * page_size
            base_where = "chat_agent_id = $1 AND workspace_id = $2"
            params: list = [agent_id, workspace_id]
            idx = 3

            if status:
                base_where += f" AND status = ${idx}"
                params.append(status)
                idx += 1
            else:
                base_where += " AND status != 'draft'"

            total = await self.db.fetchval(
                f"SELECT COUNT(*) FROM requests WHERE {base_where}", *params
            )

            params.extend([page_size, offset])
            rows = await self.db.fetch(
                f"""SELECT * FROM requests WHERE {base_where}
                    ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}""",
                *params
            )
            return records_to_list(rows), total or 0

        except Exception as e:
            logger.error(f"Error getting requests: {str(e)}")
            return [], 0

    async def get_unit_by_id(self, unit_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single unit row by id"""
        try:
            row = await self.db.fetchrow("SELECT * FROM units WHERE id = $1", unit_id)
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting unit {unit_id}: {str(e)}")
            return None

    async def get_admin_requests(
        self,
        agent_id: str,
        workspace_id: str,
        unit: Optional[str] = None,
        payment_type: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Admin view: all requests, optionally filtered by unit/payment_type/status"""
        try:
            offset = (page - 1) * page_size
            base_where = "chat_agent_id = $1 AND workspace_id = $2"
            params: list = [agent_id, workspace_id]
            idx = 3

            if status:
                base_where += f" AND status = ${idx}"
                params.append(status)
                idx += 1
            else:
                base_where += " AND status != 'draft'"

            if unit:
                base_where += f" AND data->>'unit' = ${idx}"
                params.append(unit)
                idx += 1
            if payment_type:
                base_where += f" AND data->>'payment_type' = ${idx}"
                params.append(payment_type)
                idx += 1

            total = await self.db.fetchval(
                f"SELECT COUNT(*) FROM requests WHERE {base_where}", *params
            )

            params.extend([page_size, offset])
            rows = await self.db.fetch(
                f"""SELECT * FROM requests WHERE {base_where}
                    ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx+1}""",
                *params
            )
            return records_to_list(rows), total or 0

        except Exception as e:
            logger.error(f"Error getting admin requests: {str(e)}")
            return [], 0

    async def get_requests_raised_by_member(
        self, agent_id: str, member_id: str, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get requests raised by a specific member"""
        try:
            offset = (page - 1) * page_size

            total = await self.db.fetchval(
                """SELECT COUNT(*) FROM requests
                   WHERE chat_agent_id = $1 AND raised_by = $2 AND status != 'draft'""",
                agent_id, member_id
            )

            rows = await self.db.fetch(
                """SELECT * FROM requests
                   WHERE chat_agent_id = $1 AND raised_by = $2 AND status != 'draft'
                   ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
                agent_id, member_id, page_size, offset
            )
            return records_to_list(rows), total or 0
        except Exception as e:
            logger.error(f"Error getting raised by me requests: {str(e)}")
            return [], 0

    async def get_requests_raised_to_member(
        self, agent_id: str, member_id: str, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get requests assigned to a specific member (pending action)"""
        try:
            offset = (page - 1) * page_size

            total = await self.db.fetchval(
                """SELECT COUNT(*) FROM requests
                   WHERE chat_agent_id = $1 AND current_approver = $2 AND status = 'pending'""",
                agent_id, member_id
            )

            rows = await self.db.fetch(
                """SELECT * FROM requests
                   WHERE chat_agent_id = $1 AND current_approver = $2 AND status = 'pending'
                   ORDER BY priority, created_at LIMIT $3 OFFSET $4""",
                agent_id, member_id, page_size, offset
            )
            return records_to_list(rows), total or 0
        except Exception as e:
            logger.error(f"Error getting raised to me requests: {str(e)}")
            return [], 0

    async def get_requests_approved_by_member(
        self, agent_id: str, member_id: str, page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get requests where member approved/rejected (uses DB function)"""
        try:
            offset = (page - 1) * page_size

            rows = await self.db.fetch(
                "SELECT * FROM get_requests_approved_by_member($1, $2, $3, $4)",
                agent_id, member_id, page_size, offset
            )
            total = await self.db.fetchval(
                "SELECT get_requests_approved_by_member_count($1, $2)",
                agent_id, member_id
            )
            return records_to_list(rows), total or 0
        except Exception as e:
            logger.error(f"Error getting acted-by-me requests: {str(e)}")
            return [], 0

    async def get_overdue_pending_requests(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get pending requests past sla_deadline with sla_auto_approve=True"""
        try:
            rows = await self.db.fetch(
                """SELECT * FROM requests
                   WHERE chat_agent_id = $1 AND status = 'pending'
                     AND sla_auto_approve = true AND sla_deadline < NOW()""",
                agent_id
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Error getting overdue requests: {str(e)}")
            return []

    async def get_agent_ids_with_overdue_requests(self) -> List[str]:
        """Get distinct chat_agent_ids with overdue pending requests"""
        try:
            rows = await self.db.fetch(
                """SELECT DISTINCT chat_agent_id FROM requests
                   WHERE status = 'pending' AND sla_auto_approve = true AND sla_deadline < NOW()"""
            )
            return [str(r["chat_agent_id"]) for r in rows]
        except Exception as e:
            logger.error(f"Error getting agent ids with overdue requests: {str(e)}")
            return []

    async def get_request_stats(self, agent_id: str, workspace_id: str) -> Dict[str, int]:
        """Get request statistics for an agent"""
        try:
            row = await self.db.fetchrow(
                """SELECT
                    COUNT(*) FILTER (WHERE status != 'draft') as total,
                    COUNT(*) FILTER (WHERE status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE status = 'approved') as approved,
                    COUNT(*) FILTER (WHERE status = 'rejected') as rejected,
                    COUNT(*) FILTER (WHERE is_sla_breached = true) as sla_breached
                   FROM requests
                   WHERE chat_agent_id = $1 AND workspace_id = $2""",
                agent_id, workspace_id
            )
            if row:
                return {
                    "total": row["total"] or 0,
                    "pending": row["pending"] or 0,
                    "approved": row["approved"] or 0,
                    "rejected": row["rejected"] or 0,
                    "sla_breached": row["sla_breached"] or 0,
                }
            return {"total": 0, "pending": 0, "approved": 0, "rejected": 0, "sla_breached": 0}
        except Exception as e:
            logger.error(f"Error getting request stats: {str(e)}")
            return {"total": 0}

    async def get_my_request_stats(self, agent_id: str, member_id: str) -> Dict[str, int]:
        """Get stats for requests raised by member"""
        try:
            row = await self.db.fetchrow(
                """SELECT
                    COUNT(*) FILTER (WHERE status != 'draft') as total,
                    COUNT(*) FILTER (WHERE status = 'pending') as pending,
                    COUNT(*) FILTER (WHERE status = 'approved') as approved,
                    COUNT(*) FILTER (WHERE status = 'rejected') as rejected
                   FROM requests
                   WHERE chat_agent_id = $1 AND raised_by = $2""",
                agent_id, member_id
            )
            if row:
                return {
                    "total": row["total"] or 0,
                    "pending": row["pending"] or 0,
                    "approved": row["approved"] or 0,
                    "rejected": row["rejected"] or 0,
                }
            return {"total": 0, "pending": 0, "approved": 0, "rejected": 0}
        except Exception as e:
            logger.error(f"Error getting my request stats: {str(e)}")
            return {"total": 0, "pending": 0, "approved": 0, "rejected": 0}

    async def get_my_approval_stats(self, agent_id: str, member_id: str) -> Dict[str, int]:
        """Get stats for requests I approved/rejected or pending for my approval"""
        try:
            pending = await self.db.fetchval(
                """SELECT COUNT(*) FROM requests
                   WHERE chat_agent_id = $1 AND current_approver = $2 AND status = 'pending'""",
                agent_id, member_id
            )

            approved = 0
            rejected = 0
            try:
                rpc_result = await self.db.fetchval(
                    "SELECT get_my_approval_stats($1, $2)", agent_id, member_id
                )
                if rpc_result:
                    if isinstance(rpc_result, str):
                        rpc_data = json.loads(rpc_result)
                    else:
                        rpc_data = rpc_result
                    approved = int(rpc_data.get("approved", 0))
                    rejected = int(rpc_data.get("rejected", 0))
            except Exception as rpc_err:
                logger.warning(f"RPC get_my_approval_stats fallback: {rpc_err}")

            total = (pending or 0) + approved + rejected
            return {"total": total, "pending": pending or 0, "approved": approved, "rejected": rejected}
        except Exception as e:
            logger.error(f"Error getting my approval stats: {str(e)}")
            return {"total": 0, "pending": 0, "approved": 0, "rejected": 0}

    # ========================================================================
    # Public Endpoint Operations (No Auth - For Chatbot)
    # ========================================================================

    async def get_member_by_email(self, workspace_id: str, email: str) -> Optional[Dict[str, Any]]:
        """Get member by email in a workspace"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM members WHERE workspace_id = $1 AND email = $2",
                workspace_id, email.lower()
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting member by email: {str(e)}")
            return None

    async def get_request_by_number(self, agent_id: str, request_number: str) -> Optional[Dict[str, Any]]:
        """Get request by request number"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM requests WHERE chat_agent_id = $1 AND request_number = $2",
                agent_id, request_number
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting request by number: {str(e)}")
            return None

    async def get_requests_by_email(
        self, agent_id: str, workspace_id: str, email: str,
        page: int = 1, page_size: int = 20
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get requests raised by a user (identified by email)"""
        try:
            member = await self.get_member_by_email(workspace_id, email)
            if not member:
                return [], 0

            member_id = member["id"]
            offset = (page - 1) * page_size

            total = await self.db.fetchval(
                "SELECT COUNT(*) FROM requests WHERE chat_agent_id = $1 AND raised_by = $2",
                agent_id, member_id
            )

            rows = await self.db.fetch(
                """SELECT * FROM requests
                   WHERE chat_agent_id = $1 AND raised_by = $2
                   ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
                agent_id, member_id, page_size, offset
            )
            return records_to_list(rows), total or 0
        except Exception as e:
            logger.error(f"Error getting requests by email: {str(e)}")
            return [], 0


request_repository = RequestRepository()
