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
from pathlib import Path


def _txn(merchant, trn_amt, trn_cur, ils, payments=0, cur_payment=0, type_code="5",
         date="2026-09-29T13:23:12", refund=False):
    return {
        "trnIntId": f"{merchant}:{date}",
        "merchantName": merchant,
        "trnPurchaseDate": date,
        "debCrdDate": "2026-10-10T00:00:00",
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


def _normalize(tmp_path, txns):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "account_init.json").write_text(json.dumps({"result": {"cards": []}}))
    (raw / "cardTransactions_9947_0.json").write_text(json.dumps(
        {"result": {"bankAccounts": [{"debitDates": [{"transactions": txns}]}]}}))
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


def test_plain_shekel_rows_keep_trnamt(tmp_path):
    """Fee and refund rows carry amtBeforeConvAndIndex 0 / −5 — never use it for them."""
    out = _normalize(tmp_path, REAL)
    assert out["דמי כרטיס"]["amount"] == -19.9
    assert out["Gett"]["amount"] == 5
    assert out["WOLT"]["amount"] == -46
