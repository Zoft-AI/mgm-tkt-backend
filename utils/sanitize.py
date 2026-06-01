import re
from typing import Any, Dict, Union
try:
    import nh3
except ImportError:
    nh3 = None
from markupsafe import escape as markup_escape


def sanitize_payload(payload: str) -> str:
    """Basic sanitization for XSS and SQL injection patterns."""
    payload = re.sub(r'<[^>]*>', '', payload)
    payload = re.sub(r'[;\']', '', payload)
    return payload


def sanitize_html_content(content: str, allowed_tags: list = None) -> str:
    """Advanced HTML sanitization using nh3 or basic escaping."""
    if nh3:
        if allowed_tags:
            return nh3.clean(content, tags=set(allowed_tags))
        return nh3.clean(content)
    else:
        return str(markup_escape(content))


def sanitize_user_input(data: Union[str, Dict[str, Any]], strict: bool = True) -> Union[str, Dict[str, Any]]:
    """Comprehensive user input sanitization."""
    if isinstance(data, str):
        if strict:
            data = re.sub(r'<[^>]*>', '', data)
            data = re.sub(r'javascript:', '', data, flags=re.IGNORECASE)
            data = re.sub(r'on\w+\s*=', '', data, flags=re.IGNORECASE)
        else:
            data = sanitize_html_content(data, allowed_tags=['b', 'i', 'u', 'em', 'strong'])
        
        data = re.sub(r'[;\']', '', data)
        data = re.sub(r'\b(union|select|insert|update|delete|drop|exec|script)\b', '', data, flags=re.IGNORECASE)
        
        return data.strip()
    
    elif isinstance(data, dict):
        return {key: sanitize_user_input(value, strict) for key, value in data.items()}
    
    return data


def validate_and_sanitize_json(json_data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and sanitize JSON payload for API endpoints."""
    return sanitize_user_input(json_data, strict=True)
