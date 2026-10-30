#!/usr/bin/env python3
"""Back office: tenant and member operations, database and Cognito together (docs/tenancy.md).

Does what the app's /tenants screen does, from the Mac, for the back-office agent and for repairs.
Run it from the MAIN checkout (it needs the live .env), never from a worktree:

    poetry run python sync/backoffice.py list
    poetry run python sync/backoffice.py tenant create SLUG NAME OWNER_EMAIL
    poetry run python sync/backoffice.py tenant suspend|activate SLUG
    poetry run python sync/backoffice.py member add SLUG EMAIL [--role owner|admin|member]
    poetry run python sync/backoffice.py member remove SLUG EMAIL
    poetry run python sync/backoffice.py access SLUG EMAIL        re-run Cognito provisioning only
    poetry run python sync/backoffice.py audit                     read-only: database vs Cognito drift

Each change writes Postgres first, then provisions Cognito from what Postgres says
(`activities.sync_tenant_access`: a new member is invited by email, a removed one loses the
group, an account with no access left is disabled). Nothing here deletes an account.
"""
import asyncio
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(REPO), str(REPO / "db"), str(REPO / "sync")]

import activities  # noqa: E402
import ledger  # noqa: E402
import tenants as db_tenants  # noqa: E402
from finance.tenancy import PLATFORM_ADMIN_EMAILS  # noqa: E402


def provision(conn, slug, email):
    """Cognito follows the database for `email` in tenant `slug`; prints the steps that ran."""
    tid = str(db_tenants.tenant_id(conn, slug))
    try:
        print(f"  {email}: {asyncio.run(activities.sync_tenant_access(tid, email))}")
    except Exception as e:  # noqa: BLE001 - report it and keep going; the database change stands
        print(f"  {email}: PROVISIONING FAILED: {getattr(e, 'message', e)}", file=sys.stderr)
        return False
    return True


def members_of(conn, slug):
    return [e for (e,) in conn.execute(
        "SELECT u.email FROM memberships m JOIN users u ON u.id = m.user_id WHERE m.tenant_id = %s ORDER BY u.email",
        (db_tenants.tenant_id(conn, slug),))]


def audit(conn):
    """Report where Cognito disagrees with Postgres. Read-only."""
    pool = subprocess.run(["terraform", "output", "-raw", "user_pool_id"], cwd=REPO / "infra",
                          capture_output=True, text=True, check=True).stdout.strip()

    def aws(*a):
        return json.loads(subprocess.run(["aws", "cognito-idp", *a, "--output", "json"], capture_output=True,
                                         text=True, check=True).stdout)
    cognito = {u["Username"].lower(): u["Enabled"] for u in aws("list-users", "--user-pool-id", pool)["Users"]}
    wanted = {}
    for tid, email, status in conn.execute(
            "SELECT m.tenant_id, u.email, t.status FROM memberships m JOIN users u ON u.id = m.user_id "
            "JOIN tenants t ON t.id = m.tenant_id"):
        wanted.setdefault(email, []).append((str(tid), status))
    problems = 0
    for email, rows in sorted(wanted.items()):
        if email not in cognito:
            print(f"MISSING  {email}: member but no Cognito account"); problems += 1; continue
        groups = {g["GroupName"] for g in aws("admin-list-groups-for-user", "--user-pool-id", pool, "--username", email)["Groups"]}
        for tid, status in rows:
            want = status == "active"
            if want != (f"tenant-{tid}" in groups):
                print(f"GROUP    {email}: tenant-{tid} {'missing' if want else 'should be removed (suspended)'}"); problems += 1
        if not any(s == "active" for _, s in rows) and cognito[email]:
            print(f"ENABLED  {email}: no active tenant left but the account is enabled"); problems += 1
    for email, enabled in sorted(cognito.items()):
        if email not in wanted and email not in PLATFORM_ADMIN_EMAILS and enabled:
            print(f"ORPHAN   {email}: enabled Cognito account with no membership"); problems += 1
    print("in sync" if not problems else f"{problems} difference(s); `access SLUG EMAIL` repairs one")
    return problems == 0


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    cmd, *a = argv
    conn = ledger.connect_admin()   # privileged: bypasses RLS, touches only the registry tables
    with conn:
        if cmd == "list":
            for slug, name, status in conn.execute("SELECT slug, name, status FROM tenants ORDER BY created_at").fetchall():
                print(f"{slug}\t{name}\t{status}\t" + ", ".join(members_of(conn, slug)))
            return 0
        if cmd == "audit":
            return 0 if audit(conn) else 1
        if cmd == "tenant" and a[:1] == ["create"] and len(a) == 4:
            _, slug, name, owner = a
            db_tenants.create(conn, slug, name)
            db_tenants.add_member(conn, owner, slug, "owner")
            conn.commit()
            print(f"created tenant {slug}")
            return 0 if provision(conn, slug, owner.strip().lower()) else 1
        if cmd == "tenant" and a[:1] in (["suspend"], ["activate"]) and len(a) == 2:
            slug = a[1]
            conn.execute("UPDATE tenants SET status = %s, updated_at = now() WHERE slug = %s",
                         ("suspended" if a[0] == "suspend" else "active", slug))
            conn.commit()
            print(f"{a[0]}d tenant {slug}")
            return 0 if all([provision(conn, slug, e) for e in members_of(conn, slug)]) else 1
        if cmd == "member" and a[:1] == ["add"] and len(a) >= 3:
            role = a[a.index("--role") + 1] if "--role" in a else "member"
            db_tenants.add_member(conn, a[2], a[1], role)
            conn.commit()
            print(f"added {a[2]} to {a[1]} as {role}")
            return 0 if provision(conn, a[1], a[2].strip().lower()) else 1
        if cmd == "member" and a[:1] == ["remove"] and len(a) == 3:
            tid = db_tenants.tenant_id(conn, a[1])
            conn.execute("DELETE FROM memberships WHERE tenant_id = %s AND user_id = (SELECT id FROM users WHERE email = %s)",
                         (tid, a[2].strip().lower()))
            conn.commit()
            print(f"removed {a[2]} from {a[1]}")
            return 0 if provision(conn, a[1], a[2].strip().lower()) else 1
        if cmd == "access" and len(a) == 2:
            return 0 if provision(conn, a[0], a[1].strip().lower()) else 1
    raise SystemExit(__doc__)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
