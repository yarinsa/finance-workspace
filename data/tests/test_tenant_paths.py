"""Each tenant's files live in their own tree; the master tenant keeps the original layout."""
import uuid
from pathlib import Path

from finance.paths import CODE_DATA, data_root
from finance.tenancy import DEFAULT_TENANT_ID

T = uuid.UUID("aaaaaaaa-0000-4000-8000-00000000000a")


def test_master_tenant_keeps_the_original_data_directory():
    assert data_root(DEFAULT_TENANT_ID, env={}) == CODE_DATA
    assert data_root(env={}) == CODE_DATA   # no tenant in the environment = the master tenant


def test_other_tenants_get_their_own_tree():
    assert data_root(T, env={}) == CODE_DATA / "tenants" / str(T)
    assert data_root(env={"FINANCE_TENANT_ID": str(T)}) == CODE_DATA / "tenants" / str(T)


def test_data_dir_override_applies_under_the_tenant():
    env = {"FINANCE_DATA_DIR": "/elsewhere", "FINANCE_TENANT_ID": str(T)}
    assert data_root(env=env) == Path("/elsewhere/tenants") / str(T)
    assert data_root(DEFAULT_TENANT_ID, env={"FINANCE_DATA_DIR": "/elsewhere"}) == Path("/elsewhere")


def test_two_tenants_never_share_a_directory():
    other = uuid.uuid4()
    assert data_root(T, env={}) != data_root(other, env={})


def test_a_normalizer_reads_its_own_directory_for_the_master_and_the_tenants_for_others():
    from finance.paths import source_dir
    here = Path("/code/data/cal")
    assert source_dir(here, env={}) == here
    assert source_dir(here, env={"FINANCE_TENANT_ID": str(T)}) == CODE_DATA / "tenants" / str(T) / "cal"
