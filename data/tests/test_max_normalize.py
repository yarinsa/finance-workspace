"""Max (ex-Leumi Card) normalize tests — driven by the real 2026-10-25 Max dump.

As the household, when Max bills ₪500 for payment 16 of 20 of "קרן הוכשטיין"
(a ₪10,000 deal from 2025-01-13), the ledger must show ₪500 leaving in April 2026,
not ₪10,000 and not in January 2025 — and payment 17 must be its own row, not
collapse onto payment 16 through the (date, abs amount) dedup key. A cancelled
WOLT order ("ביטול עסקה") is money back, and a ₪62.75 charge for 18 EUR is ₪62.75.

Every record below is copied from data/max/raw/transactions_2026-0{5,6,7,9}.json
(trimmed to the fields the normalizer reads).
"""
import importlib.util
import json
from datetime import date
from pathlib import Path

import digest
import validate

SRC = Path(__file__).resolve().parents[1] / "max" / "normalize.py"
_spec = importlib.util.spec_from_file_location("max_normalize", SRC)
max_normalize = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(max_normalize)


def _raw(card, merchant, purchase, payment, original, charged, plan="רגילה", plan_type=5,
         arn="", comments="", currency="ILS", category=7, user="ירין ששון"):
    return {
        "shortCardNumber": card, "merchantName": merchant,
        "purchaseDate": f"{purchase}T00:00:00",
        "paymentDate": f"{payment}T00:00:00" if payment else None,
        "originalAmount": original, "originalCurrency": currency,
        "actualPaymentAmount": charged, "paymentCurrency": 376,
        "planName": plan, "planTypeId": plan_type, "comments": comments,
        "categoryId": category, "arn": arn,
        "dealData": {"arn": arn, "userName": user},
    }


# --- real rows ----------------------------------------------------------------
GUREVICH = _raw("3819", "גורביץ מרק", "2026-04-14", "2026-05-10", 120, 120,
                arn="72302336106003000752377", category=19)
HOCHSTEIN_16 = _raw("3819", "קרן הוכשטיין", "2025-01-13", "2026-05-10", 10000, 500,
                    plan="תשלומים", plan_type=2, arn="05326105014005277131781",
                    comments="תשלום 16 מתוך 20", category=14)
HOCHSTEIN_17 = {**HOCHSTEIN_16, "paymentDate": "2026-06-10T00:00:00", "comments": "תשלום 17 מתוך 20"}
WOLT_CANCEL = _raw("5714", "WOLT", "2026-08-31", "2026-09-10", 10.21, -10.21,
                   arn="74580006244320448476133", comments="ביטול עסקה", category=20)
OASA_EUR = _raw("3819", "OASA ETICKET POS       SPATA         GRC", "2026-06-05", "2026-06-11",
                18, 62.75, plan="חיוב עסקות מיידי", arn="77673706156593643627401",
                currency="EUR", category=10)
APPLE_ILS_ABROAD = _raw("3819", "APPLE.COM/BILL         CORK          IRL", "2026-04-13",
                        "2026-04-15", 39.9, 39.9, plan="חיוב עסקות מיידי",
                        arn="55204716103204538865786", comments='חיוב עסקת חו"ל בש"ח ', category=9)
# A double charge at the greengrocer, credited back while under inquiry (arn "0"),
# then repeated at ₪0 in every later month's file.
GREENGROCER_CREDIT = _raw("3819", "מסחר פירות וירקות", "2026-05-21", "2026-06-10", 136, -136,
                          arn="0", comments="עסקה בבירור")
GREENGROCER_ZERO = {**GREENGROCER_CREDIT, "paymentDate": "2026-07-10T00:00:00", "actualPaymentAmount": 0}
SUMMARY_ROW = {**GUREVICH, "planName": None, "arn": "x", "dealData": {"arn": "x"}}

CATEGORIES = [{"id": 7, "name": "מזון וצריכה"}, {"id": 9, "name": "פנאי, בידור וספורט"},
              {"id": 10, "name": "תחבורה ורכבים"}, {"id": 14, "name": "שונות"},
              {"id": 19, "name": "קוסמטיקה וטיפוח"}, {"id": 20, "name": "מסעדות, קפה וברים"}]


def _write(raw, months):
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "categories.json").write_text(json.dumps({"result": CATEGORIES}, ensure_ascii=False))
    for ym, txns in months.items():
        (raw / f"transactions_{ym}.json").write_text(json.dumps(
            {"result": {"transactions": txns}, "returnCode": 0, "rcDesc": None}, ensure_ascii=False))
    return raw


def _normalize(tmp_path, months):
    cards, txns = max_normalize.normalize(_write(tmp_path / "raw", months))
    return cards, txns


def test_regular_purchase_is_negative_ils_on_its_purchase_date(tmp_path):
    _, [t] = _normalize(tmp_path, {"2026-05": [GUREVICH]})
    assert t["amount"] == -120
    assert t["date"] == "2026-04-14" and t["billing_date"] == "2026-05-10"
    assert t["id"] == "72302336106003000752377"
    assert t["description"] == "גורביץ מרק" and t["card_last4"] == "3819"
    assert t["category"] == "קוסמטיקה וטיפוח" and t["is_abroad"] is False


def test_installment_is_this_cycles_payment_dated_by_payment_number(tmp_path):
    _, txns = _normalize(tmp_path, {"2026-05": [HOCHSTEIN_16], "2026-06": [HOCHSTEIN_17]})
    p16, p17 = txns
    assert (p16["amount"], p17["amount"]) == (-500, -500)          # not the ₪10,000 deal
    assert (p16["date"], p17["date"]) == ("2026-04-13", "2026-05-13")  # 2025-01-13 + 15/16 months
    assert (p16["id"], p17["id"]) == ("05326105014005277131781_16", "05326105014005277131781_17")
    assert p16["installments"] == 20 and p16["original_amount"] == 10000


