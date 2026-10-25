"""CAL normalize tests — driven by the real 2026-10-16 CAL dump (issue #35).

As the household, when I pay ₪500 for installment 16 of 20 of "מטרו מוטור
שווק (1981)בעמ", or ₪303.96 for "PAYMOB*WARM SPA AND" charged as 5,100 EGP, the
ledger must record the ₪ that leaves the account. CAL's `trnAmt` is the
foreign-currency figure for FX purchases and the deal total for installments;
the ₪ charged this cycle is `amtBeforeConvAndIndex`. Before the fix the ledger
counted −10,000 and −5,100.
"""
import importlib.util
import json
import os
from pathlib import Path


def _txn(merchant, trn_amt, trn_cur, ils, payments=0, cur_payment=0, type_code="5",
         date="2026-09-29T13:23:12", refund=False, tid=None, billed_on="2026-10-10", comments=()):
    return {
        "trnIntId": tid or f"{merchant}:{date}",
        "merchantName": merchant,
        "trnPurchaseDate": date,
        "debCrdDate": f"{billed_on}T00:00:00",
        "comments": [{"key": c, "value": ""} for c in comments],
        "trnAmt": trn_amt,
        "trnCurrencySymbol": trn_cur,
        "amtBeforeConvAndIndex": ils,
        "debCrdCurrencySymbol": "₪",
        "numOfPayments": payments,
        "curPaymentNum": cur_payment,
        "trnTypeCode": type_code,
        "refundInd": refund,
    }


REAL = [
    _txn("מטרו מוטור שווק (1981)בעמ", 10000, "₪", 500, payments=20, cur_payment=16,
         type_code="8", date="2025-07-02T13:25:00"),
    _txn("ח.י אלקטרוניקה -טרקלין חש", 1846, "₪", 230.75, payments=8, cur_payment=1, type_code="8"),
    _txn("PAYMOB*WARM SPA AND", 5100, "EGP", 303.96, date="2026-09-27T00:16:49"),
    _txn("UNTITLEDrubber", 670.58, "$", 2047.41, date="2026-09-11T00:00:00"),
    _txn("Am Wriezener Bahnhof", 40, "€", 141.96, date="2026-09-10T23:58:25"),
    # ₪ rows where amtBeforeConvAndIndex is 0 / sign-flipped — trnAmt must stay.
    _txn("דמי כרטיס", 19.9, "₪", 0, type_code="72", date="2026-09-14T10:11:53"),
    _txn("Gett", 5, "₪", -5, type_code="6", date="2026-09-29T19:46:42", refund=True),
    _txn("WOLT", 46, "₪", 46, date="2026-10-12T12:00:00"),
]


def _body(txns):
    return {"result": {"bankAccounts": [{"debitDates": [{"transactions": txns}]}]}}


