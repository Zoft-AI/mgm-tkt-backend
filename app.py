import logging
import os
import time
import threading
import secrets
import json
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import httpx
from dotenv import load_dotenv

from config import Config
from api.auth_endpoint import auth_router, public_auth_router
from api.workspace_endpoint import workspace_router, public_workspace_router
from api.request_endpoint import request_router, public_request_router
from api.member_endpoint import member_router, public_invitation_router
from api.url_extraction_endpoint import url_extraction_router
from services.auth import auth_service
from utils.database import db_manager
from utils.global_error_handler import GlobalErrorHandlerMiddleware
from utils.sanitize import sanitize_user_input
from utils.storage_operations import check_s3_health

load_dotenv()

log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Global HTTP client for connection reuse
_http_client = None


async def get_http_client():
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(
                max_keepalive_connections=100,
                max_connections=200,
                keepalive_expiry=30.0,
            ),
            http2=True,
        )
    return _http_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting MGM Ticket Backend")

    # Initialize database pool
    await db_manager.connect()
    logger.info("PostgreSQL connection pool initialized")

    # Initialize HTTP client
    await get_http_client()
    logger.info("HTTP client pool initialized")

    yield

    # Shutdown
    global _http_client
    if _http_client:
        await _http_client.aclose()
        logger.info("HTTP client pool closed")

    await db_manager.close()
    logger.info("PostgreSQL connection pool closed")

    logger.info("Application shutdown complete")


app = FastAPI(
    title="MGM Ticket Backend API",
    description="Backend API for MGM Ticket Frontend",
    version="1.0.0",
    lifespan=lifespan,
)

logger.info(f"Starting application in {os.environ.get('ENVIRONMENT_details', 'production')} environment")


class RateLimiter:
    def __init__(self):
        self.requests = {}
        self.window_size = 60
        self.max_requests = 200
        self._lock = threading.Lock()
        self.cleanup_interval = 30
        self.last_cleanup = time.time()
        self.whitelist_ips = {"127.0.0.1", "localhost", "::1"}

    async def __call__(self, request: Request, call_next):
        client_ip = request.client.host
        now = time.time()

        if (client_ip in self.whitelist_ips or
            request.url.path in ["/health", "/", "/docs", "/openapi.json"]):
            return await call_next(request)

        if now - self.last_cleanup > self.cleanup_interval:
            with self._lock:
                for ip in list(self.requests.keys()):
                    self.requests[ip] = [t for t in self.requests[ip] if now - t < self.window_size]
                    if not self.requests[ip]:
                        del self.requests[ip]
                self.last_cleanup = now

        with self._lock:
            if client_ip not in self.requests:
                self.requests[client_ip] = []
            else:
                self.requests[client_ip] = [t for t in self.requests[client_ip] if now - t < self.window_size]

            if len(self.requests[client_ip]) >= self.max_requests:
                logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later.", "retry_after": self.window_size}
                )

            self.requests[client_ip].append(now)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "*"
            response.headers["Access-Control-Allow-Headers"] = "*"
            return response

        response = await call_next(request)

        if os.environ.get("ENVIRONMENT_details", "production").lower() != "development":
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = "default-src 'self' *; script-src 'self' 'unsafe-inline' *; style-src 'self' 'unsafe-inline' *; img-src 'self' data: *"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        else:
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-XSS-Protection"] = "1; mode=block"

        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = secrets.token_hex(8)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# Add middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)

current_env = os.environ.get("ENVIRONMENT_details", "production").lower()
logger.info(f"Running in {current_env} environment")

if current_env != "development":
    logger.info("Rate limiting enabled for production")
    app.middleware("http")(RateLimiter())
else:
    logger.info("Rate limiting disabled in development mode")

# CORS
ALLOW_ORIGIN = os.environ.get("ALLOW_ORIGIN", "").split(",") if os.environ.get("ALLOW_ORIGIN") else []

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

# Include routers
app.include_router(auth_router)
app.include_router(public_auth_router)
app.include_router(workspace_router)
app.include_router(public_workspace_router)
app.include_router(url_extraction_router)
app.include_router(request_router)
app.include_router(public_request_router)
app.include_router(member_router)
app.include_router(public_invitation_router)


@app.get("/template/get_agents")
async def get_templates(
    request: Request,
    authorization: str = Header(...)
):
    authorization = sanitize_user_input(authorization, strict=True) if authorization else ""
    profile_id = await auth_service.verify_login(authorization)
    if profile_id:
        rows = await db_manager.fetch(
            """SELECT * FROM "Chat_Agents" WHERE id IN (
                SELECT id FROM "Chat_Agents" LIMIT 50
            )"""
        )
        from utils.database import records_to_list
        all_templates = {"chat_agents": records_to_list(rows)}
        return JSONResponse(content=all_templates)
    else:
        raise HTTPException(status_code=401, detail="Login session expired, please login again.")


@app.get("/")
async def root():
    return {
        "api": "MGM Ticket Backend",
        "version": app.version,
        "status": "active",
        "documentation": "/docs",
        "environment": os.environ.get("ENVIRONMENT_details", "production"),
        "timestamp": datetime.now().isoformat()
    }


@app.get("/health", include_in_schema=False)
async def health_check():
    status = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": app.version,
        "services": {}
    }

    # Test database
    try:
        result = await db_manager.fetchval("SELECT get_service_status()")
        status["services"]["database"] = "healthy" if result == "ok" else "unhealthy"
    except Exception as e:
        logger.error(f"Database health check failed: {str(e)}")
        status["services"]["database"] = "unhealthy"

    # Test Redis
    try:
        redis_ping = db_manager.redis.ping()
        status["services"]["redis"] = "healthy" if redis_ping else "unhealthy"
    except Exception as e:
        logger.error(f"Redis health check failed: {str(e)}")
        status["services"]["redis"] = "unhealthy"

    # Test S3
    try:
        s3_ok = await check_s3_health()
        status["services"]["s3"] = "healthy" if s3_ok else "unhealthy"
    except Exception as e:
        logger.error(f"S3 health check failed: {str(e)}")
        status["services"]["s3"] = "unhealthy"

    if "unhealthy" in status["services"].values():
        status["status"] = "degraded"
        return JSONResponse(content=status, status_code=503)

    return status


# Global error handler
app.add_middleware(GlobalErrorHandlerMiddleware)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000, log_level="info")
