"""Leumi loan normalize tests — driven by the real 2026-09-04 scrape.

As the household, when Leumi's loan-summary reports loan 2529-1/3 ("ריבית
הצטרפות ‎2529-1/3‎", 8% rate, next payment 1,844.42) and loan 6673-1/4
("מילואים", 2% rate, next payment 867.80), the normalizer must emit ONE
RECORD PER LOAN with real rate_pct/monthly_payment — not a single zeroed-out
aggregate. Before this fix, snapshot.json's monthly_loan_service undercounted
by ~2,600 ILS/month because these two loans were collapsed into one record
with rate_pct=null and monthly_payment=0.
"""
import importlib.util
import json
from pathlib import Path

import pytest

import digest


REAL_LOANS = {
    "source": "hb2.bankleumi.co.il - LoanAndMortgages",
    "capturedAt": "2026-09-04T14:14:56.296Z",
    "loans": [
        {
            "index": 3,
            "loanLabel": " ללא ריבית הצטרפות  ‎2529-1/3‎",
            "generalInfo": {
                "נכון לתאריך": "03/09/26",
                "סוג": "מט\"י ז\"א לא צמוד ר.קבועה",
                "חשבון": "806-6719/63",
                "מספר הלוואה": "25290013",
                "מטבע": "₪",
                "מטרת הלוואה": "הל. לכל מטרה",
            },
            "balances": {
                "תשלומים שנותרו": "27",
                "סכום הלוואה מקורי": "50,000.00",
                "יתרת קרן": "45,436.45",
                "סכום הלוואה משוערך בש\"ח": "45,446.55",
                "סכום התשלום הבא": "1,844.42",
            },
            "interest": {
                "סוג הצמדה": "לא צמוד",
                "שיעור ריבית": "8%",
            },
            "dates": {
                "תאריך העמדת הלוואה": "02/06/26",
                "תאריך סיום": "02/12/28",
                "תאריך התשלום הבא": "02/10/26",
            },
            "installmentCount": 27,
            "installments": [],
        },
        {
            "index": 4,
            "loanLabel": " מילואים  ‎6673-1/4‎",
            "generalInfo": {
                "נכון לתאריך": "03/09/26",
                "סוג": "מט\"י ז\"א לא צמוד ר.קבועה",
                "חשבון": "806-6719/63",
                "מספר הלוואה": "66730014",
                "מטבע": "₪",
                "מטרת הלוואה": "הל. לכל מטרה",
            },
            "balances": {
                "תשלומים שנותרו": "38",
                "סכום הלוואה מקורי": "40,000.00",
                "יתרת קרן": "31,928.30",
                "סכום הלוואה משוערך בש\"ח": "31,979.74",
                "סכום התשלום הבא": "867.80",
            },
            "interest": {
                "סוג הצמדה": "לא צמוד",
                "שיעור ריבית": "2%",
            },
            "dates": {
                "תאריך העמדת הלוואה": "28/10/25",
                "תאריך סיום": "04/10/29",
                "תאריך התשלום הבא": "04/09/26",
            },
            "installmentCount": 38,
            "installments": [],
        },
    ],
}


def _load_leumi_loans(tmp_path, loans_payload):
    """Execute data/leumi/normalize.py against a temp raw/ dir, loans path only.

    Other raw files (accounts.json, summary.json, transactions.json) are
    left absent — normalize.py must tolerate that (self-contained/idempotent).
    """
    src = Path(digest.__file__).resolve().parent / "leumi" / "normalize.py"
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "loans.json").write_text(json.dumps(loans_payload, ensure_ascii=False),
                                     encoding="utf-8")

    mod = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("leumi_normalize", loader=None))
    code = src.read_text(encoding="utf-8").replace(
        'HERE = Path(__file__).resolve().parent', f'HERE = Path(r"{tmp_path}")')
    mod.__dict__["__file__"] = str(src)
    exec(compile(code, str(src), "exec"), mod.__dict__)
    return json.loads((tmp_path / "normalized" / "loans.json").read_text())


def test_real_loans_emit_one_record_each(tmp_path):
    """Two Leumi loans on disk -> two loan records, not one aggregate."""
    out = _load_leumi_loans(tmp_path, REAL_LOANS)
    assert len(out["records"]) == 2

    by_id = {r["loan_id"]: r for r in out["records"]}
    assert set(by_id) == {"25290013", "66730014"}

    joining = by_id["25290013"]
    assert joining["rate_pct"] == 8.0
    assert joining["monthly_payment"] == 1844.42
    assert joining["balance"] == 45436.45
    assert joining["original_amount"] == 50000.0
    assert joining["payments_remaining"] == 27
    assert joining["lender"] == "Bank Leumi"
    assert joining["category"] == "consumer"
    assert joining["final_date"] == "2028-12-02"

    miluim = by_id["66730014"]
    assert miluim["rate_pct"] == 2.0
    assert miluim["monthly_payment"] == 867.80
    assert miluim["balance"] == 31928.30
    assert miluim["payments_remaining"] == 38


