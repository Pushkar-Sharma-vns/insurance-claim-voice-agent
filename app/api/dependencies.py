import logging

from fastapi import Header, HTTPException, Query

from app.config import settings

logger = logging.getLogger(__name__)


def _fp(s: str) -> str:
    """Masked fingerprint for debugging auth mismatches — never logs the full secret."""
    return f"{s[:3]}…{s[-3:]}(len{len(s)})" if s else "(empty)"


def verify_vapi_secret(
    x_vapi_secret: str = Header(default=""),
    authorization: str = Header(default=""),
    secret: str = Query(default=""),
):
    """Accept the shared VAPI_SECRET from whichever channel the caller uses:
    - server webhooks / tools      -> `X-Vapi-Secret` header
    - custom LLM /chat/completions -> `?secret=<VAPI_SECRET>` query param. VAPI's Bearer
      token for a custom LLM is a fixed placeholder we can't set, so we pass the secret in
      the URL instead. An `Authorization` header (raw or `Bearer `-prefixed) is also accepted.

    NOTE: a query-param secret can surface in access/proxy logs — acceptable for this demo;
    prefer a header in production.
    """
    auth_token = authorization[7:] if authorization[:7].lower() == "bearer " else authorization
    # VAPI appends "/chat/completions" to the configured Custom LLM URL, so a secret passed as
    # a query param arrives as "<secret>/chat/completions". Recover the part before the slash.
    query_secret = secret.split("/", 1)[0]
    if settings.vapi_secret and settings.vapi_secret in (x_vapi_secret, auth_token, query_secret):
        return
    logger.warning(
        "Auth rejected: x_vapi_secret=%s authorization_token=%s query_secret=%s expected=%s",
        _fp(x_vapi_secret), _fp(auth_token), _fp(query_secret), _fp(settings.vapi_secret),
    )
    raise HTTPException(status_code=401, detail="Invalid Vapi secret")
