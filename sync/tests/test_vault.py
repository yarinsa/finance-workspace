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


def test_a_tenant_opts_in_by_having_an_identity_file(tmp_path):
    assert not vault.uses_vault(A, ENV, tmp_path)          # configured, but no identity: keeps its .env
    _identity(tmp_path, A)
    assert vault.uses_vault(A, ENV, tmp_path)
    assert not vault.uses_vault(B, ENV, tmp_path)          # another tenant is unaffected
    assert not vault.uses_vault(A, {}, tmp_path)           # vault not configured at all


def test_an_outage_is_retryable_but_a_refusal_is_not(monkeypatch):
    import urllib.error
    import urllib.request

    def boom(*a, **k):
        raise ConnectionRefusedError()

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    with pytest.raises(vault.VaultError) as e:
        vault._call("http://127.0.0.1:1/x")
    assert e.value.retryable

    def denied(*a, **k):
        raise urllib.error.HTTPError("u", 403, "no", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", denied)
    with pytest.raises(vault.VaultError) as e:
        vault._call("http://127.0.0.1:1/x")
    assert not e.value.retryable


def test_an_unknown_backend_is_refused(tmp_path):
    _identity(tmp_path, A)
    with pytest.raises(vault.VaultError, match="unknown vault backend"):
        vault.fetch_tenant_secrets(A, {**ENV, "FINANCE_VAULT_BACKEND": "nope"}, tmp_path)


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
    assert f"workspaceSlug={A}" in calls[1][0] and calls[1][2] == "tok"


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
