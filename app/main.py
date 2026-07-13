import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routers import chat, tools, webhooks
from app.logging_setup import setup_logging
from app.services import store

setup_logging()
store.init_db()  # S2/S3/S4 SQLite substrate

logger = logging.getLogger(__name__)

app = FastAPI(title="Observe Insurance – Voice Agent API")

app.include_router(tools.router, prefix="/tools", tags=["Tools"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])
app.include_router(chat.router, prefix="/vapi", tags=["Custom LLM"])


@app.exception_handler(Exception)
async def unhandled_exception(request: Request, exc: Exception):
    """Any uncaught error -> full traceback + method/path in the logs (console, app.log, and
    the per-call file if call_id is set), and a clean 500 to the caller instead of a bare crash."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


@app.get("/health")
def health():
    return {"status": "ok"}
