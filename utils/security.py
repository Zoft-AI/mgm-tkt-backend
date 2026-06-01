"""
Security Utilities

This module contains security-related utility functions for file validation,
input sanitization, and other security checks.
"""

import os
from pathlib import Path
from typing import Tuple

from fastapi import UploadFile


# File security configuration
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_FILE_EXTENSIONS = {'.pdf', '.txt', '.docx'}
ALLOWED_MIME_TYPES = {
    'application/pdf',
    'text/plain', 
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword'
}


def validate_file_security(file: UploadFile) -> Tuple[bool, str]:
    """
    Validate uploaded file for security issues.
    
    Args:
        file: The uploaded file to validate
        
    Returns:
        Tuple[bool, str]: (is_valid, error_message)
        - is_valid: True if file passes all security checks
        - error_message: Empty string if valid, error description if invalid
    """
    # Check file size
    if hasattr(file, 'size') and file.size and file.size > MAX_FILE_SIZE:
        return False, f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"
    
    # Check filename
    if not file.filename or file.filename.strip() == '':
        return False, "Invalid filename"
    
    # Check for path traversal
    if '..' in file.filename or '/' in file.filename or '\\' in file.filename:
        return False, "Invalid filename - path traversal detected"
    
    # Check file extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_FILE_EXTENSIONS:
        return False, f"File type not allowed. Allowed types: {', '.join(ALLOWED_FILE_EXTENSIONS)}"
    
    # Check MIME type
    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        return False, f"MIME type not allowed: {file.content_type}"
    
    return True, ""


def sanitize_filename(filename: str) -> str:
    """
    Sanitize a filename by removing potentially dangerous characters.
    
    Args:
        filename: The original filename
        
    Returns:
        str: Sanitized filename
    """
    if not filename:
        return "unnamed_file"
    
    # Remove path separators and other dangerous characters
    dangerous_chars = ['/', '\\', '..', ':', '*', '?', '"', '<', '>', '|']
    sanitized = filename
    
    for char in dangerous_chars:
        sanitized = sanitized.replace(char, '_')
    
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(' .')
    
    # Ensure filename is not empty after sanitization
    if not sanitized:
        return "unnamed_file"
    
    return sanitized


def validate_file_path(file_path: str) -> bool:
    """
    Validate that a file path is safe and doesn't contain path traversal attempts.
    
    Args:
        file_path: The file path to validate
        
    Returns:
        bool: True if path is safe, False otherwise
    """
    # Check for path traversal attempts
    if '..' in file_path:
        return False
    
    # Check for absolute paths (should be relative)
    if os.path.isabs(file_path):
        return False
    
    # Normalize the path and check it hasn't changed
    normalized = os.path.normpath(file_path)
    if normalized != file_path:
        return False
    
    return True


def mask_sensitive_data(email: str) -> str:
    """
    Mask sensitive data in email addresses for logging.
    
    Args:
        email: The email address to mask
        
    Returns:
        str: Masked email address
    """
    if not email or '@' not in email:
        return "unknown"
    
    try:
        local, domain = email.split('@', 1)
        if len(local) <= 3:
            masked_local = '*' * len(local)
        else:
            masked_local = local[:3] + '*' * (len(local) - 3)
        return f"{masked_local}@{domain}"
    except Exception:
        return "unknown"


def validate_session_id(session_id: str) -> bool:
    """
    Validate session ID format and content.
    
    Args:
        session_id: The session ID to validate
        
    Returns:
        bool: True if session ID is valid format, False otherwise
    """
    if not session_id:
        return False
    
    # Check length (UUIDs are typically 36 characters with hyphens)
    if len(session_id) < 10 or len(session_id) > 50:
        return False
    
    # Check for basic format (alphanumeric with hyphens)
    allowed_chars = set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-')
    if not set(session_id).issubset(allowed_chars):
        return False
    
    return True 