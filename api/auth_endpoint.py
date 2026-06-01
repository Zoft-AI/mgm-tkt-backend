"""
Authentication Endpoints

Custom JWT auth endpoints - signup, signin, signout, refresh, me, password reset.
No Supabase Auth SDK dependency.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr

from services.auth import auth_service

logger = logging.getLogger(__name__)

auth_router = APIRouter(prefix="/auth", tags=["authentication"])
public_auth_router = APIRouter(prefix="/public/auth", tags=["public-authentication"])


# ------------------------------------------------------------------
# Request models
# ------------------------------------------------------------------

class SignupRequest(BaseModel):
    email: str
    password: str
    name: Optional[str] = None

class SigninRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class DirectResetPasswordRequest(BaseModel):
    email: str
    new_password: str


# ------------------------------------------------------------------
# Public auth endpoints (no JWT required)
# ------------------------------------------------------------------

@public_auth_router.post("/signup")
async def signup(request: Request, body: SignupRequest):
    """Register a new user with email/password"""
    try:
        result = await auth_service.signup(body.email, body.password, body.name)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signup error: {str(e)}")
        raise HTTPException(status_code=500, detail="Registration failed")


@public_auth_router.post("/signin")
async def signin(request: Request, body: SigninRequest):
    """Sign in with email/password, returns JWT tokens"""
    try:
        result = await auth_service.signin(body.email, body.password)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signin error: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication failed")


@public_auth_router.post("/refresh")
async def refresh_token(request: Request, body: RefreshRequest):
    """Exchange refresh token for new JWT pair"""
    try:
        result = await auth_service.refresh_tokens(body.refresh_token)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        raise HTTPException(status_code=500, detail="Token refresh failed")


@public_auth_router.post("/forgot-password")
async def forgot_password(request: Request, body: ForgotPasswordRequest):
    """Request a password reset email"""
    try:
        result = await auth_service.forgot_password(body.email)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Forgot password error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to process request")


@public_auth_router.post("/reset-password")
async def reset_password(request: Request, body: ResetPasswordRequest):
    """Reset password with valid reset token"""
    try:
        result = await auth_service.reset_password(body.token, body.new_password)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Reset password error: {str(e)}")
        raise HTTPException(status_code=500, detail="Password reset failed")


@public_auth_router.post("/direct-reset-password")
async def direct_reset_password(request: Request, body: DirectResetPasswordRequest):
    """Reset password directly with email + new password (no token/email flow)"""
    try:
        result = await auth_service.direct_reset_password(body.email, body.new_password)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Direct reset password error: {str(e)}")
        raise HTTPException(status_code=500, detail="Password reset failed")


# Keep backward compatibility: /public/auth/new still works
# (frontend calls this after login to sync with backend)
@public_auth_router.post("/new")
async def auth_new(request: Request, authorization: str = Header(...)):
    """
    Legacy endpoint: sync after login.
    Now just validates the JWT and returns the profile_id.
    """
    try:
        profile_id = await auth_service.verify_login(authorization)
        return JSONResponse(content={"status": "success", "profile_id": profile_id})
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in auth/new: {str(e)}")
        raise HTTPException(status_code=500, detail="Authentication failed")


# ------------------------------------------------------------------
# Protected auth endpoints (JWT required)
# ------------------------------------------------------------------

@auth_router.post("/signout")
async def auth_signout(request: Request, authorization: str = Header(...)):
    """Sign out and revoke all refresh tokens"""
    try:
        result = await auth_service.signout(authorization)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Signout error: {str(e)}")
        raise HTTPException(status_code=500, detail="Signout failed")


@auth_router.get("/me")
async def get_current_user(request: Request, authorization: str = Header(...)):
    """Get current user profile from JWT (replaces Supabase /auth/v1/user)"""
    try:
        result = await auth_service.get_current_user(authorization)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get user")


__all__ = ["auth_router", "public_auth_router"]
