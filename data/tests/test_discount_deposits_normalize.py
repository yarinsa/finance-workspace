"""Discount deposits (פיקדונות) normalize tests.

As the household, when Discount reports a real deposit
("נזיל יומי+" / ₪9,542.30) it should surface as a `savings` record with
`liquid: true` (daily exit) — and when the discount-business dump comes back
as the bank's "no active deposits" Error envelope, it must normalize to ZERO
records rather than crash or emit a phantom row.
"""
import importlib.util
import json
from pathlib import Path

import digest


def _load_normalize(source_dir, raw_files, tmp_path):
    """Execute <source_dir>/normalize.py against a temp raw/ dir, return entities."""
    src = Path(digest.__file__).resolve().parent / source_dir / "normalize.py"
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, content in raw_files.items():
        (raw / name).write_text(json.dumps(content), encoding="utf-8")

    mod = importlib.util.module_from_spec(
        importlib.util.spec_from_loader(f"{source_dir}_normalize", loader=None))
    code = src.read_text(encoding="utf-8").replace(
        'HERE = Path(__file__).resolve().parent', f'HERE = Path(r"{tmp_path}")')
    mod.__dict__["__file__"] = str(src)
    exec(compile(code, str(src), "exec"), mod.__dict__)

    out = {}
    for fp in (tmp_path / "normalized").glob("*.json"):
        out[fp.stem] = json.loads(fp.read_text())
    return out


REAL_DISCOUNT_DEPOSIT = {
    "DepositsDetails": {
        "BusinessDate": "20260906",
        "TotalDepositsCurrentValue": 9542.3,
        "CurrencyCode": "ILS",
        "VariableRate": 4.75,
        "DepositAccountBlock": {
            "DepositAccountEntry": [
                {
                    "ProductFamily": "0",
                    "ProductCode": "0100",
                    "ProductShortName": "נזיל יומי+",
                    "ProductLongName": "נזיל יומי+ לשנתיים",
                    "TermNewAccountNumber": "00110034771009279965",
                    "AccountNumber": "",
                    "TotalDepositsCurrentValue": 9542.3,
                    "CurrencyCode": "ILS",
                }
            ]
        },
    }
}

BUSINESS_NO_ACTIVE_DEPOSITS = {
    "Error": {
        "MsgText": "לא נמצאו הפקדות פעילות",
        "ReturnedCode": "RET011039",
        "SeverityCode": "WARNING",
        "GeneratedCode": "588688",
    }
}


def test_real_discount_deposit_normalizes_to_liquid_savings(tmp_path):
    out = _load_normalize(
        "discount",
        {"deposits_depositsDetails.json": REAL_DISCOUNT_DEPOSIT},
        tmp_path,
    )
    records = out["savings"]["records"]
    assert len(records) == 1
    r = records[0]
    assert r["institution"] == "discount"
    assert r["kind"] == "bank_deposit"
    assert r["label"] == "נזיל יומי+"
    assert r["balance"] == 9542.3
    assert r["liquid"] is True
    assert r["account_id"] == "00110034771009279965"


def test_discount_deposit_never_emits_transactions(tmp_path):
    out = _load_normalize(
        "discount",
        {"deposits_depositsDetails.json": REAL_DISCOUNT_DEPOSIT},
        tmp_path,
    )
    # transactions.json is emitted by the normal txn path (empty list here since
    # no fetch-transactions_*.json was seeded) — it must not contain deposit rows.
    assert out["transactions"]["records"] == []


def test_business_no_active_deposits_yields_zero_records(tmp_path):
    """The bank's warning envelope for 'no active deposits' must not crash and
    must not produce a phantom savings record."""
    out = _load_normalize(
        "discount-business",
        {"deposits_depositsDetails.json": BUSINESS_NO_ACTIVE_DEPOSITS},
        tmp_path,
    )
    assert out["savings"]["records"] == []


def test_missing_deposit_file_yields_zero_records(tmp_path):
    """No deposits_depositsDetails.json at all (e.g. never scraped) -> no crash."""
    out = _load_normalize("discount", {}, tmp_path)
    assert out["savings"]["records"] == []


def test_liquid_vs_illiquid_split_in_snapshot_totals():
    """digest.py must separate liquid bank deposits from illiquid pension/study
    funds so net_position_with_savings doesn't imply locked money is available."""
    entities = {
        "accounts": [{"institution": "discount", "account_id": "1", "kind": "checking",
                      "balance": 1000.0, "currency": "ILS"}],
        "credit_cards": [],
        "loans": [],
        "income": [],
        "savings": [
            {"institution": "harel", "kind": "pension", "label": "קרנות פנסיה",
             "balance": 359740.0, "currency": "ILS", "liquid": False},
            {"institution": "discount", "kind": "bank_deposit", "label": "נזיל יומי+",
             "balance": 9542.3, "currency": "ILS", "liquid": True},
        ],
    }
    snap = digest.build_snapshot(entities)
    t = snap["totals"]

    assert t["long_term_savings"] == round(359740.0 + 9542.3, 2)
    assert t["liquid_savings"] == 9542.3
    assert t["illiquid_savings"] == 359740.0
    assert t["tracked_net_position"] == 1000.0
    assert t["net_position_with_savings"] == round(1000.0 + 359740.0 + 9542.3, 2)
