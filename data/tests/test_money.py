"""`Money` (Decimal in Python, JSON float, Numeric(12,2) column) and the `*Fields` base pattern.

The guard that matters: validating the real normalized accounts, cards, loans and savings
through the Decimal models must dump exactly the values the old float models wrote. Only the
key order of `currency` moved (it is the record's, not the shared field list's).
"""
import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import MetaData, Numeric
from sqlalchemy.orm import registry
from sqlmodel import Field, SQLModel

from finance.models import Account, AccountFields, Money, MoneySQL, validate_records

DATA = Path(__file__).resolve().parents[1]
SCRAPED = ("accounts", "credit_cards", "loans", "savings")
FILES = sorted(p for e in SCRAPED for p in DATA.glob(f"*/normalized/{e}.json"))

BASE = {"institution": "leumi", "account_id": "1", "kind": "checking"}


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_real_records_round_trip_unchanged(path):
    records = json.loads(path.read_text())["records"]
    dumped = validate_records(path.stem, records)
    assert dumped == records
    # every float prints the same text it did before
    assert json.dumps(dumped, sort_keys=True, ensure_ascii=False) == json.dumps(records, sort_keys=True, ensure_ascii=False)


def test_int_dumps_as_float_like_before():
    out = validate_records("accounts", [{**BASE, "balance": 100}])
    assert json.dumps(out[0]["balance"]) == "100.0"


def test_float_text_survives():
    out = validate_records("accounts", [{**BASE, "balance": 0.1, "available_balance": "2413.94"}])
    assert json.dumps(out[0]["balance"]) == "0.1"
    assert out[0]["available_balance"] == 2413.94
    assert Account.model_validate({**BASE, "balance": 0.1}).balance == Decimal("0.1")


def test_optional_money_may_be_none_and_unset_is_omitted():
    a = Account.model_validate({**BASE, "balance": 1, "overdraft_limit": None})
    assert a.overdraft_limit is None and a.available_balance is None
    assert validate_records("accounts", [{**BASE, "balance": 1, "overdraft_limit": None}])[0] == {
        **BASE, "balance": 1.0, "overdraft_limit": None}


def test_python_mode_is_decimal():
    a = Account.model_validate({**BASE, "balance": 12.5})
    assert isinstance(a.balance, Decimal)
    assert isinstance(a.model_dump()["balance"], Decimal)
    assert isinstance(a.model_dump(mode="json")["balance"], float)


def test_account_still_forbids_extras_and_defaults_currency():
    assert Account.model_validate({**BASE, "balance": 1}).currency == "ILS"
    with pytest.raises(ValidationError):
        Account.model_validate({**BASE, "balance": 1, "nope": 1})
    with pytest.raises(ValidationError):
        Account.model_validate({**BASE, "balance": "abc"})


def test_row_class_can_reuse_the_field_list():
    """A table class on a throwaway registry (not tables.py) reuses AccountFields."""
    class Scratch(SQLModel, registry=registry(metadata=MetaData())):
        pass

    class Row(AccountFields, Scratch, table=True):
        __tablename__ = "scratch_accounts"
        id: int | None = Field(default=None, primary_key=True)

    cols = Row.__table__.c
    for name in ("balance", "available_balance", "overdraft_limit"):
        assert isinstance(cols[name].type, Numeric)
        assert (cols[name].type.precision, cols[name].type.scale) == (12, 2)
    assert cols["balance"].nullable is False and cols["overdraft_limit"].nullable is True
    assert set(cols.keys()) == set(AccountFields.model_fields) | {"id"}
    assert Row.__table__.metadata is Scratch.metadata is not SQLModel.metadata
    assert "scratch_accounts" not in SQLModel.metadata.tables
    assert MoneySQL.precision == 12
