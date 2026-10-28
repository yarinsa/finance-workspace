"""AMEX normalize tests — driven by the real 2026-10-25 AMEX dump of card 7696.

As the household, when I withdraw ₪700 cash on 2026-10-01 ("משיכת מזומנים",
billed immediately on 04/10, outside the statement), get a ₪159.16 tax-free
refund from "GLOBAL BLUE HELLAS SA 608", or repay ₪948.53 of "פרעון העברות
לקרדיט" on 2026-08-09, the AMEX ledger must carry it. AMEX lists those vouchers
under `outOfStatementChargeDateVouchers`, not in the statement list, and the old
normalizer read only the statement list — 29 vouchers never reached the ledger
(validator: card_statements.amex).
"""
import importlib.util
import json
from pathlib import Path

import validate


def _voucher(date, name, billing, seq, israel=True, desc="עסקאות רגילות", **kw):
    return {"purchaseDate": date, "businessName": name, "billingAmount": billing, "ilsAmount": billing,
            "originalAmount": billing, "originalCurrencyIso": "ILS", "isIsraelDeal": israel,
            "transactionDescription": desc, "seqVoucherNumber": seq, **kw}


# statement voucher of 10-2026 (in israelAbroadVouchersList)
KING = _voucher("06/09/2026", 'קינג אקספרס בע"מ', 558.06, "071400853")
# immediate vouchers, each with its own immediate billing date
CASH = _voucher("01/10/2026", "משיכת מזומנים", 700, "232489530", desc="משיכת מזומן בארץ")
GLOBAL_BLUE = _voucher("10/06/2026", "GLOBAL BLUE HELLAS SA 608", -159.16, "GB1", israel=False,
                       desc="תיירות יוצאת קניות", originalAmount=-53.68, originalCurrencyIso="USD")
REPAY = _voucher("09/08/2026", "פרעון העברות לקרדיט", 948.53, "RP1")


def _month(statement, immediate, total):
    return {"data": {"israelAbroadVouchers": {
        "vouchers": {"israelAbroadVouchersList": statement,
                     "totalForStatement": {"totalIlsBillingDate": total}},
        "outOfStatementChargeDateVouchers": [
            {"immediateVouchersCurrencyDate": [v],
             "totalVouchersCurrencyDate": {"totalImmediateVouchers": v["billingAmount"],
                                           "dateImmediateVouchers": when}}
            for v, when in immediate]}}}


def _normalize(tmp_path, months):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "cardList.json").write_text(json.dumps({"data": {"cardsList": [
        {"cardSuffix": "7696", "cardName": "אמריקן אקספרס", "isActive": True}]}}))
    for name, body in months.items():
        (raw / name).write_text(json.dumps(body, ensure_ascii=False))
    src = Path(__file__).resolve().parents[1] / "amex" / "normalize.py"
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("amex_normalize", loader=None))
    code = src.read_text().replace(
        'HERE = Path(__file__).resolve().parent', f'HERE = Path(r"{tmp_path}")')
    exec(compile(code, str(src), "exec"), mod.__dict__)
    return json.loads((tmp_path / "normalized" / "transactions.json").read_text())["records"]


MONTHS = {
    "transactions_7696_07-2026.json": _month([], [(GLOBAL_BLUE, "12/06/2026")], 0),
    "transactions_7696_09-2026.json": _month([], [(REPAY, "14/08/2026")], 0),
    "transactions_7696_10-2026.json": _month([KING], [(CASH, "04/10/2026")], 558.06),
}


def test_immediate_vouchers_reach_the_ledger(tmp_path):
    recs = {r["description"]: r for r in _normalize(tmp_path, MONTHS)}
    assert recs["משיכת מזומנים"]["amount"] == -700 and recs["משיכת מזומנים"]["date"] == "2026-10-01"
    assert recs["משיכת מזומנים"]["billing_date"] == "2026-10-04"
    assert recs["GLOBAL BLUE HELLAS SA 608"]["amount"] == 159.16          # a credit stays positive
    assert recs["GLOBAL BLUE HELLAS SA 608"]["is_abroad"] is True
    assert recs["פרעון העברות לקרדיט"]["amount"] == -948.53
    assert recs['קינג אקספרס בע"מ']["amount"] == -558.06


def test_validator_finds_every_raw_voucher_in_the_normalized_ledger(tmp_path):
    recs = _normalize(tmp_path, MONTHS)
    files = [(Path(n), b) for n, b in MONTHS.items()]
    res = validate.check_amex_statements(validate.amex_months(files, {"7696": 10}), recs)
    assert res["status"] == "pass", res["details"]


def test_immediate_voucher_repeated_in_two_pulls_is_one_record(tmp_path):
    months = {**MONTHS, "transactions_7696_11-2026.json": _month([], [(CASH, "04/10/2026")], 0)}
    recs = _normalize(tmp_path, months)
    assert [r["description"] for r in recs].count("משיכת מזומנים") == 1


def test_statement_vouchers_carry_the_cards_charge_date(tmp_path):
    """As the household, when AMEX says card 7696 is next charged ₪4,506.30 on 10/11/2026 (it bills
    on the 10th), the vouchers of the 11-2026 statement must be dated 2026-11-10, so the snapshot can
    say what each card will charge. Before this, only immediate vouchers had a billing_date."""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "cardList.json").write_text(json.dumps({"data": {"cardsList": [
        {"cardSuffix": "7696", "cardName": "AMEX PLATINUM", "isActive": True,
         "cardChargeNext": {"billingDate": "10/11/2026", "billingSumSekel": "4506.30"},
         "cardChargeLast": {"billingDate": "10/10/2026", "billingSumSekel": "8339.89"}},
        {"cardSuffix": "6417", "cardName": "AMEX PLATINUM", "isActive": True,
         "cardChargeNext": {"billingDate": "02/11/2026", "billingSumSekel": "973.47"}}]}}))
    for name, v in {"transactions_7696_10-2026.json": KING, "transactions_7696_11-2026.json":
                    _voucher("22/10/2026", "פז", 4506.30, "V11"),
                    "transactions_6417_11-2026.json": _voucher("20/10/2026", "הוט", 973.47, "V6417")}.items():
        (raw / name).write_text(json.dumps(_month([v], [], v["billingAmount"]), ensure_ascii=False))
    src = Path(__file__).resolve().parents[1] / "amex" / "normalize.py"
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("amex_normalize", loader=None))
    exec(compile(src.read_text().replace('HERE = Path(__file__).resolve().parent', f'HERE = Path(r"{tmp_path}")'),
                 str(src), "exec"), mod.__dict__)
    recs = json.loads((tmp_path / "normalized" / "transactions.json").read_text())["records"]
    by = {r["id"]: r["billing_date"] for r in recs}
    assert by["071400853"] == "2026-10-10"      # the 10-2026 statement of 7696
    assert by["V11"] == "2026-11-10"
    assert by["V6417"] == "2026-11-02"          # a card billed on the 2nd
