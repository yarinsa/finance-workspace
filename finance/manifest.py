"""Each sync source declares itself in `data/<source>/manifest.json`.

The manifest says what the source is (name, Hebrew label, the kinds of account it
holds) and which normalized entities it provides (`capabilities`). The sync
registry, the digest and the app read these instead of keeping their own lists.
Connection details (login form, credentials) will be declared here later as a JSON
Schema, so a source describes how to connect to it too.
"""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

AccountType = Literal[
    "checking", "business_checking", "credit_card", "mortgage", "loan",
    "pension", "study_fund", "provident_fund",
]
Capability = Literal["accounts", "credit_cards", "transactions", "loans", "savings", "income", "subscription"]


class SourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    label: str
    account_types: tuple[AccountType, ...]
    capabilities: tuple[Capability, ...]


def load(name: str, data_dir: Path = DATA_DIR) -> SourceManifest:
    manifest = SourceManifest.model_validate_json((data_dir / name / "manifest.json").read_text(encoding="utf-8"))
    if manifest.name != name:
        raise ValueError(f"{name}/manifest.json declares name {manifest.name!r}")
    return manifest


def load_all(data_dir: Path = DATA_DIR) -> dict[str, SourceManifest]:
    """Every source's manifest by name, in directory order."""
    return {p.parent.name: load(p.parent.name, data_dir) for p in sorted(data_dir.glob("*/manifest.json"))}
