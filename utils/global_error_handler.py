import logging
import time
from datetime import datetime

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class GlobalErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Comprehensive global error handler that captures all uncaught exceptions."""
    
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = getattr(request.state, "request_id", "unknown")
        
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("User-Agent", "unknown")
        method = request.method
        url = str(request.url)
        
        try:
            response = await call_next(request)
            
            duration = time.time() - start_time
            logger.debug(
                f"Request completed - ID: {request_id}, "
                f"Method: {method}, URL: {url}, "
                f"Status: {response.status_code}, "
                f"Duration: {duration:.3f}s"
            )
            
            return response
            
        except HTTPException as http_exc:
            duration = time.time() - start_time
            logger.warning(
                f"HTTP Exception - Request ID: {request_id}, "
                f"Status Code: {http_exc.status_code}, "
                f"Detail: {http_exc.detail}, "
                f"Duration: {duration:.3f}s"
            )
            return JSONResponse(
                status_code=http_exc.status_code,
                content={
                    "detail": http_exc.detail,
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
        except ValueError as val_err:
            duration = time.time() - start_time
            logger.error(f"Value Error - Request ID: {request_id}, Error: {str(val_err)}")
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "Invalid input data provided",
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
        except TimeoutError as timeout_err:
            duration = time.time() - start_time
            logger.error(f"Timeout Error - Request ID: {request_id}, Error: {str(timeout_err)}")
            return JSONResponse(
                status_code=504,
                content={
                    "detail": "Request timeout. Please try again later.",
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat()
                }
            )
            
        except Exception as exc:
            duration = time.time() - start_time
            exc_type = type(exc).__name__
            exc_msg = str(exc)
            
            logger.error(
                f"Unhandled Exception - Request ID: {request_id}, "
                f"Type: {exc_type}, Message: {exc_msg}",
                exc_info=True
            )
            
            if "permission" in exc_msg.lower() or "unauthorized" in exc_msg.lower():
                status_code = 403
                detail = "Access denied"
            elif "not found" in exc_msg.lower():
                status_code = 404
                detail = "Resource not found"
            elif "database" in exc_msg.lower() or "connection" in exc_msg.lower():
                status_code = 503
                detail = "Service temporarily unavailable"
            else:
                status_code = 500
                detail = "An unexpected error occurred"
            
            return JSONResponse(
                status_code=status_code,
                content={
                    "detail": detail,
                    "request_id": request_id,
                    "timestamp": datetime.now().isoformat(),
                    "support_message": "Our team has been notified. Please contact support if the issue persists."
                }
            )
