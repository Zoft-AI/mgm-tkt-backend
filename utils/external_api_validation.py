"""
External API Validation Utilities

This module contains functions to validate external API credentials
for services like Twilio, OpenAI, and ElevenLabs.
"""

import logging
import httpx

try:
    from elevenlabs.client import ElevenLabs
except ImportError:
    ElevenLabs = None

try:
    from twilio.rest import Client as twilio_rest
except ImportError:
    twilio_rest = None

logger = logging.getLogger(__name__)

# Global HTTP client for connection reuse
_http_client = None

async def get_http_client():
    """Get or create a shared HTTP client with connection pooling"""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=10.0,
            limits=httpx.Limits(
                max_keepalive_connections=50,
                max_connections=100,
            ),
        )
    return _http_client

def check_elevenlabs(eleven_api_key):
    """
    Validate ElevenLabs API key.
    
    Args:
        eleven_api_key: The ElevenLabs API key to validate
        
    Returns:
        int: 1 if valid, Exception object if invalid
    """
    try:
        client = ElevenLabs(
            api_key=eleven_api_key,
        )
        return 1
    except Exception as e:
        return e

def check_twilio_creds(SSID, auth_token):
    """
    Validate Twilio credentials.
    
    Args:
        SSID: Twilio Account SID
        auth_token: Twilio Auth Token
        
    Returns:
        str: "OK" if valid, error message if invalid
    """
    try:
        client = twilio_rest(SSID, auth_token)
        account = client.api.accounts(SSID).fetch()
        logger.info("Twilio credentials validated successfully")
        logger.debug(f"Account SID: {account.sid}")
        return "OK"
    except Exception as e:
        error_msg = str(e)
        if "invalid username" in error_msg:
            return "Invalid Twilio SSID"
        elif "auth" in error_msg.lower():
            return "Invalid Twilio Auth token"
        else:
            logger.error(f"Twilio credential validation error: {error_msg}")
            return f"Twilio validation error: {error_msg}"

async def check_openai_api_key_async(api_key):
    """
    Validate an OpenAI API key by making an async request to the models endpoint.
    
    Args:
        api_key: The OpenAI API key to validate
        
    Returns:
        bool: True if valid, False if invalid
        str: Error message if an unexpected error occurs
    """
    url = "https://api.openai.com/v1/models"
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    try:
        client = await get_http_client()
        response = await client.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            return True
        elif response.status_code == 401:
            return False
        else:
            return f"API error: {response.status_code}"
    except httpx.TimeoutException:
        logger.warning("OpenAI API key validation request timed out")
        return "API request timed out"
    except httpx.RequestError as e:
        logger.error(f"Error validating OpenAI API key: {str(e)}")
        return f"Connection error: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error validating OpenAI API key: {str(e)}")
        return f"Unexpected error: {str(e)}"


def check_openai_api_key(api_key):
    """
    Sync wrapper for backward compatibility - runs async validation in event loop.
    For new code, use check_openai_api_key_async instead.
    """
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If event loop is running, use thread to avoid blocking
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, check_openai_api_key_async(api_key))
                return future.result(timeout=10)
        else:
            return loop.run_until_complete(check_openai_api_key_async(api_key))
    except Exception as e:
        logger.error(f"Error in sync wrapper: {str(e)}")
        return f"Validation error: {str(e)}" 