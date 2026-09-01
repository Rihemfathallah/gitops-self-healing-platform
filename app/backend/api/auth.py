"""
api/auth.py
-----------
Simple API key authentication via X-API-Key header.
"""

import hmac
import logging

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from config import settings

logger = logging.getLogger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    """
    Validate the X-API-Key header against the configured API_KEY.

    Raises:
        HTTPException 401: Missing header
        HTTPException 403: Invalid key
    """
    if api_key is None:
        raise HTTPException(status_code=401, detail="Missing X-API-Key header")
    if not hmac.compare_digest(api_key, settings.api_key):
        logger.warning("invalid API key attempt")
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key
