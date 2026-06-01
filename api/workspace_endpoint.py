"""
Workspace API Endpoints

This module contains all workspace-related endpoints for managing workspaces.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Form, Header, Request, Depends
from fastapi.responses import JSONResponse

from models.workspace import (
    WorkspaceCreate, WorkspaceUpdate, WorkspaceCreateResponse,
    WorkspaceDeleteResponse, WorkspaceAgentsResponse, TwilioNumbersResponse,
    WorkspaceListResponse, WorkspaceResponse, APIValidationError
)
from services.auth import auth_service
from services.workspace_service import workspace_service
from utils.sanitize import sanitize_user_input

logger = logging.getLogger(__name__)

workspace_router = APIRouter(prefix="/workspace", tags=["workspace"])
public_workspace_router = APIRouter(prefix="/public/workspace", tags=["public_workspace"])


async def get_current_user(authorization: str = Header(...)) -> str:
    """Dependency to get current authenticated user"""
    authorization = sanitize_user_input(authorization, strict=True) if authorization else ""
    profile_id = await auth_service.verify_login(authorization)
    if not profile_id:
        raise HTTPException(status_code=401, detail="Login please")
    return profile_id


@public_workspace_router.post("/get_agents", response_model=WorkspaceAgentsResponse)
async def public_get_agents_by_workspace(
    workspace_id: str = Form(...),
    type: str = Form(default=""),
    profile_id: str = Depends(get_current_user)
):
    """Get the list of agents in a workspace."""
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        type = sanitize_user_input(type, strict=True) if type else ""
        agents_response = await workspace_service.get_workspace_agents(profile_id, workspace_id, type)
        return agents_response
    except Exception as e:
        logger.error(f"Error getting workspace agents: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get workspace agents")


@public_workspace_router.get("/get_workspace", response_model=List[WorkspaceResponse])
async def public_get_workspace(
    profile_id: str = Depends(get_current_user)
):
    """Get the list of workspaces created by the user."""
    try:
        workspaces = await workspace_service.get_user_workspaces(profile_id)
        return workspaces
    except Exception as e:
        logger.error(f"Error getting user workspaces: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get workspaces")


@public_workspace_router.post("/delete", response_model=WorkspaceDeleteResponse)
async def workspace_delete(
    workspace_id: str = Form(...),
    profile_id: str = Depends(get_current_user)
):
    """Delete a workspace."""
    try:
        workspace_id = sanitize_user_input(workspace_id, strict=True)
        success, error_message = await workspace_service.delete_workspace(profile_id, workspace_id)
        if success:
            return WorkspaceDeleteResponse(message=f"{workspace_id} is deleted")
        else:
            raise HTTPException(status_code=400, detail=error_message or "Failed to delete workspace")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting workspace: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to delete workspace")


@public_workspace_router.get("/get_chat_agents", response_model=WorkspaceAgentsResponse)
async def get_all_chat_agents(
    profile_id: str = Depends(get_current_user)
):
    """Get all chat agents from all workspaces for the authenticated profile."""
    try:
        return await workspace_service.get_all_chat_agents_for_profile(profile_id)
    except Exception as e:
        logger.error(f"Error getting all chat agents: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get chat agents")
