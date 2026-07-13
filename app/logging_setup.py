"""Logging: three sinks.

- console (dev)
- log/app.log        — durable catch-all (RotatingFileHandler): EVERY record from every
                       module, incl. errors logged before a call_id is known (e.g. auth
                       rejections) and full tracebacks. This is the debug log.
- log/<callId>.log   — per-call file: records tagged with a call_id (set at the top of each
                       request). One file per call for its trace + tool calls + errors.

The formatter includes the function name so error lines say WHERE they came from.
"""
import contextvars
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

call_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("call_id", default=None)

LOG_DIR = Path("log")
_FMT = logging.Formatter("%(asctime)s %(levelname)s %(name)s.%(funcName)s: %(message)s")


def _safe(name: str) -> str:
    """Strip anything that isn't filename-safe (call id comes from an external payload)."""
    return "".join(c for c in name if c.isalnum() or c in "-_") or "unknown"


class PerCallFileHandler(logging.Handler):
    def emit(self, record):
        call_id = call_id_var.get()
        if not call_id:
            return  # no call context -> console + app.log only (app.log is the catch-all)
        try:
            # ponytail: open/append/close per line — fine at call-log volume, no handle to leak
            with open(LOG_DIR / f"{_safe(call_id)}.log", "a") as f:
                f.write(self.format(record) + "\n")
        except Exception:  # logging must never crash the request
            self.handleError(record)


def setup_logging():
    LOG_DIR.mkdir(exist_ok=True)

    stream = logging.StreamHandler()
    stream.setFormatter(_FMT)

    per_call = PerCallFileHandler()
    per_call.setFormatter(_FMT)

    # durable catch-all: everything lands here regardless of call context, so pre-call-id
    # errors (auth 401s) and tracebacks are always recoverable for debugging.
    app_file = RotatingFileHandler(LOG_DIR / "app.log", maxBytes=5_000_000, backupCount=3)
    app_file.setFormatter(_FMT)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [stream, per_call, app_file]
    # NOTE: we deliberately do NOT touch uvicorn's loggers. `uvicorn.error` is uvicorn's
    # (misleadingly named) general logger — routing it here just prints normal startup INFO
    # as "uvicorn.error.*", which looks alarming. Our own errors are captured via app.*
    # loggers + the global exception handler in main.py.
