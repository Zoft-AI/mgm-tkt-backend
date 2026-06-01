"""
Workspace Service Layer

This module contains all business logic for workspace operations.
Following the LLD architecture pattern for proper separation of concerns.
"""

import logging
import time
from typing import List, Optional, Dict, Any, Tuple
try:
    from twilio.rest import Client as twilio_rest
except ImportError:
    twilio_rest = None

from models.workspace import (
    WorkspaceBase, WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse, 
    WorkspaceAgentsResponse, TwilioNumbersResponse, APIValidationError
)
from db.workspace_repository import WorkspaceRepository
try:
    from utils.external_api_validation import check_elevenlabs, check_twilio_creds, check_openai_api_key
except ImportError:
    check_elevenlabs = check_twilio_creds = check_openai_api_key = lambda *a, **kw: "OK"

logger = logging.getLogger(__name__)


class WorkspaceService:
    """Service class for workspace business logic"""
    
    def __init__(self):
        self.repository = WorkspaceRepository()
    
    async def create_workspace(self, profile_id: str, workspace_data: WorkspaceCreate) -> Tuple[Optional[str], Optional[str]]:
        """
        Create a new workspace with API credential validation
        
        Args:
            profile_id: User profile ID
            workspace_data: Workspace creation data
            
        Returns:
            Tuple of (workspace_id, error_message)
        """
        try:
            # Validate API credentials before creating workspace
            validation_error = await self._validate_api_credentials(workspace_data)
            if validation_error:
                return None, validation_error
            
            # Create workspace in database
            workspace_id = await self.repository.create_workspace(profile_id, workspace_data)
            
            logger.info(f"Workspace created successfully: {workspace_id}")
            return workspace_id, None
            
        except Exception as e:
            logger.error(f"Error creating workspace: {str(e)}")
            return None, f"Failed to create workspace: {str(e)}"
    
    async def update_workspace(self, profile_id: str, workspace_data: WorkspaceUpdate) -> Tuple[bool, Optional[str]]:
        """
        Update an existing workspace with API credential validation
        
        Args:
            profile_id: User profile ID
            workspace_data: Workspace update data
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            # Validate API credentials before updating
            validation_error = await self._validate_api_credentials(workspace_data)
            if validation_error:
                return False, validation_error
            
            # Update workspace in database
            success = await self.repository.update_workspace(workspace_data.workspace_id, workspace_data)
            
            if success:
                logger.info(f"Workspace {workspace_data.workspace_id} updated successfully")
                return True, None
            else:
                return False, "Failed to update workspace"
                
        except Exception as e:
            logger.error(f"Error updating workspace: {str(e)}")
            return False, f"Failed to update workspace: {str(e)}"
    
    async def delete_workspace(self, profile_id: str, workspace_id: str) -> Tuple[bool, Optional[str]]:
        """
        Delete a workspace
        
        Args:
            profile_id: User profile ID
            workspace_id: Workspace ID to delete
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            success = await self.repository.delete_workspace(workspace_id)
            
            if success:
                logger.info(f"Workspace {workspace_id} deleted successfully")
                return True, None
            else:
                return False, "Failed to delete workspace"
                
        except Exception as e:
            logger.error(f"Error deleting workspace: {str(e)}")
            return False, f"Failed to delete workspace: {str(e)}"
    
    async def get_user_workspaces(self, profile_id: str) -> List[WorkspaceResponse]:
        """
        Get all workspaces for a user (owned + shared)
        
        Args:
            profile_id: User profile ID
            
        Returns:
            List of user workspaces with is_owner flag
        """
        try:
            from db.member_repository import member_repository
            
            # Get all workspaces (owned + shared) using member repository
            data = await member_repository.get_all_workspaces_for_profile(profile_id)
            
            workspace_responses = []
            for item in data:
                m = item["membership"]
                ws = item["workspace"]
                
                is_owner = m.get("is_owner", False)
                
                workspace_responses.append(WorkspaceResponse(
                    id=ws["id"],
                    profile_id=ws.get("profile_id", ""),
                    workspace_name=ws.get("workspace_name", "Unnamed"),
                    twilio_SSID=ws.get("twilio_SSID"),
                    twilio_auth_token=ws.get("twilio_auth_token"),
                    elevenlabs_api_key=ws.get("elevenlabs_api_key"),
                    openai_api_key=ws.get("openai_api_key"),
                    is_owner=is_owner,
                    created_at=ws.get("created_at"),
                    updated_at=ws.get("updated_at")
                ))
            
            # Sort: owned first, then by name
            workspace_responses.sort(key=lambda x: (not x.is_owner, x.workspace_name.lower()))
            
            return workspace_responses
            
        except Exception as e:
            logger.error(f"Error getting user workspaces: {str(e)}")
            return []
    
    async def get_workspace_agents(self, profile_id: str, workspace_id: str, type: str = "") -> WorkspaceAgentsResponse:
        """
        Get all agents (chat and phone) for a workspace
        User must be a member (owner or shared) of the workspace
        
        Args:
            profile_id: User profile ID
            workspace_id: Workspace ID
            type: Optional filter type. If "campaign", returns only voice agents. If empty, returns all agents.
            
        Returns:
            Workspace agents response
        """
        try:
            from db.member_repository import member_repository
            
            # Check if user is a member of this workspace (owner or shared)
            member = await member_repository.get_member_by_profile_workspace(profile_id, workspace_id)
            
            # If not in members table, check if user owns the workspace
            if not member:
                workspace = await self.repository.get_workspace_by_id(workspace_id)
                if not workspace or workspace.get("profile_id") != profile_id:
                    # User is not a member and doesn't own it
                    logger.warning(f"User {profile_id} is not a member of workspace {workspace_id}")
                    return WorkspaceAgentsResponse()
            
            # User is a member or owner, proceed to get agents
            # If type is "campaign", return only voice agents
            if type.lower() == "campaign":
                phone_agents = await self.repository.get_phone_agents_by_workspace(workspace_id)
                return WorkspaceAgentsResponse(
                    chat_agents=None,
                    phone_agents=phone_agents if phone_agents else None
                )
            
            # Otherwise, return all agents
            chat_agents = await self.repository.get_chat_agents_by_workspace(workspace_id)
            phone_agents = await self.repository.get_phone_agents_by_workspace(workspace_id)
            
            return WorkspaceAgentsResponse(
                chat_agents=chat_agents if chat_agents else None,
                phone_agents=phone_agents if phone_agents else None
            )
            
        except Exception as e:
            logger.error(f"Error getting workspace agents: {str(e)}")
            return WorkspaceAgentsResponse()
    
    async def get_phone_agents_by_profile(self, profile_id: str) -> WorkspaceAgentsResponse:
        """
        Get all phone agents for a profile
        
        Args:
            profile_id: User profile ID
            
        Returns:
            Workspace agents response with only phone agents
        """
        try:
            phone_agents = await self.repository.get_phone_agents_by_profile(profile_id)
            
            return WorkspaceAgentsResponse(
                chat_agents=None,
                phone_agents=phone_agents if phone_agents else None
            )
            
        except Exception as e:
            logger.error(f"Error getting phone agents by profile: {str(e)}")
            return WorkspaceAgentsResponse()

    async def get_all_chat_agents_for_profile(self, profile_id: str) -> WorkspaceAgentsResponse:
        """
        Get all chat agents from all workspaces (owned + shared) for a profile.
        Each agent includes workspace_id and workspace_name for context.

        Args:
            profile_id: User profile ID (from Bearer token)

        Returns:
            Workspace agents response with chat_agents list (phone_agents=None)
        """
        try:
            from db.member_repository import member_repository

            data = await member_repository.get_all_workspaces_for_profile(profile_id)
            if not data:
                return WorkspaceAgentsResponse(chat_agents=[], phone_agents=None)

            workspace_ids = [item["workspace"]["id"] for item in data]
            workspace_names = {item["workspace"]["id"]: item["workspace"].get("workspace_name", "Unnamed") for item in data}

            chat_agents_raw = await self.repository.get_chat_agents_by_workspace_ids(workspace_ids)
            chat_agents = [
                {**agent, "workspace_name": workspace_names.get(agent["workspace_id"], "Unnamed")}
                for agent in chat_agents_raw
            ]

            return WorkspaceAgentsResponse(
                chat_agents=chat_agents if chat_agents else [],
                phone_agents=None
            )
        except Exception as e:
            logger.error(f"Error getting all chat agents for profile: {str(e)}")
            return WorkspaceAgentsResponse(chat_agents=[], phone_agents=None)
    
    async def get_twilio_numbers(self, profile_id: str, workspace_id: str) -> TwilioNumbersResponse:
        """
        Get Twilio phone numbers for a workspace
        
        Args:
            profile_id: User profile ID
            workspace_id: Workspace ID
            
        Returns:
            Twilio numbers response
        """
        try:
            workspace = await self.repository.get_workspace_by_id(workspace_id)
            
            if not workspace:
                return TwilioNumbersResponse(numbers=[])
            
            twilio_ssid = workspace.get("twilio_SSID")
            twilio_auth_token = workspace.get("twilio_auth_token")
            
            if not twilio_ssid or not twilio_auth_token:
                logger.warning(f"No Twilio credentials configured for workspace {workspace_id}")
                return TwilioNumbersResponse(numbers=[])
            
            try:
                twilio_client = twilio_rest(twilio_ssid, twilio_auth_token)
                incoming_numbers = twilio_client.incoming_phone_numbers.list()
                
                numbers = [number.phone_number for number in incoming_numbers]
                
                logger.info(f"Retrieved {len(numbers)} Twilio numbers for workspace {workspace_id}")
                return TwilioNumbersResponse(numbers=numbers)
                
            except Exception as e:
                logger.error(f"Twilio API Error for workspace {workspace_id}: {e}")
                return TwilioNumbersResponse(numbers=[])
                
        except Exception as e:
            logger.error(f"Error getting Twilio numbers: {str(e)}")
            return TwilioNumbersResponse(numbers=[])
    
    async def _validate_api_credentials(self, workspace_data: WorkspaceBase) -> Optional[str]:
        """
        Validate API credentials for workspace
        
        Args:
            workspace_data: Workspace data with API credentials
            
        Returns:
            Error message if validation fails, None if successful
        """
        try:
            # Validate Twilio credentials if provided
            if workspace_data.twilio_SSID and workspace_data.twilio_auth_token:
                twilio_validation = check_twilio_creds(workspace_data.twilio_SSID, workspace_data.twilio_auth_token)
                if twilio_validation != "OK":
                    return twilio_validation
            elif workspace_data.twilio_SSID or workspace_data.twilio_auth_token:
                return "Enter both Twilio details"
            
            # Validate OpenAI API key if provided
            if workspace_data.openai_api_key:
                openai_validation = check_openai_api_key(workspace_data.openai_api_key)
                if not openai_validation:
                    return "Invalid OpenAI API key"
            
            # Validate ElevenLabs API key if provided
            if workspace_data.elevenlabs_api_key:
                elevenlabs_validation = check_elevenlabs(workspace_data.elevenlabs_api_key)
                if elevenlabs_validation != 1:
                    return f"Invalid ElevenLabs API key: {str(elevenlabs_validation)}"
            
            return None
            
        except Exception as e:
            logger.error(f"Error validating API credentials: {str(e)}")
            return "Failed to validate API credentials"


# Create a singleton instance
workspace_service = WorkspaceService()