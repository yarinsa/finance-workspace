"""Set up the local Infisical vault and give each tenant its own project and identity.

    poetry run python -m finance.vault_admin bootstrap EMAIL     # once, on a fresh vault (asks for the password)
    poetry run python -m finance.vault_admin tenant TENANT_ID    # project + read identity + write identity (for the API)
    poetry run python -m finance.vault_admin upgrade TENANT_ID   # add the write identity to a tenant set up earlier

Run on the Mac by the household owner. It creates the structure only: the households type their own
secrets (in the app or the Infisical UI), and nothing here reads or sets a credential value. The write
identity (built-in `member` role: it can also read, see issue #63) lives in ~/.finance-vault-write/ so only that
directory is mounted into the API container. The instance-admin token from
`bootstrap` is kept in ~/.finance-vault/admin.json (0600) and is not read by the worker or the API.
See docs/secrets-vault.md.
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from finance import vault


def _dir(home: Path | None = None) -> Path:
    d = (home or Path.home()) / ".finance-vault"
    d.mkdir(mode=0o700, exist_ok=True)
    return d


def _write_private(path: Path, data: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)


def _call(base: str, method: str, path: str, body: dict | None = None, token: str | None = None) -> dict:
    req = urllib.request.Request(
        base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {path}: HTTP {e.code}") from None   # the body can echo a secret
    except OSError as e:
        raise SystemExit(f"vault unreachable at {base}: {type(e).__name__}") from None


def bootstrap(base: str, email: str, password: str, org: str = "finance", home: Path | None = None) -> None:
    res = _call(base, "POST", "/api/v1/admin/bootstrap", {"email": email, "password": password, "organization": org})
    _write_private(_dir(home) / "admin.json", {
        "token": res["identity"]["credentials"]["token"], "organization_id": res["organization"]["id"]})
    print(f"bootstrapped; admin token kept in {_dir(home) / 'admin.json'}. Sign in at {base} as {email}.")


def _make_identity(base: str, token: str, org: str, project_id: str, name: str, role: str, target: Path) -> None:
    """A Universal Auth identity with `role` on this one project only; its credentials go to `target` (0600)."""
    ident = _call(base, "POST", "/api/v1/identities", {"name": name, "organizationId": org, "role": "no-access"}, token)
    iid = ident.get("identity", ident)["id"]
    _call(base, "POST", f"/api/v1/auth/universal-auth/identities/{iid}",
          {"accessTokenTTL": 300, "accessTokenMaxTTL": 3600, "accessTokenNumUsesLimit": 0}, token)
    cs = _call(base, "POST", f"/api/v1/auth/universal-auth/identities/{iid}/client-secrets",
               {"description": "sync worker" if role == "viewer" else "ledger api"}, token)
    ua = _call(base, "GET", f"/api/v1/auth/universal-auth/identities/{iid}", token=token)
    _call(base, "POST", f"/api/v2/workspace/{project_id}/identity-memberships/{iid}",
          {"roles": [{"role": role, "isTemporary": False}]}, token)
    target.parent.mkdir(mode=0o700, exist_ok=True)
    _write_private(target, {"client_id": ua["identityUniversalAuth"]["clientId"], "client_secret": cs["clientSecret"]})


def _admin(home: Path | None) -> tuple[str, str]:
    admin = json.loads((_dir(home) / "admin.json").read_text())
    return admin["token"], admin["organization_id"]


def create_tenant(base: str, tenant_id: str, home: Path | None = None) -> None:
    token, org = _admin(home)
    slug = vault.project_slug(tenant_id)
    target = vault.identity_path(tenant_id, home)
    if target.exists():
        raise SystemExit(f"{target} already exists: this tenant is set up")
    proj = _call(base, "POST", "/api/v2/workspace",
                 {"projectName": slug, "slug": slug, "type": "secret-manager"}, token)
    project = proj.get("project", proj)
    _make_identity(base, token, org, project["id"], slug, "viewer", target)   # read-only, this project only
    wtarget = vault.write_identity_path(tenant_id, {}, home)
    _make_identity(base, token, org, project["id"], f"{slug}-write", "member", wtarget)
    print(f"tenant {tenant_id}: project + read-only identity created; identity file {target}; "
          f"write identity for the API in {wtarget}. Households enter their secrets in the app "
          f"or in the Infisical UI (project '{slug}', environment prod).")


def upgrade_tenant(base: str, tenant_id: str, home: Path | None = None) -> None:
    """Give a tenant set up before self-service a write identity for the API (the project already exists)."""
    token, org = _admin(home)
    slug = vault.project_slug(tenant_id)
    wtarget = vault.write_identity_path(tenant_id, {}, home)
    if wtarget.exists():
        raise SystemExit(f"{wtarget} already exists: this tenant can already write")
    projects = _call(base, "GET", "/api/v2/workspace", token=token).get("workspaces", [])
    match = [p for p in projects if p.get("slug") == slug]
    if not match:
        raise SystemExit(f"no vault project '{slug}': run `tenant {tenant_id}` first")
    _make_identity(base, token, org, match[0]["id"], f"{slug}-write", "member", wtarget)
    print(f"tenant {tenant_id}: write identity created in {wtarget}")


def main(argv: list[str]) -> None:
    base = os.environ.get("FINANCE_VAULT_URL", "http://127.0.0.1:8080").rstrip("/")
    if len(argv) == 2 and argv[0] == "bootstrap":
        bootstrap(base, argv[1], getpass.getpass("Admin password for the new vault: "))
    elif len(argv) == 2 and argv[0] == "tenant":
        create_tenant(base, argv[1])
    elif len(argv) == 2 and argv[0] == "upgrade":
        upgrade_tenant(base, argv[1])
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