def test_installments_stay_two_ledger_rows_and_match_riseups_dating(tmp_path):
    _, txns = _normalize(tmp_path, {"2026-05": [HOCHSTEIN_16], "2026-06": [HOCHSTEIN_17]})
    riseup = {"_source": "riseup", "origin": "leumicard", "date": "2026-05-13", "amount": -500.0,
              "description": "קרן הוכשטיין", "category": "שונות"}
    ledger = digest.consolidate_transactions([{**t, "_source": "max"} for t in txns] + [riseup])
    assert len(ledger) == 2
    [may] = [r for r in ledger if r["date"] == "2026-05-13"]
    assert may["sources"] == ["max", "riseup"] and may["origin"] == "max"


def test_cancellation_is_a_positive_refund(tmp_path):
    _, [t] = _normalize(tmp_path, {"2026-09": [WOLT_CANCEL]})
    assert t["amount"] == 10.21 and t["date"] == "2026-08-31"


def test_foreign_currency_charge_uses_the_ils_billed(tmp_path):
    _, txns = _normalize(tmp_path, {"2026-07": [OASA_EUR], "2026-05": [APPLE_ILS_ABROAD]})
    eur = next(t for t in txns if t["original_currency"] == "EUR")
    assert eur["amount"] == -62.75 and eur["original_amount"] == 18 and eur["is_abroad"] is True
    apple = next(t for t in txns if t["description"].startswith("APPLE"))
    assert apple["amount"] == -39.9 and apple["is_abroad"] is True   # foreign merchant billed in ₪


def test_inquiry_credit_kept_and_zero_repeats_and_summary_rows_dropped(tmp_path):
    _, txns = _normalize(tmp_path, {"2026-06": [GREENGROCER_CREDIT, SUMMARY_ROW],
                                    "2026-07": [GREENGROCER_ZERO], "2026-08": [GREENGROCER_ZERO]})
    [t] = txns
    assert t["amount"] == 136 and t["date"] == "2026-05-21"
    assert t["id"] == "3819:2026-05-21:2026-06-10:-136:מסחר פירות וירקות"


def test_same_row_in_two_monthly_files_is_one_record_with_a_stable_id(tmp_path):
    months = {"2026-05": [GUREVICH, HOCHSTEIN_16], "2026-06": [GUREVICH, HOCHSTEIN_16, HOCHSTEIN_17]}
    _, first = _normalize(tmp_path, months)
    _, again = _normalize(tmp_path, months)
    assert [t["id"] for t in first] == [t["id"] for t in again]
    assert sorted(t["id"] for t in first) == ["05326105014005277131781_16",
                                              "05326105014005277131781_17",
                                              "72302336106003000752377"]


def test_roster_comes_from_the_transactions(tmp_path):
    cards, _ = _normalize(tmp_path, {"2026-05": [GUREVICH, WOLT_CANCEL], "2026-06": [], "2026-07": [],
                                     "2026-08": [OASA_EUR]})
    by = {c["last4"]: c for c in cards}
    assert set(by) == {"3819", "5714"}
    assert by["3819"]["active"] is True and by["5714"]["active"] is False   # not in the newest 3
    assert by["3819"]["issuer"] == "max" and by["3819"]["holder"] == "ירין ששון"
    assert "owed" not in by["3819"]                                          # roster, not debt


def test_riseup_leumicard_is_max_not_cal():
    """RiseUp's `leumicard` rows are cards 3819/9613 — the Max cards — not CAL."""
    assert digest.RISEUP_ORIGIN["leumicard"] == "max"


# --- validate.py dump check ---------------------------------------------------
AS_OF = date(2026, 10, 25)


def test_dump_max_ok_and_future_installment_does_not_hide_a_stale_dump(tmp_path):
    raw = _write(tmp_path / "max" / "raw", {"2026-10": [GUREVICH], "2026-11": [HOCHSTEIN_17]})
    (raw / "categories.json").write_text(json.dumps({"result": CATEGORIES * 4}, ensure_ascii=False))
    fresh = [{"date": "2026-10-18", "amount": -240}, {"date": "2026-11-02", "amount": -414.25}]
    assert validate.check_dump("max", tmp_path, AS_OF, new={"transactions": fresh})["status"] == "pass"
    stale = [{"date": "2026-09-01", "amount": -33}, {"date": "2026-11-02", "amount": -414.25}]
    res = validate.check_dump("max", tmp_path, AS_OF, new={"transactions": stale})
    assert res["status"] == "fail" and "2026-09-01" in res["summary"]


def test_dump_max_rejects_error_pull_and_missing_current_month(tmp_path):
    raw = _write(tmp_path / "max" / "raw", {"2026-09": [GUREVICH]})
    (raw / "categories.json").write_text(json.dumps({"result": CATEGORIES * 4}, ensure_ascii=False))
    (raw / "transactions_2026-10.json").write_text(json.dumps(
        {"result": None, "returnCode": 1, "rcDesc": "session expired"}))
    res = validate.check_dump("max", tmp_path, AS_OF, dry_run=False)
    assert res["status"] == "fail" and "transactions_2026-10.json" in res["summary"]
    (raw / "transactions_2026-10.json").unlink()
    res = validate.check_dump("max", tmp_path, AS_OF, dry_run=False)
    assert res["status"] == "fail" and "current billing month" in res["summary"]
