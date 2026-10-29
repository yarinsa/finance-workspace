"""The ledger API: a small, fixed set of endpoints over the human layer of the transactions DB.

Run with `uvicorn --factory api.app:create_app`. The contract is docs/ledger-api.md.
The API connects as the least-privileged Postgres role `finance_api` and never migrates.
"""
import asyncio
import logging
import re
import sys
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "db"))   # the shared override code
import overrides  # noqa: E402
import goal_store as goals  # noqa: E402
import tags  # noqa: E402

from .auth import TokenVerifier, check_csrf, check_origin, current_user  # noqa: E402
from .config import Settings  # noqa: E402
from finance import tenancy  # noqa: E402
from finance.tenancy import TenantContextMissing  # noqa: E402

from .errors import ApiError  # noqa: E402

from .inputs import GoalEdit, Patch, PushSubscribe, PushUnsubscribe, TagEdit, TagSet  # noqa: E402
from .gql import endpoint  # noqa: E402
from .rebuild import OTP_SOURCES, Rebuilder  # noqa: E402
from .sse import END, Event, SyncBroadcaster, sse  # noqa: E402

log = logging.getLogger("finance_api")

MAX_BODY = 8 * 1024
MAX_GRAPHQL_BODY = 16 * 1024   # a GraphQL document with variables
SSE_RETRY_MS = 5000
SSE_PING_SECONDS = 15      # CloudFront's origin read timeout is 30 s
SSE_LIFETIME_SECONDS = 600  # then the client reconnects with a fresh snapshot
SSE_MAX_STREAMS = 20
SSE_TICK_SECONDS = 1       # how often a quiet stream checks for a disconnected client
AMOUNT = re.compile(r"^\d{1,10}(\.\d{1,2})?$")


def parse_body(model, raw):
    try:
        return model.model_validate_json(raw)
    except ValidationError as e:
        raise ApiError(422, "invalid", _first_error(e.errors())) from None


def parse_key(day, abs_amount):
    """(date, abs_amount) from the URL, in the form the database stores it."""
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise ApiError(400, "bad_key", "date must be an ISO date, YYYY-MM-DD") from None
    if not AMOUNT.match(abs_amount):
        raise ApiError(400, "bad_key", "abs_amount must be a positive amount with at most 2 decimals")
    return d, Decimal(abs_amount).quantize(Decimal("0.01"))


@contextmanager
def db(request: Request, scoped=True):
    """A pooled connection; committed on a clean exit, rolled back on error.

    Scoped to the request's tenant (`tenancy.bind`, cleared again on the way out, so a pooled
    connection never carries it to the next request). A request with no resolved tenant
    raises instead of running unscoped; only `scoped=False` (health) skips the binding."""
    pool = request.app.state.pool
    ctx = getattr(request.state, "tenant", None)
    if scoped and ctx is None:
        raise TenantContextMissing("database access with no tenant resolved for this request")
    try:
        with pool.connection() as conn:
            if scoped:
                tenancy.bind(conn, ctx.tenant_id, local=False)
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
            finally:
                if scoped and not conn.closed:   # back to the pool with no tenant on it
                    try:
                        tenancy.unbind(conn)
                        conn.commit()
                    except Exception:
                        log.warning("could not clear the tenant; discarding the connection")
                        conn.close()
    except ApiError:
        raise
    except Exception as e:
        if type(e).__module__.startswith("psycopg"):
            log.exception("database error")
            raise ApiError(503, "db_unavailable", "the ledger database is not reachable") from None
        raise


