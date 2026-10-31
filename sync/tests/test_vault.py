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


def _write_identity(home, tenant, mode=0o600):
    d = home / ".finance-vault-write"
    d.mkdir(exist_ok=True)
    f = d / f"{tenant}.json"
    f.write_text(json.dumps({"client_id": "wcid", "client_secret": "wsec"}))
    f.chmod(mode)


def test_writing_is_a_separate_opt_in_from_the_read_identity(tmp_path):
    assert not vault.can_write(A, ENV, tmp_path)
    _identity(tmp_path, A)                                   # the read identity alone does not allow writes
    assert not vault.can_write(A, ENV, tmp_path)
    _write_identity(tmp_path, A)
    assert vault.can_write(A, ENV, tmp_path)
    assert not vault.can_write(B, ENV, tmp_path)
    assert not vault.can_write(A, {}, tmp_path)


def test_the_write_directory_can_be_mounted_elsewhere(tmp_path):
    env = {**ENV, "FINANCE_VAULT_WRITE_DIR": str(tmp_path / "mnt")}
    assert vault.write_identity_path(A, env) == tmp_path / "mnt" / f"{A}.json"


def test_status_lists_names_and_times_never_values(tmp_path, monkeypatch):
    _write_identity(tmp_path, A)
    calls = []

    def fake(url, *, body=None, token=None, method=None):
        calls.append((url, body))
        if "login" in url:
            return {"accessToken": "tok"}
        return {"secrets": [{"secretKey": "CAL_USERNAME", "secretValue": "hunter2", "updatedAt": "2026-10-31T10:00:00Z"}]}

    monkeypatch.setattr(vault, "_call", fake)
    out = vault.secret_status(A, ENV, tmp_path)
    assert out == {"CAL_USERNAME": "2026-10-31T10:00:00Z"}
    assert calls[0][1] == {"clientId": "wcid", "clientSecret": "wsec"}   # the write identity, not the read one
    assert "viewSecretValue=false" in calls[1][0] and f"workspaceSlug={A}" in calls[1][0]


def test_set_secret_updates_and_creates_when_missing(tmp_path, monkeypatch):
    _write_identity(tmp_path, A)
    seen = []

    def fake(url, *, body=None, token=None, method=None):
        if "login" in url:
            return {"accessToken": "tok"}
        seen.append((method, url, body["secretValue"], body["workspaceSlug"]))
        if method == "PATCH":
            raise vault.VaultError("vault refused the request (HTTP 404)", status=404)
        return {}

    monkeypatch.setattr(vault, "_call", fake)
    vault.set_secret(A, "CAL_PASSWORD", "s3cret", ENV, tmp_path)
    assert [m for m, *_ in seen] == ["PATCH", "POST"]
    assert seen[1][1].endswith("/api/v3/secrets/raw/CAL_PASSWORD") and seen[1][2:] == ("s3cret", A)


def test_a_refused_write_is_not_retried_as_a_create(tmp_path, monkeypatch):
    _write_identity(tmp_path, A)

    def fake(url, *, body=None, token=None, method=None):
        if "login" in url:
            return {"accessToken": "tok"}
        raise vault.VaultError("vault refused the request (HTTP 403)", status=403)

    monkeypatch.setattr(vault, "_call", fake)
    with pytest.raises(vault.VaultError, match="403") as e:
        vault.set_secret(A, "CAL_PASSWORD", "s3cret", ENV, tmp_path)
    assert "s3cret" not in str(e.value)


def test_another_tenants_write_identity_is_never_borrowed(tmp_path):
    _write_identity(tmp_path, A)
    with pytest.raises(vault.VaultError, match="no vault identity"):
        vault.set_secret(B, "CAL_PASSWORD", "x", ENV, tmp_path)
