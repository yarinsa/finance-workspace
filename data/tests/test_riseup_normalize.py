"""RiseUp normalize regression tests.

Bug (2026-08-01): as the household, when the month has just rolled over and
`budget_current.json` holds only 3 actuals, the normalized RiseUp ledger should
still carry the populated prior months from the multi-month budget dump — not
collapse to 3 transactions and leave 64% of the digest uncategorized.

RiseUp is the dedup-priority copy because it is the only source carrying a
spending category, so an empty RiseUp month silently de-categorizes the ledger.
"""
import importlib.util
from pathlib import Path

import pytest

NORMALIZE = Path(__file__).resolve().parents[1] / "riseup" / "normalize.py"


@pytest.fixture(scope="module")
def riseup():
    """Import riseup/normalize.py without executing its module-level scrape."""
    src = NORMALIZE.read_text(encoding="utf-8")
    # Keep only the pure helpers: everything before the accounts section runs I/O.
    head, _, _ = src.partition("# ---- accounts")
    body = head + _tail_of(src)
    mod = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("riseup_normalize", loader=None))
    mod.__dict__["__file__"] = str(NORMALIZE)
    exec(compile(body, str(NORMALIZE), "exec"), mod.__dict__)
    return mod


def _tail_of(src):
    """The _tx / collect_txns helpers, lifted out of the script body."""
    start = src.index("def _tx(")
    end = src.index("def load_budgets(")
    return "\n" + src[start:end]


def _actual(tid, date, amount, business, expense):
    return {
        "transactionId": tid,
        "source": "cal",
        "sourceType": "creditCard",
        "transactionDate": f"{date}T00:00:00",
        "billingAmount": amount,
        "businessName": business,
        "expense": expense,
    }


def test_current_month_alone_is_nearly_empty(riseup):
    """The real 2026-08-01 shape: budget_current has 64 envelopes but 3 actuals."""
    current = {
        "envelopes": [{"actuals": []} for _ in range(63)] + [
            {"actuals": [
                _actual("t1", "2026-08-02", 414.25, 'מטרו מוטור שיווק 1981 בע"', "תשלומים"),
                _actual("t2", "2026-08-02", 500, "מטרו מוטור שווק (1981)בעמ", "תשלומים"),
            ]}
        ],
        "excluded": [],
    }
    assert len(riseup.collect_txns([current])) == 2


def test_prior_months_are_included(riseup):
    """Regression: the populated July month must survive alongside an empty August."""
    july = {
        "envelopes": [{"actuals": [
            _actual("j1", "2026-07-03", 128.90, "שופרסל דיל", "מזון"),
            _actual("j2", "2026-07-11", 42.00, "פנגו", "רכב"),
        ]}],
        "excluded": [
            {"transactionId": "j3", "source": "leumi", "transactionDate": "2026-07-20",
             "billingAmount": 2000, "businessName": "העברה", "expense": ""},
        ],
    }
    august = {"envelopes": [{"actuals": [
        _actual("a1", "2026-08-02", 500, "מטרו מוטור שווק (1981)בעמ", "תשלומים"),
    ]}], "excluded": []}

    txns = riseup.collect_txns([july, august])

    assert len(txns) == 4, "July's transactions must not be dropped by an empty August"
    assert txns["j1"]["category"] == "מזון"
    assert txns["j3"]["excluded"] is True
    assert txns["a1"]["date"] == "2026-08-02"


def test_duplicate_ids_across_months_collapse(riseup):
    """The multi-month dumps overlap; transactionId dedupes, last month wins."""
    older = {"envelopes": [{"actuals": [
        _actual("dup", "2026-07-03", 100, "שופרסל דיל", "מזון")]}], "excluded": []}
    newer = {"envelopes": [{"actuals": [
        _actual("dup", "2026-07-03", 128.90, "שופרסל דיל", "מזון")]}], "excluded": []}

    txns = riseup.collect_txns([older, newer])

    assert len(txns) == 1
    assert txns["dup"]["amount"] == -128.90


def test_expense_is_negative_income_positive(riseup):
    """Money out negative, income positive — the repo-wide sign convention."""
    budget = {"envelopes": [{"actuals": [
        _actual("e1", "2026-07-03", 128.90, "שופרסל דיל", "מזון"),
        {"transactionId": "i1", "source": "leumi", "transactionDate": "2026-07-26",
         "incomeAmount": 400, "businessName": 'הו"ק מבללי אסף', "isIncome": True},
    ]}], "excluded": []}

    txns = riseup.collect_txns([budget])

    assert txns["e1"]["amount"] == -128.90
    assert txns["i1"]["amount"] == 400
    assert txns["i1"]["is_income"] is True
