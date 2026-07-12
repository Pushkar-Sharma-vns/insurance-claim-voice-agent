import logging

from fastapi import Header, HTTPException

from app.config import settings

logger = logging.getLogger(__name__)


def verify_vapi_secret(x_vapi_secret: str = Header(default="")):
    """VAPI sends the configured server.secret as the X-Vapi-Secret header."""
    if x_vapi_secret != settings.vapi_secret:
        logger.warning("Rejected request: invalid or missing Vapi secret")
        raise HTTPException(status_code=401, detail="Invalid Vapi secret")
