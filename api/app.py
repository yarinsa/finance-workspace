"""The ledger API: a small, fixed set of endpoints over the human layer of the transactions DB.

Run with `uvicorn --factory api.app:create_app`. The contract is docs/ledger-api.md.
The API connects as the least-privileged Postgres role `finance_api` and never migrates.
"""
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
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "db"))   # the shared override code
import overrides  # noqa: E402
import goal_store as goals  # noqa: E402
import tags  # noqa: E402

from .auth import TokenVerifier, check_csrf, check_origin, current_user  # noqa: E402
from .config import Settings  # noqa: E402
from .errors import ApiError  # noqa: E402
from .inputs import GoalEdit, Patch, TagEdit, TagSet  # noqa: E402
from .gql import endpoint  # noqa: E402
from .rebuild import Rebuilder  # noqa: E402

log = logging.getLogger("finance_api")

MAX_BODY = 8 * 1024
MAX_GRAPHQL_BODY = 16 * 1024   # a GraphQL document with variables
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
def db(request: Request):
    """A pooled connection; committed on a clean exit, rolled back on error."""
    pool = request.app.state.pool
    try:
        with pool.connection() as conn:
            yield conn
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


def create_app(settings=None, pool=None, rebuilder=None, verifier=None):
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
        if own_pool:
            pool.close()

    app = FastAPI(title="finance-api", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan, dependencies=[Depends(check_origin)])
    app.state.settings = settings
    app.state.pool = pool
    app.state.rebuilder = rebuilder or Rebuilder(settings.temporal_address)
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
        request.app.state.rebuilder.signal_edited()

    def found(row):
        if row is None:
            raise ApiError(404, "not_found", "no such transaction")
        return row

    @app.get("/api/health")
    def health(request: Request):
        try:
            with db(request) as conn:
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
                return endpoint.run(body, conn, user, allow_introspection=bool(settings.dev_user))
        status, out = await run_in_threadpool(work)
        return JSONResponse(jsonable_encoder(out), status_code=status)

    @app.get("/api/rebuild")
    def rebuild_status(request: Request, user=Depends(current_user)):
        return request.app.state.rebuilder.status()

    return app


def _first_error(errors):
    e = errors[0]
    where = ".".join(str(p) for p in e["loc"] if p not in ("body", "query"))
    return f"{where}: {e['msg']}" if where else e["msg"]
