from fastapi import FastAPI

from app.api.routers import tools, webhooks
from app.logging_setup import setup_logging

setup_logging()

app = FastAPI(title="Observe Insurance – Voice Agent API")

app.include_router(tools.router, prefix="/tools", tags=["Tools"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["Webhooks"])


@app.get("/health")
def health():
    return {"status": "ok"}
