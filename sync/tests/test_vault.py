"""The per-tenant vault client: one project and one identity per tenant, nothing else is readable."""
import json

import pytest

from finance import vault

A = "aaaaaaaa-0000-4000-8000-00000000000a"
B = "bbbbbbbb-0000-4000-8000-00000000000b"
ENV = {"FINANCE_VAULT_URL": "http://127.0.0.1:8080"}


def _identity(home, tenant, mode=0o600):
    d = home / ".finance-vault"
    d.mkdir(exist_ok=True)
    f = d / f"{tenant}.json"
    f.write_text(json.dumps({"client_id": "cid", "client_secret": "sec"}))
    f.chmod(mode)


def test_off_unless_the_url_is_set():
    assert not vault.enabled({})
    assert vault.enabled(ENV)


def test_fetches_only_the_tenants_own_project(tmp_path, monkeypatch):
    _identity(tmp_path, A)
    calls = []

    def fake(url, *, body=None, token=None):
        calls.append((url, body, token))
        if "login" in url:
            return {"accessToken": "tok"}
        return {"secrets": [{"secretKey": "CAL_USERNAME", "secretValue": "u"}]}

    monkeypatch.setattr(vault, "_call", fake)
    assert vault.fetch_tenant_secrets(A, ENV, tmp_path) == {"CAL_USERNAME": "u"}
    assert calls[0][1] == {"clientId": "cid", "clientSecret": "sec"}
    assert f"workspaceSlug=tenant-{A}" in calls[1][0] and calls[1][2] == "tok"


def test_a_tenant_without_its_own_identity_never_borrows_anothers(tmp_path):
    _identity(tmp_path, A)
    with pytest.raises(vault.VaultError, match="no vault identity"):
        vault.fetch_tenant_secrets(B, ENV, tmp_path)


def test_an_identity_file_others_can_read_is_refused(tmp_path):
    _identity(tmp_path, A, mode=0o644)
    with pytest.raises(vault.VaultError, match="chmod 600"):
        vault.fetch_tenant_secrets(A, ENV, tmp_path)


def test_a_tenant_id_that_is_not_a_uuid_never_reaches_the_url():
    with pytest.raises(ValueError):
        vault.project_slug("../x")
