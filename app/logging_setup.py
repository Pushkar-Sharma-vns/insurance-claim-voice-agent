"""Per-call logging: every log line for a call also lands in log/<callId>.log.

The call id is stashed in a contextvar at the start of each request; a handler
reads it per record and appends to that call's file. Console output is kept too.
"""
import contextvars
import logging
from pathlib import Path

call_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("call_id", default=None)

LOG_DIR = Path("log")
_FMT = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")


def _safe(name: str) -> str:
    """Strip anything that isn't filename-safe (call id comes from an external payload)."""
    return "".join(c for c in name if c.isalnum() or c in "-_") or "unknown"


class PerCallFileHandler(logging.Handler):
    def emit(self, record):
        call_id = call_id_var.get()
        if not call_id:
            return  # no call context (e.g. auth failure before parse) -> console only
        LOG_DIR.mkdir(exist_ok=True)
        # ponytail: open/append/close per line — fine at call-log volume, no handle to leak
        with open(LOG_DIR / f"{_safe(call_id)}.log", "a") as f:
            f.write(self.format(record) + "\n")


def setup_logging():
    stream = logging.StreamHandler()
    stream.setFormatter(_FMT)
    per_call = PerCallFileHandler()
    per_call.setFormatter(_FMT)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [stream, per_call]
