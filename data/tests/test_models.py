"""finance.models — the contract every normalize.py writes through.

As the household, when Discount reports the mortgage ending "20530810", the
normalized loan must say 2053-08-10 like Leumi's does; and when a normalizer
invents a field the models don't declare, the run must fail rather than ship it.
"""
import pytest
from pydantic import ValidationError

from finance.models import validate_records


def test_discount_compact_final_date_becomes_iso():
    [loan] = validate_records("loans", [{
        "lender": "Bank Discount", "loan_id": "1", "name": "משכנתא", "category": "mortgage",
        "balance": 100.0, "final_date": "20530810"}])
    assert loan["final_date"] == "2053-08-10"


def test_unset_fields_stay_out_of_the_json():
    [t] = validate_records("transactions", [{"date": "2026-10-01", "amount": -12.5,
                                             "description": "שופרסל", "category": None}])
    assert t == {"date": "2026-10-01", "amount": -12.5, "description": "שופרסל", "category": None}


def test_undeclared_field_is_rejected():
    with pytest.raises(ValidationError):
        validate_records("transactions", [{"date": "2026-10-01", "amount": -1, "merchant_id": "x"}])
