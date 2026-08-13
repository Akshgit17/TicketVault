"""
Phase 1.7 — guard against blocking the event loop.

supabase-py and razorpay are synchronous clients. Calling them from an
`async def` route handler blocks the event loop for the duration of the network
round trip, so one slow query stalls every concurrent request in the process.

FastAPI runs plain `def` handlers in a threadpool automatically, so the rule is:
a handler may be `async def` only if it genuinely awaits something. Anything
else must be `def`, or must push its blocking work through run_in_threadpool.

This test is structural on purpose — it fails when someone reintroduces the
pattern, which review alone reliably misses.
"""
import ast
import pathlib

import pytest

ROUTES_DIR = pathlib.Path(__file__).resolve().parent.parent / "app" / "routes"

# Handlers that must stay async because they await a real coroutine, and which
# delegate their blocking work explicitly.
ALLOWED_ASYNC = {
    "create_listing",    # await qr_file.read() -> run_in_threadpool(_persist_listing)
    "razorpay_webhook",  # await request.body() -> run_in_threadpool(_process)
    "get_public_config", # pure compute, no I/O at all
}


def _route_files():
    return sorted(p for p in ROUTES_DIR.glob("*.py") if p.name != "__init__.py")


def _is_route_handler(fn: ast.AsyncFunctionDef) -> bool:
    """True if decorated with @router.get/post/... — i.e. FastAPI dispatches it."""
    for dec in fn.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
            if target.value.id == "router":
                return True
    return False


def _async_handlers(path: pathlib.Path):
    """Async route handlers only — plain async helpers are free to await."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and _is_route_handler(n)
    ]


@pytest.mark.parametrize("path", _route_files(), ids=lambda p: p.name)
def test_no_blocking_async_handlers(path):
    offenders = [
        fn.name for fn in _async_handlers(path) if fn.name not in ALLOWED_ASYNC
    ]
    assert not offenders, (
        f"{path.name}: {offenders} are `async def` but not in the allow-list. "
        "If the handler does blocking I/O, make it `def` so FastAPI runs it in "
        "a threadpool; if it genuinely awaits, add it to ALLOWED_ASYNC."
    )


@pytest.mark.parametrize("path", _route_files(), ids=lambda p: p.name)
def test_allowed_async_handlers_actually_await(path):
    """An allow-listed handler that no longer awaits anything should become `def`."""
    for fn in _async_handlers(path):
        if fn.name not in ALLOWED_ASYNC or fn.name == "get_public_config":
            continue
        has_await = any(isinstance(n, ast.Await) for n in ast.walk(fn))
        assert has_await, (
            f"{path.name}:{fn.name} is allow-listed as async but awaits nothing. "
            "Convert it to `def`."
        )


def test_blocking_work_is_offloaded_in_async_handlers():
    """The two genuinely-async handlers must hand their blocking half to a thread."""
    for name, module in [
        ("create_listing", "listings.py"),
        ("razorpay_webhook", "webhooks.py"),
    ]:
        source = (ROUTES_DIR / module).read_text(encoding="utf-8")
        assert "run_in_threadpool" in source, (
            f"{module} contains async handler {name} but never calls "
            "run_in_threadpool — its blocking work is still on the event loop."
        )


def test_upload_is_size_limited():
    """Unbounded uploads let a few large files pin CPU inside OpenCV."""
    from app.routes.listings import MAX_QR_UPLOAD_BYTES

    assert 0 < MAX_QR_UPLOAD_BYTES <= 10 * 1024 * 1024
