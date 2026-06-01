"""
Workspace Pydantic Models

This module contains all Pydantic models for workspace-related operations.
Following the LLD architecture pattern for proper data validation and serialization.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime


class WorkspaceBase(BaseModel):
    """Base workspace model with common fields"""
    workspace_name: str = Field(..., min_length=1, max_length=100, description="Workspace name")
    twilio_SSID: Optional[str] = Field(None, description="Twilio Account SID")
    twilio_auth_token: Optional[str] = Field(None, description="Twilio Auth Token")
    elevenlabs_api_key: Optional[str] = Field(None, description="ElevenLabs API Key")
    openai_api_key: Optional[str] = Field(None, description="OpenAI API Key")

    @field_validator('workspace_name')
    @classmethod
    def validate_workspace_name(cls, v):
        if not v or v.strip() == '':
            raise ValueError('Workspace name cannot be empty')
        return v.strip()

    @field_validator('twilio_SSID', 'twilio_auth_token')
    @classmethod
    def validate_twilio_credentials(cls, v):
        # Convert empty strings to None for consistency
        if v is not None and v.strip() == '':
            return None
        return v

    @model_validator(mode='after')
    def validate_twilio_pair(self):
        """Ensure both Twilio SSID and Auth Token are provided together or both are empty"""
        ssid = self.twilio_SSID
        token = self.twilio_auth_token
        
        if (ssid and not token) or (token and not ssid):
            raise ValueError('Both Twilio SSID and Auth Token must be provided together')
        
        return self


class WorkspaceCreate(WorkspaceBase):
    """Model for creating a new workspace"""
    pass


class WorkspaceUpdate(WorkspaceBase):
    """Model for updating an existing workspace"""
    workspace_id: str = Field(..., description="Workspace ID to update")


class WorkspaceResponse(WorkspaceBase):
    """Model for workspace response data"""
    id: str
    profile_id: str
    is_owner: Optional[bool] = Field(default=False, description="True if user owns this workspace")
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkspaceAgentsRequest(BaseModel):
    """Model for getting agents by workspace request"""
    workspace_id: str = Field(..., description="Workspace ID")


class WorkspaceAgentsResponse(BaseModel):
    """Model for workspace agents response"""
    chat_agents: Optional[List[Dict[str, Any]]] = None
    phone_agents: Optional[List[Dict[str, Any]]] = None


class WorkspaceDeleteRequest(BaseModel):
    """Model for workspace deletion request"""
    workspace_id: str = Field(..., description="Workspace ID to delete")


class WorkspaceDeleteResponse(BaseModel):
    """Model for workspace deletion response"""
    message: str


class TwilioNumbersRequest(BaseModel):
    """Model for getting Twilio numbers request"""
    workspace_id: str = Field(..., description="Workspace ID")


class TwilioNumbersResponse(BaseModel):
    """Model for Twilio numbers response"""
    numbers: List[str] = Field(default_factory=list, description="List of Twilio phone numbers")


class WorkspaceCreateResponse(BaseModel):
    """Model for workspace creation response"""
    workspace_id: str


class APIValidationError(BaseModel):
    """Model for API validation error responses"""
    error: str
    details: Optional[str] = None


class WorkspaceListResponse(BaseModel):
    """Model for workspace list response"""
    workspaces: List[WorkspaceResponse] 