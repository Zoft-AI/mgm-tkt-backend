"""
Workspace Repository

Database operations for workspace management using asyncpg (direct PostgreSQL).
"""

import logging
from typing import List, Optional, Dict, Any

from utils.database import get_db, record_to_dict, records_to_list

logger = logging.getLogger(__name__)


class WorkspaceRepository:
    """Repository class for workspace database operations"""

    def __init__(self):
        self.db = get_db()

    async def create_workspace(self, profile_id: str, workspace_data) -> str:
        try:
            row = await self.db.fetchrow(
                """INSERT INTO "Workspaces" (profile_id, workspace_name)
                   VALUES ($1, $2) RETURNING id""",
                profile_id, workspace_data.workspace_name
            )
            if not row:
                raise Exception("Failed to create workspace - no data returned")
            workspace_id = str(row["id"])
            logger.info(f"Workspace created: {workspace_id}")
            return workspace_id
        except Exception as e:
            logger.error(f"Database error creating workspace: {str(e)}")
            raise Exception(f"Failed to create workspace: {str(e)}")

    async def update_workspace(self, workspace_id: str, workspace_data) -> bool:
        try:
            result = await self.db.execute(
                """UPDATE "Workspaces" SET workspace_name = $1 WHERE id = $2""",
                workspace_data.workspace_name, workspace_id
            )
            updated = result.split()[-1] != "0"
            if updated:
                logger.info(f"Workspace updated: {workspace_id}")
            return updated
        except Exception as e:
            logger.error(f"Database error updating workspace: {str(e)}")
            return False

    async def delete_workspace(self, workspace_id: str) -> bool:
        try:
            result = await self.db.execute(
                """DELETE FROM "Workspaces" WHERE id = $1""", workspace_id
            )
            deleted = result.split()[-1] != "0"
            if deleted:
                logger.info(f"Workspace deleted: {workspace_id}")
            return deleted
        except Exception as e:
            logger.error(f"Database error deleting workspace: {str(e)}")
            return False

    async def get_workspaces_by_profile(self, profile_id: str) -> List[Dict[str, Any]]:
        try:
            rows = await self.db.fetch(
                """SELECT * FROM "Workspaces" WHERE profile_id = $1 ORDER BY created_at DESC""",
                profile_id
            )
            result = records_to_list(rows)
            logger.info(f"Retrieved {len(result)} workspaces for profile: {profile_id}")
            return result
        except Exception as e:
            logger.error(f"Database error getting workspaces: {str(e)}")
            return []

    async def get_workspace_by_id(self, workspace_id: str) -> Optional[Dict[str, Any]]:
        try:
            row = await self.db.fetchrow(
                """SELECT * FROM "Workspaces" WHERE id = $1""", workspace_id
            )
            return record_to_dict(row)
        except Exception as e:
            logger.error(f"Database error getting workspace: {str(e)}")
            return None

    async def get_chat_agents_by_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        try:
            rows = await self.db.fetch(
                """SELECT * FROM "Chat_Agents" WHERE workspace_id = $1 ORDER BY created_at DESC""",
                workspace_id
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Database error getting chat agents: {str(e)}")
            return []

    async def get_chat_agents_by_workspace_ids(self, workspace_ids: List[str]) -> List[Dict[str, Any]]:
        try:
            if not workspace_ids:
                return []
            rows = await self.db.fetch(
                """SELECT * FROM "Chat_Agents" WHERE workspace_id = ANY($1) ORDER BY created_at DESC""",
                workspace_ids
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Database error getting chat agents: {str(e)}")
            return []

    async def get_phone_agents_by_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        """Get phone agents (legacy - may not exist in mgm schema)"""
        try:
            rows = await self.db.fetch(
                """SELECT * FROM "Phone_Agents" WHERE workspace_id = $1 ORDER BY created_at DESC""",
                workspace_id
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Database error getting phone agents: {str(e)}")
            return []

    async def get_phone_agents_by_profile(self, profile_id: str) -> List[Dict[str, Any]]:
        """Get phone agents by profile (legacy - may not exist in mgm schema)"""
        try:
            rows = await self.db.fetch(
                """SELECT * FROM "Phone_Agents" WHERE profile_id = $1 ORDER BY created_at DESC""",
                profile_id
            )
            return records_to_list(rows)
        except Exception as e:
            logger.error(f"Database error getting phone agents by profile: {str(e)}")
            return []


workspace_repository = WorkspaceRepository()
