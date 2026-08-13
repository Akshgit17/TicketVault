"""
Logging, request correlation, and error reporting.

Replaces bare `print()` and unstructured logs. Every log line carries a
request id, so a user reporting "my payment failed at 3pm" can be traced across
the auth check, the Razorpay call, and the settlement write.

No hard dependency on Sentry — it activates only if SENTRY_DSN is set and the
SDK is installed.
"""
import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar

from app.config import settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

logger = logging.getLogger("tv.access")

# Attributes LogRecord always carries; anything else was passed via `extra`.
_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
}

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class JsonFormatter(logging.Formatter):
    """One JSON object per line — parseable by any log aggregator."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        rid = request_id_var.get()
        if rid:
            payload["request_id"] = rid

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable, for local development."""

    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        prefix = f"[{rid}] " if rid else ""
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {prefix}{record.name}: {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging() -> None:
    formatter = JsonFormatter() if settings.LOG_FORMAT == "json" else ConsoleFormatter()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.LOG_LEVEL.upper())

    # uvicorn duplicates access logs in its own format; ours carries request ids.
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
    for noisy in ("httpx", "httpcore", "hpack", "apscheduler.executors.default"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def configure_sentry() -> bool:
    """Initialise Sentry if configured. Returns whether it was enabled."""
    if not settings.SENTRY_DSN:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger(__name__).warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; error reporting disabled."
        )
        return False

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        # Payment payloads and auth headers must not leave the building.
        send_default_pii=False,
    )
    return True


def _clean_request_id(raw: bytes | None) -> str | None:
    """
    Accept an inbound request id only if it is well-formed.

    It ends up in log output, so an unvalidated header is a log-injection
    vector (newlines, forged JSON fields).
    """
    if not raw:
        return None
    try:
        candidate = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    return candidate if _SAFE_REQUEST_ID.match(candidate) else None


class RequestContextMiddleware:
    """
    Pure-ASGI middleware: assigns a request id, echoes it back as a header, and
    logs one structured line per request with status and duration.

    Written as raw ASGI rather than BaseHTTPMiddleware to avoid the extra task
    wrapping, which interferes with contextvar propagation into threadpooled
    handlers.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        rid = _clean_request_id(headers.get(b"x-request-id")) or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)

        # Also stash it on the scope. Starlette's ServerErrorMiddleware — which
        # invokes the 500 handler — sits *outside* user middleware, so by the
        # time it runs the contextvar below has already been reset and the
        # handler would report a null request id. The scope survives.
        scope["request_id"] = rid

        started = time.perf_counter()
        status = 500

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            path = scope.get("path", "")
            # Health checks are high-frequency and uninteresting when healthy.
            level = logging.DEBUG if path.startswith("/health") and status < 400 else logging.INFO
            logger.log(
                level,
                "%s %s -> %s",
                scope.get("method", "?"), path, status,
                extra={
                    "http_method": scope.get("method"),
                    "http_path": path,
                    "http_status": status,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)


def current_request_id() -> str | None:
    return request_id_var.get()
