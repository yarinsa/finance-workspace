#!/usr/bin/env python3
"""Tenants and memberships (privileged: runs as the owner role, the API cannot).

    tenants.py list
    tenants.py create SLUG NAME            new tenant with the three horizon buckets
    tenants.py member add EMAIL [TENANT_SLUG] [--role owner|admin|member]   (default tenant, owner)
    tenants.py member remove EMAIL [TENANT_SLUG]
    tenants.py suspend|activate TENANT_SLUG
    tenants.py memberships                 "tenant_id<TAB>email" per membership (infra/tenant-groups.sh sync)

Users are global; the API reads memberships to decide which tenants an email may act in
(docs/tenancy.md). A tenant's categories are seeded by its first ledger import.
"""
import sys

import ledger
from finance.tenancy import DEFAULT_TENANT_ID, ROLES


def tenant_id(conn, slug):
    row = conn.execute("SELECT id FROM tenants WHERE slug = %s", (slug,)).fetchone()
    if not row:
        raise SystemExit(f"no tenant {slug!r}")
    return row[0]


def create(conn, slug, name):
    tid = conn.execute("INSERT INTO tenants (name, slug) VALUES (%s, %s) RETURNING id", (name, slug)).fetchone()[0]
    conn.execute(
        "INSERT INTO horizons (tenant_id, key, name, target_pct, position) "
        "SELECT %s, key, name, target_pct, position FROM horizons WHERE tenant_id = %s",
        (tid, DEFAULT_TENANT_ID))
    return tid


def add_member(conn, email, slug=None, role="owner"):
    if role not in ROLES:
        raise SystemExit(f"role must be one of {ROLES}")
    tid = tenant_id(conn, slug) if slug else DEFAULT_TENANT_ID
    email = email.strip().lower()
    conn.execute("INSERT INTO users (email) VALUES (%s) ON CONFLICT DO NOTHING", (email,))
    uid = conn.execute("SELECT id FROM users WHERE email = %s", (email,)).fetchone()[0]
    conn.execute("INSERT INTO memberships (tenant_id, user_id, role) VALUES (%s, %s, %s) "
                 "ON CONFLICT (tenant_id, user_id) DO UPDATE SET role = EXCLUDED.role", (tid, uid, role))


def main(argv):
    conn = ledger.connect_admin()   # privileged on purpose: bypasses RLS, touches only global tables
    with conn:
        cmd, *a = argv or ["list"]
        if cmd == "list":
            for slug, name, status, n in conn.execute(
                    "SELECT t.slug, t.name, t.status, count(m.id) FROM tenants t "
                    "LEFT JOIN memberships m ON m.tenant_id = t.id GROUP BY t.id ORDER BY t.created_at"):
                print(f"{slug}\t{name}\t{status}\t{n} members")
        elif cmd == "memberships":
            for tid, email in conn.execute("SELECT m.tenant_id, u.email FROM memberships m "
                                           "JOIN users u ON u.id = m.user_id ORDER BY m.created_at"):
                print(f"{tid}\t{email}")
        elif cmd == "create" and len(a) == 2:
            print(create(conn, *a))
        elif cmd == "member" and a[:1] == ["add"] and len(a) >= 2:
            rest = [x for x in a[2:] if not x.startswith("--role")]
            role = a[a.index("--role") + 1] if "--role" in a else "owner"
            rest = [x for x in rest if x != role]
            add_member(conn, a[1], rest[0] if rest else None, role)
        elif cmd == "member" and a[:1] == ["remove"] and len(a) >= 2:
            tid = tenant_id(conn, a[2]) if len(a) > 2 else DEFAULT_TENANT_ID
            conn.execute("DELETE FROM memberships WHERE tenant_id = %s AND user_id = "
                         "(SELECT id FROM users WHERE email = %s)", (tid, a[1].strip().lower()))
        elif cmd in ("suspend", "activate") and len(a) == 1:
            conn.execute("UPDATE tenants SET status = %s, updated_at = now() WHERE slug = %s",
                         ("suspended" if cmd == "suspend" else "active", a[0]))
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
