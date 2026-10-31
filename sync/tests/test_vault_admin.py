"""vault_admin.import_env: only the sources' connection variables move from .env into the vault."""
import json

import pytest

from finance import vault, vault_admin

T = "aaaaaaaa-0000-4000-8000-00000000000a"


def _env(tmp_path, text):
    f = tmp_path / ".env"
    f.write_text(text)
    return f


def test_parses_comments_quotes_and_export(tmp_path):
    f = _env(tmp_path, '# c\nA=1\nexport B="two words"\nC=\'x\'\n\nnot a pair\nD=a=b\n')
    assert vault_admin.parse_env_file(f) == {"A": "1", "B": "two words", "C": "x", "D": "a=b"}


def test_imports_only_source_logins_and_never_infrastructure_secrets(tmp_path, monkeypatch):
    wdir = tmp_path / ".finance-vault-write"
    wdir.mkdir()
    (wdir / f"{T}.json").write_text(json.dumps({"client_id": "c", "client_secret": "s"}))
    sent = {}
    monkeypatch.setattr(vault, "set_secret", lambda t, n, v, env=None, home=None: sent.__setitem__(n, (t, v)))
    f = _env(tmp_path, "AMEX_ID=123456789\nAMEX_PASSWORD=pw\nAMEX_CARD6_DIGITS=\n"
                       "POSTGRES_PASSWORD=db\nFINANCE_API_ORIGIN_SECRET=o\nAWS_SECRET_ACCESS_KEY=k\n")
    names = vault_admin.import_env(T, f, home=tmp_path)
    assert names == ["AMEX_ID", "AMEX_PASSWORD"]          # the empty one and the infrastructure ones stay behind
    assert sent == {"AMEX_ID": (T, "123456789"), "AMEX_PASSWORD": (T, "pw")}


def test_needs_a_write_identity(tmp_path):
    with pytest.raises(SystemExit, match="no write identity"):
        vault_admin.import_env(T, _env(tmp_path, "AMEX_ID=1\n"), home=tmp_path)
