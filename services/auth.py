"""
Authentication Service

Custom JWT authentication with bcrypt password hashing.
No Supabase Auth SDK - works directly with PostgreSQL auth_users table.
"""

import logging
import uuid
import hashlib
import secrets
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from jose import jwt, JWTError
import bcrypt as _bcrypt
import os

from utils.database import get_db

logger = logging.getLogger(__name__)

JWT_SECRET = os.environ.get("JWT_SECRET", "change-me-in-production-64-chars-minimum-please")
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.environ.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "7"))


class AuthService:
    """Authentication service with custom JWT + bcrypt"""

    def __init__(self):
        self.db = get_db()

    # ------------------------------------------------------------------
    # Password hashing
    # ------------------------------------------------------------------

    def hash_password(self, password: str) -> str:
        return _bcrypt.hashpw(
            password.encode("utf-8"), _bcrypt.gensalt()
        ).decode("utf-8")

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            return _bcrypt.checkpw(
                password.encode("utf-8"), password_hash.encode("utf-8")
            )
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Token creation
    # ------------------------------------------------------------------

    def create_access_token(self, user_id: str, email: str) -> str:
        payload = {
            "sub": user_id,
            "email": email,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
            "iat": datetime.now(timezone.utc),
            "type": "access"
        }
        return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

    def create_refresh_token(self) -> str:
        return secrets.token_urlsafe(48)

    # ------------------------------------------------------------------
    # Core auth operations
    # ------------------------------------------------------------------

    async def signup(self, email: str, password: str, name: Optional[str] = None) -> Dict[str, Any]:
        """Register a new user. Trigger auto-creates profile + workspace."""
        email = email.lower().strip()

        existing = await self.db.fetchrow(
            "SELECT id FROM auth_users WHERE email = $1", email
        )
        if existing:
            raise HTTPException(status_code=409, detail="User with this email already exists")

        password_hash = self.hash_password(password)
        display_name = name or email.split("@")[0]

        user = await self.db.fetchrow(
            """INSERT INTO auth_users (email, password_hash, name, email_verified, provider)
               VALUES ($1, $2, $3, true, 'email')
               RETURNING id, email, name, created_at""",
            email, password_hash, display_name
        )

        if not user:
            raise HTTPException(status_code=500, detail="Failed to create user")

        user_id = str(user["id"])
        tokens = await self._issue_tokens(user_id, email)

        logger.info(f"User signed up: {email}")
        return {
            "status": "success",
            "profile_id": user_id,
            **tokens
        }

    async def signin(self, email: str, password: str) -> Dict[str, Any]:
        """Authenticate user and issue JWT tokens"""
        email = email.lower().strip()

        user = await self.db.fetchrow(
            "SELECT id, email, password_hash, name, is_active FROM auth_users WHERE email = $1",
            email
        )

        if not user:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if not user["password_hash"]:
            raise HTTPException(status_code=401, detail="Account uses OAuth login. Please sign in with Google.")

        if not self.verify_password(password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        if not user["is_active"]:
            raise HTTPException(status_code=403, detail="Account is disabled")

        await self.db.execute(
            "UPDATE auth_users SET last_sign_in_at = NOW() WHERE id = $1",
            user["id"]
        )

        user_id = str(user["id"])
        tokens = await self._issue_tokens(user_id, user["email"])

        logger.info(f"User signed in: {email}")
        return {
            "status": "success",
            "profile_id": user_id,
            **tokens
        }

    async def verify_login(self, authorization: str) -> str:
        """
        Validate JWT from Authorization header. Returns user_id (profile_id).
        This is a LOCAL decode - no remote call needed.
        """
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization header required")

        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header format. Must use Bearer scheme.")

        token = authorization[7:]  # Strip "Bearer "
        if not token:
            raise HTTPException(status_code=401, detail="Empty token provided")

        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        except JWTError as e:
            logger.warning(f"JWT decode failed: {str(e)}")
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        token_type = payload.get("type")
        if token_type != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        return user_id

    async def refresh_tokens(self, refresh_token: str) -> Dict[str, Any]:
        """Exchange a valid refresh token for new access + refresh tokens"""
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()

        record = await self.db.fetchrow(
            """SELECT rt.id, rt.user_id, rt.expires_at, rt.revoked,
                      au.email, au.is_active
               FROM auth_refresh_tokens rt
               JOIN auth_users au ON au.id = rt.user_id
               WHERE rt.token_hash = $1""",
            token_hash
        )

        if not record:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        if record["revoked"]:
            raise HTTPException(status_code=401, detail="Refresh token has been revoked")

        if record["expires_at"] < datetime.now(timezone.utc):
            raise HTTPException(status_code=401, detail="Refresh token has expired")

        if not record["is_active"]:
            raise HTTPException(status_code=403, detail="Account is disabled")

        # Revoke old token
        await self.db.execute(
            "UPDATE auth_refresh_tokens SET revoked = true, revoked_at = NOW() WHERE id = $1",
            record["id"]
        )

        # Issue new pair
        user_id = str(record["user_id"])
        tokens = await self._issue_tokens(user_id, record["email"])

        return {"status": "success", "profile_id": user_id, **tokens}

    async def signout(self, authorization: str) -> Dict[str, str]:
        """Revoke all refresh tokens for the user"""
        user_id = await self.verify_login(authorization)

        await self.db.execute(
            "UPDATE auth_refresh_tokens SET revoked = true, revoked_at = NOW() WHERE user_id = $1 AND revoked = false",
            uuid.UUID(user_id)
        )

        logger.info(f"User signed out, tokens revoked: {user_id}")
        return {"status": "success", "message": "Signed out successfully"}

    async def get_current_user(self, authorization: str) -> Dict[str, Any]:
        """Get user profile info from JWT (replaces Supabase /auth/v1/user)"""
        user_id = await self.verify_login(authorization)

        user = await self.db.fetchrow(
            """SELECT au.id, au.email, au.name, au.provider, au.email_verified,
                      au.created_at, au.last_sign_in_at
               FROM auth_users au WHERE au.id = $1""",
            uuid.UUID(user_id)
        )

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        return {
            "id": str(user["id"]),
            "email": user["email"],
            "name": user["name"],
            "provider": user["provider"],
            "email_verified": user["email_verified"],
            "created_at": user["created_at"].isoformat() if user["created_at"] else None,
            "last_sign_in_at": user["last_sign_in_at"].isoformat() if user["last_sign_in_at"] else None,
        }

    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------

    async def forgot_password(self, email: str) -> Dict[str, str]:
        """Generate a password reset token"""
        email = email.lower().strip()
        user = await self.db.fetchrow(
            "SELECT id, email FROM auth_users WHERE email = $1 AND is_active = true",
            email
        )

        # Always return success to prevent email enumeration
        if not user:
            return {"status": "success", "message": "If the email exists, a reset link has been sent"}

        reset_token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        await self.db.execute(
            """UPDATE auth_users
               SET password_reset_token = $1, password_reset_expires_at = $2
               WHERE id = $3""",
            reset_token, expires_at, user["id"]
        )

        # TODO: Send email with reset link containing the token
        logger.info(f"Password reset token generated for: {email}")

        return {"status": "success", "message": "If the email exists, a reset link has been sent"}

    async def reset_password(self, token: str, new_password: str) -> Dict[str, str]:
        """Reset password using a valid reset token"""
        user = await self.db.fetchrow(
            """SELECT id FROM auth_users
               WHERE password_reset_token = $1
                 AND password_reset_expires_at > NOW()
                 AND is_active = true""",
            token
        )

        if not user:
            raise HTTPException(status_code=400, detail="Invalid or expired reset token")

        password_hash = self.hash_password(new_password)

        await self.db.execute(
            """UPDATE auth_users
               SET password_hash = $1, password_reset_token = NULL, password_reset_expires_at = NULL
               WHERE id = $2""",
            password_hash, user["id"]
        )

        # Revoke all refresh tokens for security
        await self.db.execute(
            "UPDATE auth_refresh_tokens SET revoked = true, revoked_at = NOW() WHERE user_id = $1 AND revoked = false",
            user["id"]
        )

        logger.info(f"Password reset completed for user: {user['id']}")
        return {"status": "success", "message": "Password has been reset. Please sign in again."}

    async def direct_reset_password(self, email: str, new_password: str) -> Dict[str, str]:
        """Reset password directly by email (no token required)"""
        email = email.lower().strip()

        user = await self.db.fetchrow(
            "SELECT id FROM auth_users WHERE email = $1 AND is_active = true",
            email
        )

        if not user:
            raise HTTPException(status_code=404, detail="No active account found with this email")

        password_hash = self.hash_password(new_password)

        await self.db.execute(
            "UPDATE auth_users SET password_hash = $1 WHERE id = $2",
            password_hash, user["id"]
        )

        await self.db.execute(
            "UPDATE auth_refresh_tokens SET revoked = true, revoked_at = NOW() WHERE user_id = $1 AND revoked = false",
            user["id"]
        )

        logger.info(f"Direct password reset completed for user: {user['id']}")
        return {"status": "success", "message": "Password has been reset. Please sign in with your new password."}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _issue_tokens(self, user_id: str, email: str) -> Dict[str, str]:
        """Generate access + refresh token pair and store refresh in DB.
        MD role gets 1-year session; all others get the default from .env (24hrs).
        """
        member = await self.db.fetchrow(
            "SELECT designation FROM members WHERE profile_id = $1", uuid.UUID(user_id)
        )

        if member and member["designation"] and "managing director" in member["designation"].lower():
            access_minutes = 525600  # 365 days
            refresh_days = 365
        else:
            access_minutes = ACCESS_TOKEN_EXPIRE_MINUTES
            refresh_days = REFRESH_TOKEN_EXPIRE_DAYS

        payload = {
            "sub": user_id,
            "email": email,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=access_minutes),
            "iat": datetime.now(timezone.utc),
            "type": "access"
        }
        access_token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

        refresh_token = self.create_refresh_token()
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(days=refresh_days)

        await self.db.execute(
            """INSERT INTO auth_refresh_tokens (user_id, token_hash, expires_at)
               VALUES ($1, $2, $3)""",
            uuid.UUID(user_id), token_hash, expires_at
        )

        return {"access_token": access_token, "refresh_token": refresh_token}


auth_service = AuthService()
