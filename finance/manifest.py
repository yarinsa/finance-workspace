"""Each sync source declares itself in `data/<source>/manifest.json`.

The manifest says what the source is (name, Hebrew label, the kinds of account it
holds) and which normalized entities it provides (`capabilities`). The sync
registry, the digest and the app read these instead of keeping their own lists.
`connection` is a JSON Schema (draft 2020-12 object) for the source's connection form,
rendered in the app with react-jsonschema-form. Each property names the `.env` variable it
maps to in `x-env`; `writeOnly` marks a secret. The schema only describes what to set:
values are never read back through the app: a household with a vault write identity can set them from the
syncs screen (stored in its vault, api/gql/sync.py); otherwise they stay in the Mac's `.env`.
"""
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

AccountType = Literal[
    "checking", "business_checking", "credit_card", "mortgage", "loan",
    "pension", "study_fund", "provident_fund",
]
Capability = Literal["accounts", "credit_cards", "transactions", "loans", "savings", "balance_days"]


class SourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    label: str
    account_types: tuple[AccountType, ...]
    capabilities: tuple[Capability, ...]
    connection: dict

    @field_validator("connection")
    @classmethod
    def _connection_is_a_form_schema(cls, schema: dict) -> dict:
        if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
            raise ValueError("connection must be a JSON Schema object with properties")
        for key, prop in schema["properties"].items():
            if prop.get("type") != "string" or not isinstance(prop.get("x-env"), str):
                raise ValueError(f"connection.{key} must be a string field with an x-env variable")
        unknown = set(schema.get("required", [])) - set(schema["properties"])
        if unknown:
            raise ValueError(f"connection requires unknown fields: {sorted(unknown)}")
        return schema

    @property
    def env_vars(self) -> tuple[str, ...]:
        """The .env variables the connection reads, in form order."""
        return tuple(p["x-env"] for p in self.connection["properties"].values())


def load(name: str, data_dir: Path = DATA_DIR) -> SourceManifest:
    manifest = SourceManifest.model_validate_json((data_dir / name / "manifest.json").read_text(encoding="utf-8"))
    if manifest.name != name:
        raise ValueError(f"{name}/manifest.json declares name {manifest.name!r}")
    return manifest


def load_all(data_dir: Path = DATA_DIR) -> dict[str, SourceManifest]:
    """Every source's manifest by name, in directory order."""
    return {p.parent.name: load(p.parent.name, data_dir) for p in sorted(data_dir.glob("*/manifest.json"))}
