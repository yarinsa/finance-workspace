"""Per-tenant secrets from the self-hosted Infisical vault (docs/secrets-vault.md).

One Infisical project per tenant, project slug = the tenant id (36 chars, Infisical's maximum). Each tenant has its own
machine identity (Universal Auth) that can read only its own project; the identity's
client id/secret live in ``~/.finance-vault/<tenant-id>.json`` (mode 0600) on the Mac.
A tenant is moved over one at a time: it uses the vault only when ``FINANCE_VAULT_URL`` is set AND its
identity file exists; otherwise it keeps reading its .env file exactly as before. ``FINANCE_VAULT_BACKEND``
names the implementation (only ``infisical`` today), so another backend can sit next to it.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ENVIRONMENT = "prod"
SECRET_PATH = "/"


class VaultError(RuntimeError):
    """`retryable` is True for an outage (vault down, timeout), False for a final answer
    (no identity, access denied, bad configuration)."""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def enabled(env=None) -> bool:
    return bool((env if env is not None else os.environ).get("FINANCE_VAULT_URL"))


def identity_path(tenant_id, home: Path | None = None) -> Path:
    return (home or Path.home()) / ".finance-vault" / f"{uuid.UUID(str(tenant_id))}.json"


def uses_vault(tenant_id, env=None, home: Path | None = None) -> bool:
    """The per-tenant opt-in: vault configured and this tenant has its own identity file."""
    return enabled(env) and identity_path(tenant_id, home).exists()


def project_slug(tenant_id) -> str:
    # The bare uuid: Infisical caps a project slug at 36 characters, so a "tenant-" prefix does not fit.
    return str(uuid.UUID(str(tenant_id)))   # the uuid parse keeps anything else out of the URL


def _identity(tenant_id, home: Path | None = None) -> dict:
    path = identity_path(tenant_id, home)
    if not path.exists():
        raise VaultError(f"no vault identity for tenant {tenant_id}: {path}")
    if path.stat().st_mode & 0o077:
        raise VaultError(f"{path} must not be readable by others (chmod 600)")
    data = json.loads(path.read_text())
    if not data.get("client_id") or not data.get("client_secret"):
        raise VaultError(f"{path} needs client_id and client_secret")
    return data


def _call(url: str, *, body: dict | None = None, token: str | None = None) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:   # never echo the response body: it may carry a secret
        raise VaultError(f"vault refused the request (HTTP {e.code})", retryable=e.code >= 500) from None
    except Exception as e:   # connection refused, timeout: the vault is down, a retry may work
        raise VaultError(f"vault unreachable: {type(e).__name__}", retryable=True) from None


def fetch_tenant_secrets(tenant_id, env=None, home: Path | None = None) -> dict[str, str]:
    """All secrets of the tenant's project as {NAME: value}. Raises VaultError, never falls
    back to another tenant's identity or to the repo .env."""
    e = env if env is not None else os.environ
    if e.get("FINANCE_VAULT_BACKEND", "infisical") != "infisical":
        raise VaultError(f"unknown vault backend {e['FINANCE_VAULT_BACKEND']!r}")
    base = e.get("FINANCE_VAULT_URL", "").rstrip("/")
    if not base:
        raise VaultError("FINANCE_VAULT_URL is not set")
    ident = _identity(tenant_id, home)
    login = _call(f"{base}/api/v1/auth/universal-auth/login",
                  body={"clientId": ident["client_id"], "clientSecret": ident["client_secret"]})
    query = urllib.parse.urlencode({"workspaceSlug": project_slug(tenant_id), "environment": ENVIRONMENT,
                                    "secretPath": SECRET_PATH})
    res = _call(f"{base}/api/v3/secrets/raw?{query}", token=login["accessToken"])
    return {s["secretKey"]: s["secretValue"] for s in res.get("secrets", [])}
