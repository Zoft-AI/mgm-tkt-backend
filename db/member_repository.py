"""
Repository for Team Member operations

Database operations using asyncpg (direct PostgreSQL).
"""

import logging
from typing import Optional, Dict, Any, List, Tuple

from utils.database import get_db, record_to_dict, records_to_list

logger = logging.getLogger(__name__)


class MemberRepository:
    """Repository for member database operations"""

    def __init__(self):
        self.db = get_db()

    # ========================================================================
    # Member CRUD Operations
    # ========================================================================

    async def get_members_by_workspace(
        self,
        workspace_id: str,
        status: Optional[str] = None,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get all members in a workspace with pagination"""
        try:
            offset = (page - 1) * page_size

            count_query = "SELECT COUNT(*) FROM members WHERE workspace_id = $1"
            data_query = """SELECT * FROM members WHERE workspace_id = $1"""
            params: list = [workspace_id]

            if status:
                count_query += " AND status = $2"
                data_query += " AND status = $2"
                params.append(status)

            total = await self.db.fetchval(count_query, *params)

            data_query += " ORDER BY hierarchy_level DESC, name ASC LIMIT $%d OFFSET $%d" % (
                len(params) + 1, len(params) + 2
            )
            params.extend([page_size, offset])

            rows = await self.db.fetch(data_query, *params)
            return records_to_list(rows), total or 0

        except Exception as e:
            logger.error(f"Error getting members: {str(e)}")
            return [], 0

    async def get_member_by_id(self, member_id: str) -> Optional[Dict[str, Any]]:
        """Get member by ID"""
        try:
            row = await self.db.fetchrow("SELECT * FROM members WHERE id = $1", member_id)
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting member by id: {str(e)}")
            return None

    async def get_member_by_email_workspace(self, email: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        """Get member by email in a specific workspace"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM members WHERE workspace_id = $1 AND email = $2",
                workspace_id, email.lower()
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting member by email: {str(e)}")
            return None

    async def get_member_by_profile_workspace(self, profile_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        """Get member by profile_id in a specific workspace"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM members WHERE workspace_id = $1 AND profile_id = $2",
                workspace_id, profile_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting member by profile: {str(e)}")
            return None

    async def get_members_by_profile(self, profile_id: str) -> List[Dict[str, Any]]:
        """Get all workspace memberships for a profile"""
        try:
            rows = await self.db.fetch(
                "SELECT * FROM members WHERE profile_id = $1 AND status = 'active'",
                profile_id
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Error getting memberships: {str(e)}")
            return []

    async def get_all_workspaces_for_profile(self, profile_id: str) -> List[Dict[str, Any]]:
        """Get all workspaces (owned + shared) for a profile with workspace details"""
        try:
            result = []
            workspace_ids_seen = set()

            # 1. Get workspaces from members table
            members = await self.db.fetch(
                "SELECT * FROM members WHERE profile_id = $1 AND status = 'active'",
                profile_id
            )

            for m in members:
                m_dict = record_to_dict(m)
                ws_row = await self.db.fetchrow(
                    """SELECT * FROM "Workspaces" WHERE id = $1""", m["workspace_id"]
                )
                if ws_row:
                    ws_dict = record_to_dict(ws_row)
                    workspace_ids_seen.add(str(ws_row["id"]))
                    result.append({"membership": m_dict, "workspace": ws_dict})

            # 2. Get workspaces directly owned via Workspaces.profile_id
            owned = await self.db.fetch(
                """SELECT * FROM "Workspaces" WHERE profile_id = $1""", profile_id
            )

            for ws in owned:
                ws_dict = record_to_dict(ws)
                if ws_dict["id"] in workspace_ids_seen:
                    continue

                virtual_membership = {
                    "id": None,
                    "profile_id": profile_id,
                    "workspace_id": ws_dict["id"],
                    "email": None,
                    "name": None,
                    "hierarchy_level": 6,
                    "status": "active",
                    "is_owner": True,
                    "is_active": True,
                    "invited_by": None,
                    "invited_at": ws_dict.get("created_at"),
                    "created_at": ws_dict.get("created_at"),
                    "updated_at": None
                }
                result.append({"membership": virtual_membership, "workspace": ws_dict})

            return result

        except Exception as e:
            logger.error(f"Error getting all workspaces: {str(e)}")
            return []

    async def create_member(self, member_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Create a new member"""
        try:
            columns = list(member_data.keys())
            values = list(member_data.values())
            placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
            col_names = ", ".join(columns)

            row = await self.db.fetchrow(
                f"INSERT INTO members ({col_names}) VALUES ({placeholders}) RETURNING *",
                *values
            )
            if row:
                logger.info(f"Member created: {row['id']}")
                return record_to_dict(row)
            return None
        except Exception as e:
            logger.error(f"Error creating member: {str(e)}")
            return None

    async def update_member(self, member_id: str, update_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update a member"""
        try:
            if not update_data:
                return None

            set_clauses = []
            values = []
            for i, (col, val) in enumerate(update_data.items(), 1):
                set_clauses.append(f"{col} = ${i}")
                values.append(val)

            values.append(member_id)
            query = f"UPDATE members SET {', '.join(set_clauses)} WHERE id = ${len(values)} RETURNING *"

            row = await self.db.fetchrow(query, *values)
            if row:
                logger.info(f"Member updated: {member_id}")
                return record_to_dict(row)
            return None
        except Exception as e:
            logger.error(f"Error updating member: {str(e)}")
            return None

    async def delete_member(self, member_id: str) -> bool:
        """Soft delete - set status to inactive"""
        try:
            result = await self.db.execute(
                "UPDATE members SET status = 'inactive', is_active = false WHERE id = $1",
                member_id
            )
            deleted = result.split()[-1] != "0"
            if deleted:
                logger.info(f"Member deactivated: {member_id}")
            return deleted
        except Exception as e:
            logger.error(f"Error deleting member: {str(e)}")
            return False

    async def hard_delete_member(self, member_id: str) -> bool:
        """Permanently delete a member"""
        try:
            result = await self.db.execute("DELETE FROM members WHERE id = $1", member_id)
            deleted = result.split()[-1] != "0"
            if deleted:
                logger.info(f"Member permanently deleted: {member_id}")
            return deleted
        except Exception as e:
            logger.error(f"Error hard deleting member: {str(e)}")
            return False

    # ========================================================================
    # Invitation Operations
    # ========================================================================

    async def get_member_by_invitation_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Get member by invitation token"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM members WHERE invitation_token = $1", token
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting member by token: {str(e)}")
            return None

    async def get_pending_invitations(
        self,
        workspace_id: str,
        page: int = 1,
        page_size: int = 50
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get all pending/revoked/expired invitations for a workspace"""
        try:
            offset = (page - 1) * page_size

            total = await self.db.fetchval(
                """SELECT COUNT(*) FROM members
                   WHERE workspace_id = $1
                     AND status IN ('pending', 'revoked', 'expired')
                     AND invited_by IS NOT NULL""",
                workspace_id
            )

            rows = await self.db.fetch(
                """SELECT * FROM members
                   WHERE workspace_id = $1
                     AND status IN ('pending', 'revoked', 'expired')
                     AND invited_by IS NOT NULL
                   ORDER BY invited_at DESC
                   LIMIT $2 OFFSET $3""",
                workspace_id, page_size, offset
            )
            return records_to_list(rows), total or 0
        except Exception as e:
            logger.error(f"Error getting pending invitations: {str(e)}")
            return [], 0

    async def activate_member(self, member_id: str, profile_id: str) -> Optional[Dict[str, Any]]:
        """Activate a pending member (accept invitation)"""
        try:
            row = await self.db.fetchrow(
                """UPDATE members
                   SET profile_id = $1, status = 'active',
                       invitation_token = NULL, invitation_expires_at = NULL,
                       updated_at = NOW()
                   WHERE id = $2 RETURNING *""",
                profile_id, member_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error activating member: {str(e)}")
            return None

    async def revoke_invitation(self, member_id: str) -> Optional[Dict[str, Any]]:
        """Revoke a pending invitation"""
        try:
            row = await self.db.fetchrow(
                """UPDATE members
                   SET status = 'revoked', invitation_token = NULL,
                       invitation_expires_at = NULL, is_active = false, updated_at = NOW()
                   WHERE id = $1 RETURNING *""",
                member_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error revoking invitation: {str(e)}")
            return None

    # ========================================================================
    # Notification Operations
    # ========================================================================

    async def get_unseen_memberships(self, profile_id: str) -> List[Dict[str, Any]]:
        """Get active memberships not yet seen by the user"""
        try:
            rows = await self.db.fetch(
                """SELECT * FROM members
                   WHERE profile_id = $1 AND status = 'active' AND seen = false
                   ORDER BY created_at DESC""",
                profile_id
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Error getting unseen memberships: {str(e)}")
            return []

    async def mark_memberships_seen(
        self, profile_id: str, member_ids: Optional[List[str]] = None
    ) -> int:
        """Mark memberships as seen"""
        try:
            if member_ids:
                result = await self.db.execute(
                    """UPDATE members SET seen = true
                       WHERE profile_id = $1 AND seen = false AND id = ANY($2)""",
                    profile_id, member_ids
                )
            else:
                result = await self.db.execute(
                    "UPDATE members SET seen = true WHERE profile_id = $1 AND seen = false",
                    profile_id
                )
            count = int(result.split()[-1])
            return count
        except Exception as e:
            logger.error(f"Error marking memberships seen: {str(e)}")
            return 0

    # ========================================================================
    # Workspace Operations
    # ========================================================================

    async def get_workspace(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        """Get workspace by ID"""
        try:
            row = await self.db.fetchrow(
                """SELECT * FROM "Workspaces" WHERE id = $1""", workspace_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting workspace: {str(e)}")
            return None

    async def get_workspace_owner(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        """Get the owner member of a workspace"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM members WHERE workspace_id = $1 AND is_owner = true",
                workspace_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting workspace owner: {str(e)}")
            return None

    # ========================================================================
    # Hierarchy Operations
    # ========================================================================

    async def get_hierarchy_levels(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Get all hierarchy levels for a workspace"""
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
    # Profile Operations
    # ========================================================================

    async def get_profile(self, profile_id: str) -> Optional[Dict[str, Any]]:
        """Get profile by ID"""
        try:
            row = await self.db.fetchrow("SELECT * FROM profiles WHERE id = $1", profile_id)
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting profile: {str(e)}")
            return None

    async def get_profile_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get profile by email"""
        try:
            row = await self.db.fetchrow(
                "SELECT * FROM profiles WHERE email = $1", email.lower()
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Error getting profile by email: {str(e)}")
            return None


member_repository = MemberRepository()