def _normalize(tmp_path, txns, files=None):
    """Run cal/normalize.py on one cycle file, or on `files` = [(name, txns, mtime)]."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "account_init.json").write_text(json.dumps({"result": {"cards": []}}))
    for name, rows, mtime in files or [("cardTransactions_9947_0.json", txns, None)]:
        fp = raw / name
        fp.write_text(json.dumps(_body(rows)))
        if mtime:
            os.utime(fp, (mtime, mtime))
    return _run(tmp_path)


def _records(tmp_path, txns=None, files=None):
    _normalize(tmp_path, txns, files)
    return json.loads((tmp_path / "normalized" / "transactions.json").read_text())["records"]


def _run(tmp_path):
    src = Path(__file__).resolve().parents[1] / "cal" / "normalize.py"
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("cal_normalize", loader=None))
    code = src.read_text().replace(
        'HERE = Path(__file__).resolve().parent', f'HERE = Path(r"{tmp_path}")')
    exec(compile(code, str(src), "exec"), mod.__dict__)
    recs = json.loads((tmp_path / "normalized" / "transactions.json").read_text())["records"]
    return {r["description"]: r for r in recs}


def test_installment_records_this_cycles_payment_not_deal_total(tmp_path):
    out = _normalize(tmp_path, REAL)
    assert out["מטרו מוטור שווק (1981)בעמ"]["amount"] == -500
    assert out["ח.י אלקטרוניקה -טרקלין חש"]["amount"] == -230.75


def test_foreign_purchase_records_shekels_not_original_currency(tmp_path):
    out = _normalize(tmp_path, REAL)
    assert out["PAYMOB*WARM SPA AND"]["amount"] == -303.96
    assert out["UNTITLEDrubber"]["amount"] == -2047.41
    assert out["Am Wriezener Bahnhof"]["amount"] == -141.96


def test_original_amount_and_currency_are_kept(tmp_path):
    out = _normalize(tmp_path, REAL)
    spa = out["PAYMOB*WARM SPA AND"]
    assert spa["original_amount"] == 5100 and spa["original_currency"] == "EGP"
    metro = out["מטרו מוטור שווק (1981)בעמ"]
    assert metro["original_amount"] == 10000 and metro["original_currency"] == "₪"
    assert spa["currency"] == "ILS"


def test_plain_shekel_rows_and_refunds(tmp_path):
    out = _normalize(tmp_path, REAL)
    assert out["Gett"]["amount"] == 5                 # refund: amtBeforeConvAndIndex -5 -> +5
    assert out["WOLT"]["amount"] == -46


# --- real rows of card 9947 that broke card_statements.cal (2026-10-25 dump) ---
# As the household, when CAL waives my ₪19.90 "דמי כרטיס" ("החודש עמדת ביעד המחזור
# לפטור מלא מעמלת דמי כרטיס ולכן לא חויבת") or accrues ₪49.32 "החזר CashPro" as
# BUY ME vouchers (צבירה למועדון), nothing is charged: amtBeforeConvAndIndex is 0
# and Σ amtBeforeConvAndIndex equals the statement total (₪7,393.89 for
# 2026-10-10). The ledger carried them as -19.90 / -49.32 charges.
FEE_WAIVED = _txn("דמי כרטיס", 19.9, "₪", 0, type_code="72", date="2026-09-14T10:11:53",
                  tid="32155084200", comments=["עסקה עם הנחה",
                  "החודש עמדת ביעד המחזור לפטור מלא מעמלת דמי כרטיס ולכן לא חויבת"])
CASHPRO = _txn("החזר CashPro", 49.32, "₪", 0, type_code="6", date="2026-09-30T00:00:00",
               tid="32284210199", comments=["BUY ME למימוש בשוברי"])


def test_waived_card_fee_and_loyalty_accrual_billed_zero_are_not_charges(tmp_path):
    out = _normalize(tmp_path, REAL + [CASHPRO])
    assert "דמי כרטיס" not in out and "החזר CashPro" not in out


# As the household, I pay installment 16/20 (₪500) of "מטרו מוטור שווק (1981)בעמ"
# on the 2026-10-10 bill and 17/20 on the 2026-11-10 bill. CAL repeats the deal's
# trnIntId 28674478000 in both cycles (cardTransactions_9947_1.json and the new
# open-cycle cardTransactions_9947_1_next.json), so keying on trnIntId kept only
# 17/20 and the October cycle lost ₪874.75 of installments (מטרו 500, ח.י
# אלקטרוניקה 230.75, מחסני חשמל-אילת 114, ליברה 30).
METRO_16 = _txn("מטרו מוטור שווק (1981)בעמ", 10000, "₪", 500, payments=20, cur_payment=16,
                type_code="8", date="2025-07-02T13:25:00", tid="28674478000")
METRO_17 = _txn("מטרו מוטור שווק (1981)בעמ", 10000, "₪", 500, payments=20, cur_payment=17,
                type_code="8", date="2025-07-02T13:25:00", tid="28674478000", billed_on="2026-11-10")
HI_1 = _txn("ח.י אלקטרוניקה -טרקלין חש", 1846, "₪", 230.75, payments=8, cur_payment=1,
            type_code="8", tid="32300000001")
HI_2 = _txn("ח.י אלקטרוניקה -טרקלין חש", 1846, "₪", 230.75, payments=8, cur_payment=2,
            type_code="8", tid="32300000001", billed_on="2026-11-10")


def test_each_installment_of_one_deal_is_its_own_record(tmp_path):
    recs = _records(tmp_path, files=[("cardTransactions_9947_1.json", [METRO_16, HI_1], None),
                                     ("cardTransactions_9947_1_next.json", [METRO_17, HI_2], None)])
    metro = sorted((r["billing_date"], r["amount"], r["id"]) for r in recs if r["description"].startswith("מטרו"))
    assert metro == [("2026-10-10", -500, "28674478000_16"), ("2026-11-10", -500, "28674478000_17")]
    assert len([r for r in recs if r["description"].startswith("ח.י")]) == 2


def test_installment_is_dated_by_payment_number_like_riseup(tmp_path):
    """RiseUp dates payment n at purchase + (n-1) months: מטרו 16/20 on 2026-10-02,
    ח.י 2/8 on 2026-10-29. Same-dated payments would collapse on the digest's
    (date, |amount|) key, so the dating also keeps them apart in the ledger."""
    import digest
    recs = _records(tmp_path, files=[("cardTransactions_9947_1.json", [METRO_16, HI_1], None),
                                     ("cardTransactions_9947_1_next.json", [METRO_17, HI_2], None)])
    dates = sorted((r["description"][:3], r["date"]) for r in recs)
    assert dates == [("ח.י", "2026-09-29"), ("ח.י", "2026-10-29"),
                     ("מטר", "2026-10-02"), ("מטר", "2026-11-02")]
    riseup = {"_source": "riseup", "origin": "cal", "date": "2026-10-29", "amount": -230.75,
              "description": "ח.י אלקטרוניקה -טרקלין חש", "category": "חשמל"}
    ledger = digest.consolidate_transactions([{**r, "_source": "cal"} for r in recs] + [riseup])
    assert len(ledger) == 4
    [oct29] = [r for r in ledger if r["date"] == "2026-10-29"]
    assert oct29["sources"] == ["cal", "riseup"]


def test_stale_card_index_file_does_not_override_the_fresh_pull(tmp_path):
    """CAL renumbered the cards (16 -> 17): card 5919 now dumps as _10, but the
    2026-10-16 cardTransactions_5919_9.json is still in raw/ and sorts AFTER
    _10 by name. The newest pull must win."""
    old = _txn("WOLT", 46, "₪", 46, date="2026-10-12T12:00:00", tid="1")
    new = _txn("WOLT", 46, "₪", 40, date="2026-10-12T12:00:00", tid="1")
    recs = _records(tmp_path, files=[("cardTransactions_5919_9.json", [old], 1_760_000_000),
                                     ("cardTransactions_5919_10.json", [new], 1_761_000_000)])
    assert [r["amount"] for r in recs] == [-40]