async def read_json_body(request: Request, limit=MAX_BODY):
    """The request body, refusing to buffer more than `limit` bytes."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise ApiError(413, "too_large", f"body must be at most {limit} bytes")
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise ApiError(413, "too_large", f"body must be at most {limit} bytes")
    return body


class OtpBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{4,8}$")


def create_app(settings=None, pool=None, rebuilder=None, verifier=None, broadcaster=None):
    """Build the app. Tests pass fakes; production passes nothing and reads the environment."""
    settings = settings or Settings.from_env()
    own_pool = pool is None
    if own_pool:
        from psycopg_pool import ConnectionPool
        if not settings.database_url:
            raise RuntimeError("API_DATABASE_URL is not set")
        pool = ConnectionPool(settings.database_url, min_size=1, max_size=5, timeout=5, open=False)

    @asynccontextmanager
    async def lifespan(app):
        if own_pool:
            pool.open()
        yield
        await app.state.broadcaster.stop()
        if own_pool:
            pool.close()

    app = FastAPI(title="finance-api", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan, dependencies=[Depends(check_origin)])
    app.state.settings = settings
    app.state.pool = pool
    app.state.rebuilder = rebuilder or Rebuilder(settings.temporal_address)
    app.state.broadcaster = broadcaster or SyncBroadcaster(settings.database_url)
    app.state.sse_streams = 0
    app.state.sse_ping = SSE_PING_SECONDS          # tests shorten these
    app.state.sse_lifetime = SSE_LIFETIME_SECONDS
    app.state.sse_max_streams = SSE_MAX_STREAMS
    app.state.sse_tick = SSE_TICK_SECONDS
    app.state.verifier = verifier or (None if settings.dev_user else TokenVerifier(settings))

    @app.exception_handler(ApiError)
    async def api_error(request, e):
        return JSONResponse({"error": e.code, "message": e.message}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def invalid(request, e):
        return JSONResponse({"error": "invalid", "message": _first_error(e.errors())}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, e):
        code = {404: "not_found", 405: "method_not_allowed"}.get(e.status_code, "error")
        return JSONResponse({"error": code, "message": str(e.detail)}, status_code=e.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request, e):
        log.exception("unhandled error")
        return JSONResponse({"error": "internal", "message": "internal error"}, status_code=500)

    def signal_rebuild(request):
        # The edit is already committed; a Temporal problem must not turn it into an error.
        request.app.state.rebuilder.signal_edited(request.state.tenant.tenant_id)

    def found(row):
        if row is None:
            raise ApiError(404, "not_found", "no such transaction")
        return row

    @app.get("/api/health")
    def health(request: Request):
        try:
            with db(request, scoped=False) as conn:
                conn.execute("SELECT 1")
            db_ok = True
        except ApiError:
            db_ok = False
        out = {"ok": db_ok, "db": db_ok, "temporal": bool(request.app.state.rebuilder.ping())}
        if settings.dev_user:
            out["dev"] = True
        return out

    @app.get("/api/transactions")
    def list_transactions(request: Request, user=Depends(current_user),
                          date_from: date | None = Query(None, alias="from"),
                          date_to: date | None = Query(None, alias="to"),
                          excluded: Literal["include", "only"] | None = None):
        with db(request) as conn:
            return {"transactions": overrides.list_rows(conn, date_from, date_to, excluded or "hide")}

    @app.get("/api/transactions/{day}/{abs_amount}")
    def get_transaction(day: str, abs_amount: str, request: Request, user=Depends(current_user)):
        k = parse_key(day, abs_amount)
        with db(request) as conn:
            return found(overrides.get_row(conn, k))

    @app.patch("/api/transactions/{day}/{abs_amount}", dependencies=[Depends(check_csrf)])
    async def patch_transaction(day: str, abs_amount: str, request: Request, user=Depends(current_user)):
        k = parse_key(day, abs_amount)
        raw = await read_json_body(request)
        try:
            body = Patch.model_validate_json(raw)
        except ValidationError as e:
            raise ApiError(422, "invalid", _first_error(e.errors())) from None
        if not body.model_fields_set:
            raise ApiError(422, "invalid", "send at least one of category, note, excluded, horizon, goal_id")

        def work():
            with db(request) as conn:
                found(overrides.get_row(conn, k))
                try:
                    return overrides.patch(conn, k, {f: getattr(body, f) for f in body.model_fields_set}, user)
                except ValueError as e:
                    raise ApiError(422, "invalid", str(e)) from None
        row = await run_in_threadpool(work)
        await run_in_threadpool(signal_rebuild, request)
        return row

    @app.delete("/api/transactions/{day}/{abs_amount}/override", dependencies=[Depends(check_csrf)])
    def reset_override(day: str, abs_amount: str, request: Request, user=Depends(current_user)):
        k = parse_key(day, abs_amount)
        with db(request) as conn:
            found(overrides.get_row(conn, k))
            row = overrides.reset(conn, k, user)
        signal_rebuild(request)
        return row

    @app.get("/api/categories")
    def categories(request: Request, user=Depends(current_user)):
        with db(request) as conn:
            return {"categories": overrides.categories(conn)}

    @app.put("/api/transactions/{day}/{abs_amount}/tags", dependencies=[Depends(check_csrf)])
    async def put_tags(day: str, abs_amount: str, request: Request, user=Depends(current_user)):
        k = parse_key(day, abs_amount)
        body = parse_body(TagSet, await read_json_body(request))

        def work():
            with db(request) as conn:
                found(overrides.get_row(conn, k))
                tags.set_tags(conn, k, body.tags, user)
                return overrides.get_row(conn, k)
        row = await run_in_threadpool(work)
        await run_in_threadpool(signal_rebuild, request)
        return row

    @app.get("/api/tags")
    def list_tags(request: Request, user=Depends(current_user)):
        with db(request) as conn:
            return {"tags": tags.all_tags(conn)}

    @app.patch("/api/tags/{tag_id}", dependencies=[Depends(check_csrf)])
    async def edit_tag(tag_id: int, request: Request, user=Depends(current_user)):
        body = parse_body(TagEdit, await read_json_body(request))
        if not body.model_fields_set:
            raise ApiError(422, "invalid", "send name and/or color")

        def work():
            with db(request) as conn:
                if body.name and tags.tag_name_taken(conn, body.name, tag_id):
                    raise ApiError(409, "conflict", "a tag with that name already exists")
                changes = {f: getattr(body, f) for f in body.model_fields_set if f != "name" or body.name}
                return tags.update_tag(conn, tag_id, **changes)
        tag = await run_in_threadpool(work)
        if tag is None:
            raise ApiError(404, "not_found", "no such tag")
        await run_in_threadpool(signal_rebuild, request)
        return tag

    @app.delete("/api/tags/{tag_id}", dependencies=[Depends(check_csrf)])
    def remove_tag(tag_id: int, request: Request, user=Depends(current_user)):
        with db(request) as conn:
            if not tags.delete_tag(conn, tag_id):
                raise ApiError(404, "not_found", "no such tag")
        signal_rebuild(request)
        return {"deleted": tag_id}

    @app.get("/api/tags/orphaned")
    def orphaned_tags(request: Request, user=Depends(current_user)):
        with db(request) as conn:
            return {"links": tags.orphaned(conn)}

    @app.get("/api/horizons")
    def list_horizons(request: Request, user=Depends(current_user)):
        with db(request) as conn:
            return {"horizons": goals.horizons(conn)}

    @app.get("/api/goals")
    def list_goals(request: Request, user=Depends(current_user)):
        with db(request) as conn:
            return {"goals": goals.all_goals(conn)}

    @app.post("/api/goals", dependencies=[Depends(check_csrf)])
    async def create_goal(request: Request, user=Depends(current_user)):
        body = parse_body(GoalEdit, await read_json_body(request))
        if body.description is None or body.amount is None:
            raise ApiError(422, "invalid", "description and amount are required")
        fields = {f: getattr(body, f) for f in body.model_fields_set if f not in ("description", "amount")}

        def work():
            with db(request) as conn:
                return goals.create_goal(conn, body.description.strip(), body.amount, **fields)
        goal = await run_in_threadpool(work)
        await run_in_threadpool(signal_rebuild, request)
        return goal

    @app.patch("/api/goals/{goal_id}", dependencies=[Depends(check_csrf)])
    async def edit_goal(goal_id: int, request: Request, user=Depends(current_user)):
        body = parse_body(GoalEdit, await read_json_body(request))
        if not body.model_fields_set:
            raise ApiError(422, "invalid", "send at least one goal field")
        if any(f in body.model_fields_set and getattr(body, f) is None for f in ("description", "amount")):
            raise ApiError(422, "invalid", "description and amount cannot be cleared")

        def work():
            with db(request) as conn:
                return goals.update_goal(conn, goal_id, **{f: getattr(body, f) for f in body.model_fields_set})
        goal = await run_in_threadpool(work)
        if goal is None:
            raise ApiError(404, "not_found", "no such goal")
        await run_in_threadpool(signal_rebuild, request)
        return goal

    @app.delete("/api/goals/{goal_id}", dependencies=[Depends(check_csrf)])
    def remove_goal(goal_id: int, request: Request, user=Depends(current_user)):
        with db(request) as conn:
            if not goals.delete_goal(conn, goal_id):
                raise ApiError(404, "not_found", "no such goal")
        signal_rebuild(request)
        return {"deleted": goal_id}

    @app.get("/api/overrides/orphaned")
    def orphaned(request: Request, user=Depends(current_user)):
        with db(request) as conn:
            return {"overrides": overrides.orphaned(conn)}

    @app.get("/api/audit")
    def audit(request: Request, user=Depends(current_user), limit: int = Query(50, ge=1, le=500)):
        with db(request) as conn:
            return {"entries": overrides.audit_log(conn, limit)}

    @app.post("/api/graphql", dependencies=[Depends(check_csrf)])
    async def graphql(request: Request, user=Depends(current_user)):
        body = await read_json_body(request, MAX_GRAPHQL_BODY)

        def work():
            with db(request) as conn:
                return endpoint.run(body, conn, user, allow_introspection=bool(settings.dev_user),
                                    rebuilder=request.app.state.rebuilder,
                                    tenant_id=request.state.tenant.tenant_id)
        status, out, writes = await run_in_threadpool(work)   # committed when work() returns
        if writes:
            await run_in_threadpool(signal_rebuild, request)
        return JSONResponse(jsonable_encoder(out), status_code=status)

    @app.post("/api/sync/{source}/login", dependencies=[Depends(check_csrf)], status_code=202)
    def start_login(source: str, request: Request, user=Depends(current_user)):
        """Start a one-source sync that logs in with a code typed here (Harel). Scheduled runs never do."""
        if source not in OTP_SOURCES:
            raise ApiError(404, "not_found", "no app login for this source")
        if not request.app.state.rebuilder.start_login(source):
            raise ApiError(503, "unavailable", "the sync worker is not reachable")
        log.info("login started for %s by %s", source, user)
        return {"ok": True}

    @app.post("/api/sync/{source}/otp", dependencies=[Depends(check_csrf)], status_code=202)
    def submit_otp(source: str, body: OtpBody, request: Request, user=Depends(current_user)):
        """Hand the SMS code to the waiting login. The code is never stored or logged here."""
        if source not in OTP_SOURCES:
            raise ApiError(404, "not_found", "no app login for this source")
        if not request.app.state.rebuilder.submit_otp(source, body.code):
            raise ApiError(409, "not_waiting", "no login is waiting for a code")
        return {"ok": True}

    @app.get("/api/sync/events")
    async def sync_events(request: Request, user=Depends(current_user)):
        """Live sync status: a `snapshot` event, then a `source` event per change, pings in between."""
        st = request.app.state
        tenant = request.state.tenant
        if st.sse_streams >= st.sse_max_streams:
            raise ApiError(503, "too_many_streams", "too many open status streams")
        st.sse_streams += 1
        released = False

        def release(sub=None):
            nonlocal released
            if released:   # the stream's finally and the response's background task both call this
                return
            released = True
            st.sse_streams -= 1
            if sub is not None:
                st.broadcaster.unsubscribe(sub)

        sub = None
        try:
            sub = st.broadcaster.subscribe()   # before the snapshot, so no change falls between them
            snap = await st.broadcaster.snapshot()
        except Exception:
            release(sub)
            log.exception("sync status stream could not start")
            raise ApiError(503, "db_unavailable", "the sync status is not reachable") from None

        async def stream():
            loop = asyncio.get_running_loop()
            try:
                yield f"retry: {SSE_RETRY_MS}\n\n"
                yield sse("snapshot", snap)
                end = loop.time() + st.sse_lifetime
                next_ping = loop.time() + st.sse_ping
                while True:
                    now = loop.time()
                    if now >= end or await request.is_disconnected():
                        return
                    try:
                        item = await asyncio.wait_for(
                            sub.get(), timeout=max(0.01, min(st.sse_tick, next_ping - now, end - now)))
                    except asyncio.TimeoutError:
                        if loop.time() >= next_ping:
                            next_ping = loop.time() + st.sse_ping
                            yield ": ping\n\n"
                        continue
                    if item is END:
                        return
                    if isinstance(item, Event) and item.tenant and item.tenant != str(tenant.tenant_id):
                        continue   # another tenant's inbox changed
                    yield sse(item.name, item.data) if isinstance(item, Event) else sse("source", item)
            finally:
                release(sub)

        return StreamingResponse(
            stream(), media_type="text/event-stream", background=BackgroundTask(release, sub),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/push/key")
    def push_key(user=Depends(current_user)):
        """The VAPID public key the browser subscribes with. 404 until push is configured."""
        if not settings.push_public_key:
            raise ApiError(404, "not_configured", "push notifications are not configured")
        return {"key": settings.push_public_key}

    @app.post("/api/push/subscribe", dependencies=[Depends(check_csrf)])
    async def push_subscribe(request: Request, user=Depends(current_user)):
        """Store (or refresh) this browser's push subscription, keyed by endpoint."""
        body = parse_body(PushSubscribe, await read_json_body(request))
        agent = (request.headers.get("user-agent") or "")[:300] or None

        def work():
            with db(request) as conn:
                conn.execute(
                    "INSERT INTO push_subscriptions (endpoint, p256dh, auth, email, user_agent) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (tenant_id, endpoint) DO UPDATE "
                    "SET p256dh = EXCLUDED.p256dh, auth = EXCLUDED.auth, "
                    "email = EXCLUDED.email, user_agent = EXCLUDED.user_agent",
                    (body.endpoint, body.keys.p256dh, body.keys.auth, user, agent))
        await run_in_threadpool(work)
        return {"ok": True}

    @app.post("/api/push/unsubscribe", dependencies=[Depends(check_csrf)])
    async def push_unsubscribe(request: Request, user=Depends(current_user)):
        """Forget this browser's subscription (idempotent)."""
        body = parse_body(PushUnsubscribe, await read_json_body(request))

        def work():
            with db(request) as conn:
                return conn.execute("DELETE FROM push_subscriptions WHERE endpoint = %s AND email = %s",
                                    (body.endpoint, user)).rowcount
        return {"ok": True, "removed": await run_in_threadpool(work)}

    @app.get("/api/rebuild")
    def rebuild_status(request: Request, user=Depends(current_user)):
        return request.app.state.rebuilder.status(request.state.tenant.tenant_id)

    return app


def _first_error(errors):
    e = errors[0]
    where = ".".join(str(p) for p in e["loc"] if p not in ("body", "query"))
    return f"{where}: {e['msg']}" if where else e["msg"]
