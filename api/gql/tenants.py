"""Tenant registry for platform admins: tenants, their members and status (docs/tenancy.md).

Works on the global tables `tenants`, `users` and `memberships` through the request's
connection. Authorization is `finance.tenancy.is_platform_admin(email)`, checked by the caller
before anything here runs."""
import uuid

from finance import tenancy
from finance.tenancy import DEFAULT_TENANT_ID


def _members(conn, tenant_id):
    return [{"email": e, "role": r} for e, r in conn.execute(
        "SELECT u.email, m.role FROM memberships m JOIN users u ON u.id = m.user_id "
        "WHERE m.tenant_id = %s ORDER BY m.created_at, u.email", (tenant_id,))]


def _row(conn, row):
    tid, slug, name, status, created_at = row
    return {"id": tid, "slug": slug, "name": name, "status": status, "created_at": created_at,
            "members": _members(conn, tid)}


def get(conn, tenant_id):
    try:
        tenant_id = uuid.UUID(str(tenant_id))
    except ValueError:
        return None
    row = conn.execute("SELECT id, slug, name, status, created_at FROM tenants WHERE id = %s", (tenant_id,)).fetchone()
    return _row(conn, row) if row else None


def all_tenants(conn):
    rows = conn.execute("SELECT id, slug, name, status, created_at FROM tenants ORDER BY created_at, slug").fetchall()
    return [_row(conn, r) for r in rows]


def create(conn, slug, name):
    """A new tenant with its horizon buckets (read from the master tenant, seeded by `seed_horizons`)."""
    if conn.execute("SELECT 1 FROM tenants WHERE slug = %s", (slug,)).fetchone():
        raise ValueError("a tenant with this slug exists")
    tid = conn.execute("INSERT INTO tenants (name, slug) VALUES (%s, %s) RETURNING id", (name, slug)).fetchone()[0]
    tenancy.bind(conn, DEFAULT_TENANT_ID, local=False)   # RLS: read the template from the master tenant
    horizons = conn.execute("SELECT key, name, target_pct, position FROM horizons").fetchall()
    return tid, horizons


def seed_horizons(conn, tenant_id, horizons):
    """Insert a new tenant's horizons while the connection is bound to that tenant (RLS)."""
    tenancy.bind(conn, tenant_id, local=False)
    for key, name, pct, pos in horizons:
        conn.execute("INSERT INTO horizons (key, name, target_pct, position) VALUES (%s, %s, %s, %s)",
                     (key, name, pct, pos))


def set_member(conn, tenant_id, email, role):
    email = email.strip().lower()
    conn.execute("INSERT INTO users (email) VALUES (%s) ON CONFLICT DO NOTHING", (email,))
    uid = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()[0]
    if role != "owner":
        _keep_an_owner(conn, tenant_id, except_user=uid)
    conn.execute("INSERT INTO memberships (tenant_id, user_id, role) VALUES (%s, %s, %s) "
                 "ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role", (tenant_id, uid, role))


def remove_member(conn, tenant_id, email):
    uid = conn.execute("SELECT id FROM users WHERE email = %s", (email.strip().lower(),)).fetchone()
    if not uid:
        return
    _keep_an_owner(conn, tenant_id, except_user=uid[0])
    conn.execute("DELETE FROM memberships WHERE tenant_id = %s AND user_id = %s", (tenant_id, uid[0]))


def _keep_an_owner(conn, tenant_id, except_user):
    """A tenant never loses its last owner (nobody could manage it afterwards)."""
    others = conn.execute("SELECT count(*) FROM memberships WHERE tenant_id = %s AND role = 'owner' "
                          "AND user_id <> %s", (tenant_id, except_user)).fetchone()[0]
    is_owner = conn.execute("SELECT 1 FROM memberships WHERE tenant_id = %s AND user_id = %s AND role = 'owner'",
                            (tenant_id, except_user)).fetchone()
    if is_owner and not others:
        raise ValueError("a tenant needs at least one owner")


def set_status(conn, tenant_id, status):
    if tenant_id == DEFAULT_TENANT_ID and status != "active":
        raise ValueError("the master tenant cannot be suspended")
    conn.execute("UPDATE tenants SET status = %s, updated_at = now() WHERE id = %s", (status, tenant_id))
