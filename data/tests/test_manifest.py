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
        "discount": {"accounts", "transactions"},
        "discount-business": {"accounts", "credit_cards", "transactions"},
        "discount-mortgage": {"loans"},
        "leumi": {"accounts", "loans", "transactions"},
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
        '{"name": "more", "label": "x", "account_types": ["pension"], "capabilities": ["savings"]}')
    with pytest.raises(ValueError, match="declares name"):
        manifest.load("harel", tmp_path)
