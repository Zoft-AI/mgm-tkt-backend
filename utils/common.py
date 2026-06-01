"""
Common Utilities

This module contains general utility functions that are used across the application,
including validation helpers, formatting functions, and other common operations.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone


logger = logging.getLogger(__name__)


def safe_json_loads(json_string: str, default: Any = None) -> Any:
    """
    Safely parse JSON string with fallback default value
    
    Args:
        json_string: JSON string to parse
        default: Default value to return if parsing fails
        
    Returns:
        Parsed JSON data or default value
    """
    if not json_string:
        return default
    
    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse JSON: {str(e)}")
        return default


def safe_json_dumps(data: Any, default: str = "{}") -> str:
    """
    Safely serialize data to JSON string with fallback
    
    Args:
        data: Data to serialize
        default: Default JSON string to return if serialization fails
        
    Returns:
        JSON string representation of data or default
    """
    try:
        return json.dumps(data)
    except (TypeError, ValueError) as e:
        logger.warning(f"Failed to serialize JSON: {str(e)}")
        return default


def validate_email(email: str) -> bool:
    """
    Validate email address format
    
    Args:
        email: Email address to validate
        
    Returns:
        True if email format is valid, False otherwise
    """
    if not email:
        return False
    
    # Basic email regex pattern
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def validate_password_strength(password: str) -> Dict[str, bool]:
    """
    Validate password strength and return detailed feedback
    
    Args:
        password: Password to validate
        
    Returns:
        Dictionary with validation results
    """
    if not password:
        return {
            "is_valid": False,
            "has_min_length": False,
            "has_uppercase": False,
            "has_lowercase": False,
            "has_digit": False,
            "has_special_char": False
        }
    
    return {
        "is_valid": (
            len(password) >= 8 and
            any(c.isupper() for c in password) and
            any(c.islower() for c in password) and
            any(c.isdigit() for c in password)
        ),
        "has_min_length": len(password) >= 8,
        "has_uppercase": any(c.isupper() for c in password),
        "has_lowercase": any(c.islower() for c in password),
        "has_digit": any(c.isdigit() for c in password),
        "has_special_char": any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password)
    }


def sanitize_input(input_string: str, max_length: int = 1000) -> str:
    """
    Sanitize user input by removing potentially dangerous characters
    
    Args:
        input_string: Input string to sanitize
        max_length: Maximum allowed length
        
    Returns:
        Sanitized input string
    """
    if not input_string:
        return ""
    
    # Remove control characters and limit length
    sanitized = ''.join(char for char in input_string if ord(char) >= 32)
    return sanitized[:max_length].strip()


def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format datetime object to string
    
    Args:
        dt: Datetime object to format
        format_str: Format string
        
    Returns:
        Formatted datetime string
    """
    try:
        return dt.strftime(format_str)
    except (AttributeError, ValueError):
        return ""


def parse_datetime(date_string: str) -> Optional[datetime]:
    """
    Parse datetime string to datetime object
    
    Args:
        date_string: Date string to parse
        
    Returns:
        Datetime object or None if parsing fails
    """
    if not date_string:
        return None
    
    # Common datetime formats to try
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y"
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_string, fmt)
        except ValueError:
            continue
    
    # Try ISO format parsing as last resort
    try:
        return datetime.fromisoformat(date_string.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        logger.warning(f"Failed to parse datetime: {date_string}")
        return None


def get_current_utc_timestamp() -> str:
    """
    Get current UTC timestamp as ISO format string
    
    Returns:
        Current UTC timestamp string
    """
    return datetime.now(timezone.utc).isoformat()


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Split a list into chunks of specified size
    
    Args:
        lst: List to chunk
        chunk_size: Size of each chunk
        
    Returns:
        List of chunks
    """
    if chunk_size <= 0:
        return [lst]
    
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def merge_dicts(*dicts: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge multiple dictionaries, with later dictionaries taking precedence
    
    Args:
        *dicts: Dictionaries to merge
        
    Returns:
        Merged dictionary
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


def extract_numbers_from_string(text: str) -> List[float]:
    """
    Extract all numbers from a text string
    
    Args:
        text: Text string to extract numbers from
        
    Returns:
        List of extracted numbers
    """
    if not text:
        return []
    
    # Pattern to match integers and floats
    pattern = r'-?\d+\.?\d*'
    matches = re.findall(pattern, text)
    
    numbers = []
    for match in matches:
        try:
            if '.' in match:
                numbers.append(float(match))
            else:
                numbers.append(float(int(match)))
        except ValueError:
            continue
    
    return numbers


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """
    Truncate string to maximum length with optional suffix
    
    Args:
        text: Text to truncate
        max_length: Maximum length
        suffix: Suffix to add if truncated
        
    Returns:
        Truncated string
    """
    if not text or len(text) <= max_length:
        return text
    
    if len(suffix) >= max_length:
        return text[:max_length]
    
    return text[:max_length - len(suffix)] + suffix


def is_valid_uuid(uuid_string: str) -> bool:
    """
    Check if string is a valid UUID
    
    Args:
        uuid_string: String to validate
        
    Returns:
        True if valid UUID, False otherwise
    """
    import uuid
    
    try:
        uuid.UUID(uuid_string)
        return True
    except (ValueError, TypeError):
        return False


def generate_slug(text: str, max_length: int = 50) -> str:
    """
    Generate a URL-friendly slug from text
    
    Args:
        text: Text to convert to slug
        max_length: Maximum length of slug
        
    Returns:
        URL-friendly slug
    """
    if not text:
        return ""
    
    # Convert to lowercase and replace spaces with hyphens
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    slug = re.sub(r'[-\s]+', '-', slug)
    slug = slug.strip('-')
    
    return slug[:max_length]


def calculate_file_hash(file_content: bytes, algorithm: str = "md5") -> str:
    """
    Calculate hash of file content
    
    Args:
        file_content: File content as bytes
        algorithm: Hash algorithm ('md5', 'sha256', etc.)
        
    Returns:
        Hex string of file hash
    """
    import hashlib
    
    try:
        hasher = hashlib.new(algorithm)
        hasher.update(file_content)
        return hasher.hexdigest()
    except (ValueError, AttributeError):
        logger.error(f"Unsupported hash algorithm: {algorithm}")
        return ""


def format_file_size(size_bytes: int) -> str:
    """
    Format file size in human-readable format
    
    Args:
        size_bytes: Size in bytes
        
    Returns:
        Formatted size string (e.g., "1.5 MB")
    """
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    size_index = 0
    size = float(size_bytes)
    
    while size >= 1024.0 and size_index < len(size_names) - 1:
        size /= 1024.0
        size_index += 1
    
    return f"{size:.1f} {size_names[size_index]}" 