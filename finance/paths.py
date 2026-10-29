"""Where a tenant's files live (docs/tenancy.md).

The default (master) tenant keeps the layout the household always had: `data/<source>/raw`,
`data/digested`, `data/goals`, ... Any other tenant gets the same tree under
`data/tenants/<tenant_id>/`. The tenant is chosen once, per process, by `FINANCE_TENANT_ID`
(the sync worker starts a child process per tenant), so module-level paths are safe.
`FINANCE_DATA_DIR` still points the whole thing at another checkout's data (read-only use).
Code (the `normalize.py` scripts, `db/`) is never under a tenant directory."""
import os
import uuid
from pathlib import Path

from finance.tenancy import DEFAULT_TENANT_ID

CODE_DATA = Path(__file__).resolve().parent.parent / "data"   # the checkout's data/ (code + default tenant)


def tenant_id_from_env(env=None):
    raw = (env if env is not None else os.environ).get("FINANCE_TENANT_ID")
    return uuid.UUID(raw) if raw else DEFAULT_TENANT_ID


def data_root(tenant_id=None, env=None):
    """The directory holding one tenant's source dumps, normalized output and digested files."""
    env = os.environ if env is None else env
    tenant_id = uuid.UUID(str(tenant_id)) if tenant_id else tenant_id_from_env(env)
    base = Path(env.get("FINANCE_DATA_DIR") or CODE_DATA)
    return base if tenant_id == DEFAULT_TENANT_ID else base / "tenants" / str(tenant_id)


def source_dir(here, env=None):
    """A source's directory for a `normalize.py` living in `here`: itself for the master tenant
    (the layout never moved), the same-named directory in the tenant's tree for any other."""
    here = Path(here)
    if tenant_id_from_env(env) == DEFAULT_TENANT_ID:
        return here
    return data_root(env=env) / here.name
