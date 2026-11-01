"""Every sync source's manifest.json: valid, and honest about what its normalizer emits."""
import re

import pytest

from finance import manifest
from finance.manifest import DATA_DIR

SOURCES = sorted(p.parent.name for p in DATA_DIR.glob("*/normalize.py") if p.parent.name != "riseup")


@pytest.mark.parametrize("name", SOURCES)
def test_every_synced_source_has_a_manifest(name):
    m = manifest.load(name)
    assert m.label and m.account_types and m.capabilities


def test_capabilities_are_what_the_normalizer_writes():
    """The real entity sets from CLAUDE.md's Sources table: a manifest cannot promise data the source lacks."""
    assert {n: set(m.capabilities) for n, m in manifest.load_all().items() if n in SOURCES} == {
        "discount": {"accounts", "transactions", "balance_days"},
        "discount-business": {"accounts", "credit_cards", "transactions"},
        "discount-mortgage": {"loans"},
        "leumi": {"accounts", "loans", "transactions", "balance_days"},
        "cal": {"credit_cards", "transactions"},
        "amex": {"credit_cards", "transactions"},
        "max": {"credit_cards", "transactions"},
        "harel": {"savings"},
        "more": {"savings"},
        "analyst": {"savings"},
    }


def test_manifest_name_must_match_its_directory(tmp_path):
    (tmp_path / "harel").mkdir()
    (tmp_path / "harel" / "manifest.json").write_text(
        '{"name": "more", "label": "x", "account_types": ["pension"], "capabilities": ["savings"], '
        '"connection": {"type": "object", "properties": {}}}')
    with pytest.raises(ValueError, match="declares name"):
        manifest.load("harel", tmp_path)


SCRAPER_DIR = {"discount-business": "discount", "discount-mortgage": "discount"}


@pytest.mark.parametrize("name", SOURCES)
def test_connection_fields_are_the_env_vars_the_scraper_reads(name):
    """A form must not ask for a variable the scraper ignores (or hide one it needs)."""
    m = manifest.load(name)
    scraper = DATA_DIR.parent / "scrapers" / SCRAPER_DIR.get(name, name)
    code = "".join(p.read_text() for p in scraper.glob("*.mjs")) if scraper.is_dir() else ""
    read = set(re.findall(r"process\.env\.([A-Z0-9_]+)", code))
    assert set(m.env_vars) <= read, name
    if name == "discount-business":  # the SME login page takes no account code
        assert "DISCOUNT_NUM" not in m.env_vars


def test_a_secret_is_write_only_and_never_has_a_value():
    for m in manifest.load_all().values():
        for prop in m.connection["properties"].values():
            assert "default" not in prop and "const" not in prop


def test_connection_must_be_a_form_schema(tmp_path):
    (tmp_path / "x").mkdir()
    base = '{"name":"x","label":"x","account_types":["checking"],"capabilities":["accounts"],"connection":%s}'
    (tmp_path / "x" / "manifest.json").write_text(base % '{"type":"object","properties":{"A":{"type":"string"}}}')
    with pytest.raises(ValueError, match="x-env"):
        manifest.load("x", tmp_path)
