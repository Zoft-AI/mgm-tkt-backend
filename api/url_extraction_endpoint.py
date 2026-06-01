import asyncio
from fastapi import APIRouter, Request
from newspaper import Article
from utils.sanitize import validate_and_sanitize_json

url_extraction_router = APIRouter(prefix="/url", tags=["url_extraction"])


async def extract_text_from_url(url):
    """Extract text content from a URL using newspaper library"""
    article = Article(url)
    article.download()
    article.parse()
    return article.text


@url_extraction_router.post("/extract/word")
async def extract_wcount_from_url(request: Request):
    """Extract word and character count from a URL with timeout."""
    data = await request.json()
    data = validate_and_sanitize_json(data)

    euid = data.get("euid")
    url = data.get("url")
    timeout = 10

    try:
        characters = await asyncio.wait_for(extract_text_from_url(url), timeout=timeout)
        return {
            "euid": euid,
            "char_count": len(characters),
            "word_count": len(characters.split())
        }
    except TimeoutError:
        return {
            "euid": euid,
            "error": f"Request timed out after {timeout} seconds"
        }
    except Exception as e:
        return {
            "euid": euid,
            "error": f"Error processing URL: {str(e)}"
        }
