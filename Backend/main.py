import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.observability import (
    RequestContextMiddleware,
    configure_logging,
    configure_sentry,
    current_request_id,
)

configure_logging()
_sentry_enabled = configure_sentry()

from app.jobs.scheduler import lifespan
from app.routes import (
    health, users, cities, events, listings, bookings, config, webhooks, sellers,
    admin, pricing,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="TicketVault API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*", "X-Request-ID"],
)

# Outermost middleware, so the request id covers CORS handling and errors too.
app.add_middleware(RequestContextMiddleware)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Log the full traceback; return an opaque error with the request id.

    Internal exception text can carry table names, SQL fragments, and provider
    responses. The user gets an id to quote at support; the detail stays in the
    logs.
    """
    logger.exception(
        "Unhandled error on %s %s", request.method, request.url.path,
        extra={"http_path": request.url.path},
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred.",
            # Scope first: this handler runs outside RequestContextMiddleware,
            # where the contextvar has already been reset.
            "request_id": request.scope.get("request_id") or current_request_id(),
        },
    )


app.include_router(health.router)
app.include_router(config.router)
app.include_router(users.router)
app.include_router(sellers.router)
app.include_router(cities.router)
app.include_router(events.router)
app.include_router(listings.router)
app.include_router(bookings.router)
app.include_router(webhooks.router)
app.include_router(admin.router)
app.include_router(pricing.router)

logger.info(
    "TicketVault API starting",
    extra={"environment": settings.ENVIRONMENT, "sentry_enabled": _sentry_enabled},
)
