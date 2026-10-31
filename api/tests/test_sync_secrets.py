"""Entering a source's connection secrets from the app: names come from the manifest, the value goes
straight to the tenant's vault and is never kept, echoed or logged. No database needed."""
import json

import pytest
from pydantic import ValidationError

from api.gql import sync
from api.gql.inputs import SyncSourceSecretSetInput
from finance import vault

A = "aaaaaaaa-0000-4000-8000-00000000000a"
B = "bbbbbbbb-0000-4000-8000-00000000000b"
ENV = {"FINANCE_VAULT_URL": "http://vault:8080"}
VALUE = "p@ss-never-echoed"


@pytest.fixture
def vault_env(tmp_path, monkeypatch):
    """Tenant A has a write identity in a mounted directory; B has none."""
    d = tmp_path / "w"
    d.mkdir()
    f = d / f"{A}.json"
    f.write_text(json.dumps({"client_id": "c", "client_secret": "s"}))
    f.chmod(0o600)
    env = {**ENV, "FINANCE_VAULT_WRITE_DIR": str(d)}
    return env


def test_the_fields_are_the_manifests_connection_variables():
    names = [f["name"] for f in sync.connection_fields("amex")]
    assert names == ["AMEX_ID", "AMEX_CARD6_DIGITS", "AMEX_PASSWORD"]
    masked = {f["name"]: f["masked"] for f in sync.connection_fields("amex")}
    assert masked == {"AMEX_ID": False, "AMEX_CARD6_DIGITS": True, "AMEX_PASSWORD": True}


def test_an_unknown_source_is_refused():
    with pytest.raises(sync.SecretsError, match="unknown source"):
        sync.connection_fields("../etc")


def test_a_household_without_a_write_identity_sees_fields_it_cannot_edit(vault_env):
    view = sync.secrets_view(B, "amex", vault_env)
    assert view["can_edit"] is False
    assert all(f["is_set"] is False for f in view["fields"])


def test_status_marks_what_the_vault_holds_and_never_a_value(vault_env, monkeypatch):
    monkeypatch.setattr(vault, "secret_status", lambda t, env=None, home=None: {"AMEX_ID": "2026-10-31T10:00:00+00:00"})
    view = sync.secrets_view(A, "amex", vault_env)
    assert view["can_edit"] is True
    assert {f["name"]: f["is_set"] for f in view["fields"]} == {
        "AMEX_ID": True, "AMEX_CARD6_DIGITS": False, "AMEX_PASSWORD": False}
    assert VALUE not in json.dumps(view, default=str)


def test_only_a_manifest_name_can_be_written(vault_env, monkeypatch):
    monkeypatch.setattr(vault, "set_secret", lambda *a, **k: pytest.fail("must not reach the vault"))
    with pytest.raises(sync.SecretsError, match="not one of this source"):
        sync.set_secret(A, "amex", "CAL_PASSWORD", VALUE, vault_env)       # another source's variable
    with pytest.raises(sync.SecretsError, match="not one of this source"):
        sync.set_secret(A, "amex", "AWS_SECRET_ACCESS_KEY", VALUE, vault_env)


def test_writing_goes_to_the_requests_tenant_only(vault_env, monkeypatch):
    calls = []
    monkeypatch.setattr(vault, "set_secret", lambda t, n, v, env=None, home=None: calls.append((t, n, v)))
    monkeypatch.setattr(vault, "secret_status", lambda *a, **k: {"AMEX_PASSWORD": None})
    view = sync.set_secret(A, "amex", "AMEX_PASSWORD", VALUE, vault_env)
    assert calls == [(A, "AMEX_PASSWORD", VALUE)]
    assert next(f for f in view["fields"] if f["name"] == "AMEX_PASSWORD")["is_set"] is True
    with pytest.raises(sync.SecretsError, match="not set up for editing"):
        sync.set_secret(B, "amex", "AMEX_PASSWORD", VALUE, vault_env)       # no identity: never borrows A's
    assert len(calls) == 1


def test_a_vault_failure_is_reported_without_the_value(vault_env, monkeypatch):
    def refuse(*a, **k):
        raise vault.VaultError("vault refused the request (HTTP 403)", status=403)

    monkeypatch.setattr(vault, "set_secret", refuse)
    with pytest.raises(sync.SecretsError) as e:
        sync.set_secret(A, "amex", "AMEX_PASSWORD", VALUE, vault_env)
    assert VALUE not in str(e.value)


def test_a_rejected_value_is_never_quoted_in_the_validation_error():
    with pytest.raises(ValidationError) as e:
        SyncSourceSecretSetInput(source="amex", name="AMEX_PASSWORD", value=VALUE * 200)
    assert VALUE not in str(e.value)
    with pytest.raises(ValidationError):
        SyncSourceSecretSetInput(source="amex", name="amex_password", value=VALUE)   # not an env-var name
    with pytest.raises(ValidationError):
        SyncSourceSecretSetInput(source="amex", name="AMEX_PASSWORD", value="")
