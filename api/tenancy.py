"""Which tenant a request acts in (docs/tenancy.md).

Resolution: the `X-Tenant-Id` header names the tenant; with no header, a user who belongs to
exactly one tenant gets that one. The user must hold a membership (403 otherwise) in an
active tenant. The result is stored once, in `request.state.tenant`, and every database
access binds it with `SET LOCAL app.tenant_id`; nothing downstream reads a tenant from client
input again. Any `tenant_id` in a JSON body or GraphQL input is never used: Row-Level
Security and the column default decide the tenant of every row."""
import uuid

from fastapi import Request

from finance.tenancy import TenantContext

from .errors import ApiError

HEADER = "x-tenant-id"


def memberships(pool, email):
    """[(user_id, tenant_id, role, status)] for this email (users/memberships/tenants are global)."""
    with pool.connection() as conn:
        return conn.execute(
            "SELECT u.id, m.tenant_id, m.role, t.status FROM users u "
            "JOIN memberships m ON m.user_id = u.id JOIN tenants t ON t.id = m.tenant_id "
            "WHERE u.email = %s ORDER BY m.created_at, m.tenant_id", (email,)).fetchall()


def resolve(pool, email, header):
    """The TenantContext for `email` asking for `header` (None/empty = not specified)."""
    rows = memberships(pool, email)
    if not rows:
        raise ApiError(403, "no_tenant", "this account is not a member of any tenant")
    if header:
        try:
            wanted = uuid.UUID(header.strip())
        except ValueError:
            raise ApiError(400, "bad_tenant", "X-Tenant-Id must be a uuid") from None
        row = next((r for r in rows if r[1] == wanted), None)
        if row is None:   # same answer whether the tenant exists or not
            raise ApiError(403, "forbidden", "not a member of this tenant")
    elif len(rows) == 1:
        row = rows[0]
    else:
        raise ApiError(400, "tenant_required", "this account belongs to several tenants: send X-Tenant-Id")
    user_id, tenant_id, role, status = row
    if status != "active":
        raise ApiError(403, "tenant_suspended", "this tenant is suspended")
    return TenantContext(user_id=user_id, tenant_id=tenant_id, role=role)


def resolve_request(request: Request, email):
    """Resolve and remember the tenant of this request."""
    ctx = resolve(request.app.state.pool, email, request.headers.get(HEADER))
    request.state.tenant = ctx
    return ctx
