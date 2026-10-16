"""Request bodies shared by the REST routes and the GraphQL mutations (api/gql/inputs.py).

One definition of what an override or tag edit may contain, so both paths validate alike.
"""
import sys
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "db"))   # the shared tag rules
import tags  # noqa: E402


class Patch(BaseModel):
    """Any of the override fields; null clears that field. Unknown fields are rejected."""
    model_config = ConfigDict(extra="forbid")

    category: str | None = Field(default=None, max_length=64)
    note: str | None = Field(default=None, max_length=500)
    excluded: bool | None = None
    horizon: Literal["current", "near", "future"] | None = None

    @field_validator("category", "note")
    @classmethod
    def blank_clears(cls, v):
        return (v.strip() or None) if v is not None else None


class TagSet(BaseModel):
    """The full set of tag names for one transaction (replaces what was there)."""
    model_config = ConfigDict(extra="forbid")

    tags: list[str] = Field(max_length=20)

    @field_validator("tags")
    @classmethod
    def valid_names(cls, v):
        return [tags.clean_name(n) for n in v]


class TagEdit(BaseModel):
    """Rename and/or recolor a tag; `color: null` clears it."""
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")

    @field_validator("name")
    @classmethod
    def valid_name(cls, v):
        return tags.clean_name(v) if v is not None else None