def test_combined_monthly_payment_matches_real_total(tmp_path):
    """Sum of the two real loans' monthly payments is ~2,712 ILS/month."""
    out = _load_leumi_loans(tmp_path, REAL_LOANS)
    total = round(sum(r["monthly_payment"] for r in out["records"]), 2)
    assert total == 2712.22


def test_missing_loans_file_does_not_crash(tmp_path):
    """No raw/loans.json on disk (e.g. before first scrape) -> empty, no crash."""
    src = Path(digest.__file__).resolve().parent / "leumi" / "normalize.py"
    raw = tmp_path / "raw"
    raw.mkdir()

    mod = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("leumi_normalize", loader=None))
    code = src.read_text(encoding="utf-8").replace(
        'HERE = Path(__file__).resolve().parent', f'HERE = Path(r"{tmp_path}")')
    mod.__dict__["__file__"] = str(src)
    exec(compile(code, str(src), "exec"), mod.__dict__)

    out = json.loads((tmp_path / "normalized" / "loans.json").read_text())
    assert out["records"] == []


def test_monthly_loan_service_picks_up_per_loan_payments():
    """digest.py's monthly_loan_service must sum real per-loan monthly_payment
    values regardless of source, confirming Leumi's per-loan records feed it."""
    loans = [
        {"lender": "Bank Discount", "loan_id": "d1", "monthly_payment": 500.0,
         "payments_remaining": 10, "balance": 1000.0, "category": "consumer"},
        {"lender": "Bank Leumi", "loan_id": "25290013", "monthly_payment": 1844.42,
         "payments_remaining": 27, "balance": 45436.45, "category": "consumer"},
        {"lender": "Bank Leumi", "loan_id": "66730014", "monthly_payment": 867.80,
         "payments_remaining": 38, "balance": 31928.30, "category": "consumer"},
    ]
    entities = {
        "accounts": [], "credit_cards": [], "income": [], "savings": [],
        "loans": loans,
    }
    snap = digest.build_snapshot(entities)
    assert snap["totals"]["monthly_loan_service"] == 3212.22


# As the household, when the 2026-10-27 Leumi scrape saved loan 2529-1/3 twice
# (index 3 and index 4 both rendered 25290013, balance 43,894.94) while Leumi's
# summary says the loans total 74,463.85, the snapshot must show 74,463.85 of
# Leumi debt — not 87,789.88 (the same loan counted twice, the מילואים loan lost).
DUPLICATED_2529 = {
    "source": "hb2.bankleumi.co.il - LoanAndMortgages",
    "capturedAt": "2026-10-27T04:20:53.358Z",
    "loans": [
        {**REAL_LOANS["loans"][0], "index": i,
         "generalInfo": {**REAL_LOANS["loans"][0]["generalInfo"], "נכון לתאריך": "26/10/26"},
         "balances": {"תשלומים שנותרו": "26", "סכום הלוואה מקורי": "50,000.00",
                      "יתרת קרן": "43,894.94", "סכום הלוואה משוערך בש\"ח": "44,129.05",
                      "סכום התשלום הבא": "1,844.42"},
         "installmentCount": 0}
        for i in (3, 4)
    ],
}
SUMMARY_2026_10_26 = {"TotalPerTypeItems": [
    {"accountType": "CHECKING", "totalPerAccountType": 2413.94},
    {"accountType": "CREDITCARD", "totalPerAccountType": -599.06},
    {"accountType": "LOAN", "totalPerAccountType": -74463.85},
]}


def test_duplicated_loan_page_counts_once_and_the_rest_comes_from_the_summary(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "summary.json").write_text(json.dumps(SUMMARY_2026_10_26), encoding="utf-8")
    out = _load_leumi_loans_with_raw(tmp_path, DUPLICATED_2529)
    ids = [r["loan_id"] for r in out["records"]]
    assert ids.count("25290013") == 1
    assert round(sum(r["balance"] for r in out["records"]), 2) == 74463.85
    rest = next(r for r in out["records"] if r["loan_id"] != "25290013")
    assert rest["balance"] == 30568.91
    assert rest["monthly_payment"] == 0          # unknown until the page is scraped again


def _load_leumi_loans_with_raw(tmp_path, loans_payload):
    """Like _load_leumi_loans, but keeps whatever else is already in tmp_path/raw."""
    src = Path(digest.__file__).resolve().parent / "leumi" / "normalize.py"
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    (raw / "loans.json").write_text(json.dumps(loans_payload, ensure_ascii=False), encoding="utf-8")
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("leumi_normalize", loader=None))
    code = src.read_text(encoding="utf-8").replace(
        'HERE = Path(__file__).resolve().parent', f'HERE = Path(r"{tmp_path}")')
    mod.__dict__["__file__"] = str(src)
    exec(compile(code, str(src), "exec"), mod.__dict__)
    return json.loads((tmp_path / "normalized" / "loans.json").read_text())
