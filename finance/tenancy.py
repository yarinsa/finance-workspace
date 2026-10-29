"""Tenant constants and context shared by the API, the data layer and the jobs.

Every customer-data row carries a `tenant_id`. Postgres Row-Level Security filters on the
transaction-local setting `app.tenant_id`, which `bind` sets; the column default reads the
same setting, so inserts land in the current tenant. A missing setting is an error (the
`::uuid` cast of an unset or empty value fails), never "return all"."""
import contextvars
import os
import uuid
from dataclasses import dataclass

# The tenant that holds everything scraped before tenants existed (migration 0016).
DEFAULT_TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
ROLES = ("owner", "admin", "member")


class TenantContextMissing(RuntimeError):
    """A data access ran with no tenant bound."""


@dataclass(frozen=True)
class TenantContext:
    user_id: uuid.UUID | None
    tenant_id: uuid.UUID
    role: str | None = None


_current = contextvars.ContextVar("tenant_context", default=None)


def set_context(ctx):
    """Bind `ctx` for the current task; returns the token for `reset_context`."""
    return _current.set(ctx)


def reset_context(token):
    _current.reset(token)


def current():
    """The bound TenantContext. Raises TenantContextMissing: never falls back to a default."""
    ctx = _current.get()
    if ctx is None:
        raise TenantContextMissing("no tenant bound to this request or job")
    return ctx


def bind(conn, tenant_id, local=True):
    """Pin `conn` to `tenant_id` for Row-Level Security (`app.tenant_id`).

    `local=True` is SET LOCAL: it dies with the current transaction. The API binds with
    `local=False` and `unbind`s in a `finally`, because the stores commit mid-request (a
    commit would drop a transaction-local setting); the pool hands a connection to one
    request at a time and every request binds its own tenant before its first statement."""
    tenant_id = uuid.UUID(str(tenant_id))   # rejects anything that is not a uuid before SQL sees it
    conn.execute("SELECT set_config('app.tenant_id', %s, %s)", (str(tenant_id), local))


def unbind(conn):
    """Clear the tenant from `conn`: a data query on it now fails instead of returning rows."""
    conn.execute("SELECT set_config('app.tenant_id', '', false)")


def resolve_tenant_id(tenant_id=None):
    """The tenant for a host-side data access: the argument, else the bound context, else the
    FINANCE_TENANT_ID environment variable a parent job passed down. Raises
    TenantContextMissing when none is set; there is no silent default."""
    if tenant_id is not None:
        return uuid.UUID(str(tenant_id))
    ctx = _current.get()
    if ctx is not None:
        return ctx.tenant_id
    env = os.environ.get("FINANCE_TENANT_ID")
    if env:
        return uuid.UUID(env)
    raise TenantContextMissing("no tenant bound: pass tenant_id, bind a TenantContext or set FINANCE_TENANT_ID")


def use_cli_tenant():
    """For `__main__` entry points of the household's own scripts: run as FINANCE_TENANT_ID,
    or as the default tenant when it is unset (the single-household behaviour from before
    tenants). The data layer itself never defaults; only these entry points do."""
    tenant_id = uuid.UUID(os.environ.get("FINANCE_TENANT_ID") or str(DEFAULT_TENANT_ID))
    os.environ["FINANCE_TENANT_ID"] = str(tenant_id)
    set_context(TenantContext(None, tenant_id, None))
    return tenant_id
