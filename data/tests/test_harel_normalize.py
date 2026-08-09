"""Harel savings normalize tests — driven by the real 2026-08-01 scrape.

As the household, when Harel reports topic 70 = "338,361" and topic 62 =
"137,861", those should normalize to ₪338,361 of pension and ₪137,861 of study
funds — as a `savings` entity that never reaches the spending ledger.
"""
import importlib.util
import json

import pytest

import digest


def _load_harel(tmp_path, online_data, customer_products):
    """Execute data/harel/normalize.py against a temp raw/ dir."""
    from pathlib import Path
    src = Path(digest.__file__).resolve().parent / "harel" / "normalize.py"
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "online-data.json").write_text(json.dumps(online_data), encoding="utf-8")
    (raw / "customer-products.json").write_text(
        json.dumps(customer_products), encoding="utf-8")

    mod = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("harel_normalize", loader=None))
    code = src.read_text(encoding="utf-8").replace(
        'HERE = Path(__file__).resolve().parent', f'HERE = Path(r"{tmp_path}")')
    mod.__dict__["__file__"] = str(src)
    exec(compile(code, str(src), "exec"), mod.__dict__)
    return json.loads((tmp_path / "normalized" / "savings.json").read_text())


REAL_PRODUCTS = {
    "topicsList": {"2": [
        {"topicId": 60, "topicName": "גמל", "xTopicName": "השתלמות",
         "sectionName": "חסכון פנסיוני", "policiesCount": 5, "xtopicId": 62},
        {"topicId": 70, "topicName": "פנסיה", "xTopicName": "קרנות פנסיה",
         "sectionName": "חסכון פנסיוני", "policiesCount": 1, "xtopicId": 70},
    ]}
}


def test_real_balances_normalize(tmp_path):
    """The exact payload seen on 2026-08-01."""
    out = _load_harel(tmp_path, {"70": "338,361", "62": "137,861"}, REAL_PRODUCTS)
    by_kind = {r["kind"]: r for r in out["records"]}

    assert by_kind["pension"]["balance"] == 338361.0
    assert by_kind["pension"]["label"] == "קרנות פנסיה"
    assert by_kind["pension"]["policies_count"] == 1

    assert by_kind["study_fund"]["balance"] == 137861.0
    assert by_kind["study_fund"]["policies_count"] == 5


def test_no_transactions_entity_is_emitted(tmp_path):
    """Savings must never reach the spending ledger."""
    _load_harel(tmp_path, {"70": "338,361"}, REAL_PRODUCTS)
    assert not (tmp_path / "normalized" / "transactions.json").exists()


def test_thousands_separated_strings_parse(tmp_path):
    """Harel returns money as strings like "338,361", not numbers."""
    out = _load_harel(tmp_path, {"70": "1,234,567", "62": 500}, REAL_PRODUCTS)
    balances = sorted(r["balance"] for r in out["records"])
    assert balances == [500.0, 1234567.0]


def test_unparseable_balance_is_skipped(tmp_path):
    """A junk value must not crash the run or emit a null-balance record."""
    out = _load_harel(tmp_path, {"70": "338,361", "62": "-"}, REAL_PRODUCTS)
    assert len(out["records"]) == 1
    assert out["records"][0]["balance"] == 338361.0


def test_savings_excluded_from_tracked_net_but_in_combined_total():
    """snapshot totals: tracked_net stays liquid-vs-debt; savings surface separately."""
    entities = {
        "accounts": [{"institution": "discount", "account_id": "1", "kind": "checking",
                      "balance": -679.80, "currency": "ILS"}],
        "credit_cards": [],
        "loans": [],
        "income": [],
        "savings": [
            {"institution": "harel", "kind": "pension", "label": "קרנות פנסיה",
             "balance": 338361.0, "currency": "ILS"},
            {"institution": "harel", "kind": "study_fund", "label": "השתלמות",
             "balance": 137861.0, "currency": "ILS"},
        ],
    }
    snap = digest.build_snapshot(entities)
    t = snap["totals"]

    assert t["long_term_savings"] == 476222.0
    assert t["tracked_net_position"] == -679.80, "savings must not inflate the liquid position"
    assert t["net_position_with_savings"] == round(-679.80 + 476222.0, 2)
