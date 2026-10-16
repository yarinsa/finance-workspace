"""Real-case tests for validate.py — the data-validation pipeline.

Every fixture is a real record from the 2026-10-16 scrape (Hebrew descriptions,
amounts and dates as the banks returned them), inlined so the suite needs none of
the gitignored data. Each check has a passing case and a failing case taken from
reality — including the findings the validator surfaced on its first run
(Leumi FITID collisions, CAL trnAmt, AMEX immediate vouchers, the Discount hole).
"""
import json
from datetime import date
from pathlib import Path

import validate

AS_OF = date(2026, 10, 16)


def bank(origin, d, amount, desc, **kw):
    """A bank-side ledger row as validate.Dataset.bank_rows() yields it."""
    return {"date": d, "amount": amount, "description": desc, "origin": origin,
            "source": origin, "_source": origin, "_date": date.fromisoformat(d), **kw}


def ctx(rows):
    return validate.bank_context(rows)


# --- business-day helpers ------------------------------------------------------

def test_saturday_billing_settles_sunday_zero_banking_days():
    # CAL's cycle closes Sat 2026-10-10; Discount debited Sun 2026-10-11.
    assert validate.business_days_between(date(2026, 10, 10), date(2026, 10, 11)) == 0


def test_thursday_to_sunday_is_one_banking_day():
    assert validate.business_days_between(date(2026, 10, 8), date(2026, 10, 11)) == 1
    assert validate.business_days_between(date(2026, 10, 11), date(2026, 10, 15)) == 4


# =============================================================================
# 1. Dump sanity
# =============================================================================

TELEBANK_NO_DEPOSITS = {"Error": {"MsgText": "לא נמצאו הפקדות פעילות", "ReturnedCode": "RET011039",
                                  "SeverityCode": "WARNING", "GeneratedCode": "588688"}}
CAL_NO_LOANS = {"result": None, "statusDescription": None, "statusTitle": "אין ללקוח הלוואות",
                "statusCode": 468, "groupPid": "9b26cef3-3d3b-4dfd-9d68-32bcf8c702b5"}
AMEX_NO_DATA = {"data": None, "errorCode": "22", "errorDescription": "", "isSuccess": False}
DISCOUNT_INFO = {"AccountInfoAndBalance": {
    "AccountName": "ששון ירין", "HandlingBranchID": "0034", "HandlingBranchName": "סניף אלון",
    "AccountBalance": -5831.15, "AccountWithheldBalance": 0, "AccountAvailableBalance": 4168.85,
    "AccountAutomaticAuthorizedOverdraft": 0, "AccountLimit": 10000, "TotalAccountLimit": 10000,
    "AccountStatusCode": "A", "AccountCurrencyCode": "ILS", "PrivateBusinessFlag": "P"}}
DISCOUNT_TX = {"CurrentAccountLastTransactions": {
    "LastTransactionsOrder": "DESC", "CurrentAccountInfo": {"AccountBalance": -5831.15},
    "OperationEntry": [{
        "OperationDate": "20261013", "ValueDate": "20261014", "OperationCode": "C70",
        "OperationDescription": "משיכת מזומן ללא כרטיס", "OperationAmount": -700,
        "BalanceAfterOperation": -5831.15, "OperationNumber": 4197,
        "OperationDescriptionToDisplay": "משיכת מזומן ללא כרטיס"}]}}


def write_discount(root, info=DISCOUNT_INFO, tx=DISCOUNT_TX):
    raw = root / "discount" / "raw"
    raw.mkdir(parents=True)
    (raw / "infoAndBalance.json").write_text(json.dumps(info, ensure_ascii=False))
    (raw / "transactions.json").write_text(json.dumps(tx, ensure_ascii=False))


def write_prev(root, source, entity, records):
    d = root / source / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{entity}.json").write_text(json.dumps(
        {"source": source, "entity": entity, "records": records}, ensure_ascii=False))


def txns(n, last="2026-10-13"):
    return [{"date": "2026-08-01", "amount": -10, "description": "x"}] * (n - 1) + \
           [{"date": last, "amount": -700, "description": "משיכת מזומן ללא כרטיס"}]


def test_error_envelopes_are_recognised_per_institution():
    assert "Error envelope" in validate.error_reason(TELEBANK_NO_DEPOSITS)
    assert "statusCode 468" in validate.error_reason(CAL_NO_LOANS)
    assert "errorCode 22" in validate.error_reason(AMEX_NO_DATA)
    assert validate.error_reason({"ProcessRequestResult": 0, "jsonResp": {}}) == "empty jsonResp"
    assert validate.error_reason(DISCOUNT_INFO) is None


def test_healthy_dump_passes_and_stub_is_rejected(tmp_path):
    write_discount(tmp_path)
    assert validate.check_raw_file(tmp_path / "discount/raw/infoAndBalance.json") is None
    stub = tmp_path / "stub.json"
    stub.write_text(json.dumps(TELEBANK_NO_DEPOSITS, ensure_ascii=False))
    assert validate.check_raw_file(stub).startswith("error stub")


def test_empty_missing_unparseable_and_tiny_dumps(tmp_path):
    (tmp_path / "empty.json").write_text("")
    (tmp_path / "html.json").write_text("<html>Session expired</html>" * 20)
    (tmp_path / "tiny.json").write_text('{"AccountBalance": -5831.15}')
    assert validate.check_raw_file(tmp_path / "empty.json") == "empty file"
    assert validate.check_raw_file(tmp_path / "html.json").startswith("not valid JSON")
    assert validate.check_raw_file(tmp_path / "tiny.json").startswith("suspiciously small")
    assert validate.check_raw_file(tmp_path / "nope.json") == "missing"


def test_dump_ok(tmp_path):
    write_discount(tmp_path)
    write_prev(tmp_path, "discount", "transactions", txns(321))
    res = validate.check_dump("discount", tmp_path, AS_OF, new={"transactions": txns(325)})
    assert res["status"] == "pass"


def test_dump_rejects_error_stub_served_with_http_200(tmp_path):
    # a half-authenticated scrape: the required file is an error body
    write_discount(tmp_path, tx=TELEBANK_NO_DEPOSITS)
    res = validate.check_dump("discount", tmp_path, AS_OF, dry_run=False)
    assert res["status"] == "fail"
    assert any("transactions.json" in d["reason"] and "error stub" in d["reason"] for d in res["details"])


def test_dump_rejects_missing_required_file(tmp_path):
    write_discount(tmp_path)
    (tmp_path / "discount/raw/infoAndBalance.json").unlink()
    res = validate.check_dump("discount", tmp_path, AS_OF, dry_run=False)
    assert res["status"] == "fail"
    assert any("infoAndBalance.json: missing" in d["reason"] for d in res["details"])


def test_dump_rejects_record_count_drop_over_20_percent(tmp_path):
    # discount normalized 321 transactions last time; a truncated pull yields 200
    write_discount(tmp_path)
    write_prev(tmp_path, "discount", "transactions", txns(321))
    res = validate.check_dump("discount", tmp_path, AS_OF, new={"transactions": txns(200)})
    assert res["status"] == "fail"
    assert any("321 -> 200" in d["reason"] for d in res["details"])
    # a 10% dip is tolerated
    ok = validate.check_dump("discount", tmp_path, AS_OF, new={"transactions": txns(290)})
    assert ok["status"] == "pass"


def test_cal_count_collapse_on_new_billing_cycle_is_only_a_warning(tmp_path):
    # CAL pulls ONE cycle: 49 purchases billed 2026-10-10, then the next cycle opens
    prev = [{"date": "2026-10-08", "billing_date": "2026-10-10", "amount": -101}] * 49
    new = [{"date": "2026-10-14", "billing_date": "2026-11-10", "amount": -70}] * 3
    raw = tmp_path / "cal" / "raw"
    raw.mkdir(parents=True)
    (raw / "account_init.json").write_text(json.dumps({"result": {"cards": []}, "pad": "x" * 300}))
    (raw / "monthlyDebitsSummary.json").write_text(json.dumps(
        {"result": {"bankAccounts": []}, "statusCode": 1, "pad": "x" * 300}))
    write_prev(tmp_path, "cal", "transactions", prev)
    res = validate.check_dump("cal", tmp_path, date(2026, 10, 16), new={"transactions": new})
    assert res["status"] == "warn"
    assert "new billing cycle" in res["details"][0]["reason"]


def test_dump_rejects_stale_latest_transaction(tmp_path):
    write_discount(tmp_path)
    stale = txns(30, last="2026-09-01")
    write_prev(tmp_path, "discount", "transactions", stale)
    res = validate.check_dump("discount", tmp_path, AS_OF, new={"transactions": stale})
    assert res["status"] == "fail"
    assert any("45 days old" in d["reason"] for d in res["details"])


def test_amex_inactive_cards_answer_errorCode_22_but_active_card_must_have_a_pull(tmp_path):
    raw = tmp_path / "amex" / "raw"
    raw.mkdir(parents=True)
    cards = [{"cardSuffix": "7696", "cardName": "AMEX PLATINUM", "isActive": True, "isBlock": False},
             {"cardSuffix": "8146", "cardName": "AMEX FLY CARD", "isActive": False, "isBlock": True}]
    (raw / "cardList.json").write_text(json.dumps(
        {"data": {"cardsList": cards, "billingSumSekel": "2347.35", "pad": "x" * 300},
         "errorCode": "0", "isSuccess": True}))
    (raw / "transactions_8146_10-2026.json").write_text(json.dumps(AMEX_NO_DATA))
    findings = validate.raw_findings("amex", raw, AS_OF)
    assert [lvl for lvl, _ in findings] == ["fail"]
    assert "active card 7696" in findings[0][1]
    (raw / "transactions_7696_10-2026.json").write_text(json.dumps({"data": {"x": 1}, "isSuccess": True}))
    assert validate.raw_findings("amex", raw, AS_OF) == []


def test_dump_cli_exit_codes(tmp_path, capsys):
    write_discount(tmp_path, tx=TELEBANK_NO_DEPOSITS)
    assert validate.main(["dump", "discount", "--data-dir", str(tmp_path), "--as-of", "2026-10-16"]) == 1
    assert capsys.readouterr().out.startswith("REJECT")
    assert validate.main(["dump", "no-such-source", "--data-dir", str(tmp_path)]) == 2


# =============================================================================
# 2. Card bills: statement <-> bank debit
# =============================================================================

CAL_OCT = {"issuer": "cal", "card": "all", "billing_date": date(2026, 10, 10), "amount": 7393.89, "kind": "cycle"}
AMEX_7696_OCT = {"issuer": "amex", "card": "7696", "billing_date": date(2026, 10, 10),
                 "amount": 8339.89, "kind": "cycle"}
AMEX_6250_OCT = {"issuer": "amex", "card": "6250", "billing_date": date(2026, 10, 10),
                 "amount": 1914.0, "kind": "cycle"}
DINERS_OCT = ("discount", "2026-10-11", -7393.89, "דיינרס קלו חיוב")
AMEX_OCT = ("discount", "2026-10-11", -8339.89, "אמריקן אקס חיוב")
MC_OCT = ("leumi", "2026-10-11", -1914, "ל.מאסטרקארד")


def blanket(*days):
    """Filler rows so every bank source demonstrably covers the given days."""
    return [bank(src, d, -1, "x") for src in validate.BANK_SOURCES for d in days]


def bills(statements, rows, as_of=AS_OF):
    cov, gaps = ctx(rows)
    return validate.check_card_bills(statements, rows, as_of, cov, gaps)


def test_statement_billed_saturday_matches_sunday_debit():
    rows = [bank(*DINERS_OCT), bank(*AMEX_OCT)]
    res = bills([CAL_OCT, AMEX_7696_OCT], rows)
    assert res["status"] == "pass", res
    assert res["summary"].startswith("2 of 2 statements matched")


def test_leumi_mastercard_debit_matches_but_digest_does_not_classify_it():
    # 2026-10-11 Leumi "ל.מאסטרקארד" -1914 equals AMEX card 6250's statement, yet
    # digest.is_card_bill_payment() misses it (no "חיוב", spelled with an alef), so
    # the ledger counts the settlement as spending on top of the card's purchases.
    res = bills([AMEX_6250_OCT], [bank(*MC_OCT)])
    assert res["status"] == "warn"
    [d] = res["details"]
    assert d["description"] == "ל.מאסטרקארד" and d["amount"] == -1914
    assert "digest.is_card_bill_payment" in d["reason"]


def test_debit_more_than_three_banking_days_late_does_not_match():
    late = bank("discount", "2026-10-15", -7393.89, "דיינרס קלו חיוב")       # 4 banking days
    res = bills([CAL_OCT], [late] + blanket("2026-10-05", "2026-10-16"))
    assert res["status"] == "fail"
    assert any("no matching bank debit" in d["reason"] for d in res["details"])
    assert any("no matching statement" in d["reason"] for d in res["details"])   # the late debit, orphaned


def test_unmatched_statement_inside_bank_ledger_hole_is_a_warning_not_a_failure():
    # Discount has no rows 2026-06-12 -> 2026-09-29: the Sep-10 CAL statement
    # (3,911.40) cannot be found, but the cause is the hole, reported by balance.discount.
    june = bank("discount", "2026-06-10", -14915.55, "דיינרס קלו חיוב")
    edges = [bank("discount", "2026-06-12", -666.72, "פירעון הלוואה 10800100014"),
             bank("discount", "2026-09-29", 1510, "משיכה מפיקדון נזיל יומי+")]
    june_st = {**CAL_OCT, "billing_date": date(2026, 6, 10), "amount": 14915.55}
    sept_st = {**CAL_OCT, "billing_date": date(2026, 9, 10), "amount": 3911.40}
    res = bills([june_st, sept_st], [june] + edges)
    assert res["status"] == "warn"
    assert any("hole" in d["reason"] and d["amount"] == -3911.4 for d in res["details"])
    assert not any(d.get("level") == "fail" for d in res["details"] if d["amount"] == -3911.4)


def test_statement_older_than_the_bank_ledger_is_skipped():
    # AMEX 6250's June statement (4,329.40) predates Leumi's first row (2026-07-06)
    june = {**AMEX_6250_OCT, "billing_date": date(2026, 6, 10), "amount": 4329.4}
    res = bills([june], [bank("leumi", "2026-07-06", 1844.42, "העברה לפיגור"), bank(*MC_OCT)])
    assert res["status"] == "pass" and "1 before bank coverage" in res["summary"]


def test_bank_card_debit_without_a_statement_is_reported():
    # Discount-business paid a CAL "דיינרס קלו חיוב" -129 on 2026-04-10 that no
    # statement in the CAL dump accounts for.
    stmt = {**CAL_OCT, "billing_date": date(2026, 4, 10), "amount": 10050.99}
    rows = [bank("discount", "2026-04-10", -10050.99, "דיינרס קלו חיוב"),
            bank("discount-business", "2026-04-10", -129, "דיינרס קלו חיוב")]
    res = bills([stmt], rows)
    assert res["status"] == "fail"
    [d] = [d for d in res["details"] if d["amount"] == -129]
    assert d["source"] == "discount-business"


def test_max_card_bills_have_no_statement_source_and_are_not_failures():
    rows = [bank("discount", "2026-10-11", -1639.25, "מקס איט פי חיוב"), bank(*DINERS_OCT)]
    res = bills([CAL_OCT], rows)
    assert res["status"] == "pass" and "1 debits of unscraped issuers" in res["summary"]


def test_two_cards_billed_together_match_one_summed_debit():
    a = {**AMEX_7696_OCT, "card": "1111", "amount": 100.0}
    b = {**AMEX_7696_OCT, "card": "2222", "amount": 50.5}
    res = bills([a, b], [bank("discount", "2026-10-11", -150.5, "אמריקן אקס חיוב")])
    assert res["status"] == "pass" and res["summary"].startswith("1 of 2")


def test_issuer_attribution_from_bank_descriptions():
    assert validate.issuer_of("דיינרס קלו חיוב") == "cal"
    assert validate.issuer_of("חיוב לכרטיס מכאל 9947") == "cal"
    assert validate.issuer_of("אמריקן אקס חיוב") == "amex"
    assert validate.issuer_of("ל.מאסטרקארד") == "amex"
    assert validate.issuer_of("מקס איט פי חיוב") == "max"
    assert validate.issuer_of("דסק-משכנתא חיוב") is None


def test_cal_summary_gives_cycle_and_immediate_debits_but_not_future_ones():
    summary = {"result": {"bankAccounts": [{"months": [
        {"month": "2026-02-01T00:00:00", "debitDays": [
            {"debitDay": "2026-02-21T00:00:00", "cards": [
                {"debitDateInd": 2, "dailyDebits": [{"currencySymbol": "₪", "dailyDebit": 1500}]}]},
            {"debitDay": "2026-02-10T00:00:00", "cards": [
                {"debitDateInd": 1, "dailyDebits": [{"currencySymbol": "₪", "dailyDebit": 14200.12}]}]}]},
        {"month": "2026-11-01T00:00:00", "debitDays": [
            {"debitDay": "2026-11-10T00:00:00", "cards": [
                {"debitDateInd": 1, "dailyDebits": [{"currencySymbol": "₪", "dailyDebit": 1798.13}]}]}]}]}]}}
    got = validate.cal_statements(summary, AS_OF)
    assert [(s["billing_date"].isoformat(), s["amount"], s["kind"]) for s in got] == [
        ("2026-02-21", 1500, "immediate"), ("2026-02-10", 14200.12, "cycle")]
    # Saturday 02-21 immediate debit settles Sunday 02-22 (real Discount row: -1500)
    res = bills(got, [bank("discount", "2026-02-22", -1500, "דיינרס קלו חיוב"),
                      bank("discount", "2026-02-10", -14200.12, "דיינרס קלו חיוב")])
    assert res["status"] == "pass"


# =============================================================================
# 3. Card transactions <-> statement total
# =============================================================================

def cal_txn(d, name, trn, billed, refund=False, kind="רגילה", sym="₪", n=0, cur=0):
    return {"trnPurchaseDate": f"{d}T10:00:00", "merchantName": name, "trnAmt": trn,
            "amtBeforeConvAndIndex": billed, "refundInd": refund, "trnType": kind,
            "trnCurrencySymbol": sym, "numOfPayments": n, "curPaymentNum": cur}


# A slice of CAL card 9947's cycle billed 2026-10-10: a $ purchase, a refund, a
# 10-installment deal, a standing order, the card fee and a CashPro loyalty accrual
# (both billed ₪0). ₪ billed = 15.52 - 5 + 114 + 135.14 = 259.66.
CAL_CYCLE = {"result": {"bankAccounts": [{"debitDates": [{
    "date": "2026-10-10T00:00:00",
    "totalDebits": [{"currencySymbol": "₪", "amount": 259.66}],
    "transactions": [
        cal_txn("2026-10-07", "RAILWAY", 5, 15.52, sym="$"),
        cal_txn("2026-09-29", "Gett", 5, -5, refund=True, kind="זיכוי"),
        cal_txn("2026-09-29", "מחסני חשמל-אילת", 1059, 114, kind="תשלומים", n=10, cur=1),
        cal_txn("2026-09-25", 'פרטנר תקשורת בע"מ', 135.14, 135.14, kind="הוראת קבע"),
        cal_txn("2026-09-14", "דמי כרטיס", 19.9, 0, kind="שרותים"),
        cal_txn("2026-09-30", "החזר CashPro", 49.32, 0, kind="צבירה למועדון")]}]}]}}


def cal_row(d, name, amount):
    return {"card_last4": "9947", "billing_date": "2026-10-10", "date": d, "description": name, "amount": amount}


BILLED = [cal_row("2026-10-07", "RAILWAY", -15.52), cal_row("2026-09-29", "Gett", 5),
          cal_row("2026-09-29", "מחסני חשמל-אילת", -114), cal_row("2026-09-25", 'פרטנר תקשורת בע"מ', -135.14)]
FEE_AND_ACCRUAL = [cal_row("2026-09-14", "דמי כרטיס", -19.9), cal_row("2026-09-30", "החזר CashPro", -49.32)]


def cal_check(ledger, body=CAL_CYCLE):
    return validate.check_cal_statements(validate.cal_cycles([("9947", body)]), ledger)


def test_cal_cycle_reconciles_when_ledger_uses_the_billed_shekel_amounts():
    assert cal_check(BILLED)["status"] == "pass"


def test_cal_cycle_fails_when_ledger_carries_dollar_and_whole_deal_amounts():
    # the old normalizer stored -trnAmt: $5 as -5, the installment deal as -1059
    # (not the ₪114 charged this cycle), fee and accrual as charges.
    old = [cal_row("2026-10-07", "RAILWAY", -5), cal_row("2026-09-29", "Gett", 5),
           cal_row("2026-09-29", "מחסני חשמל-אילת", -1059), cal_row("2026-09-25", 'פרטנר תקשורת בע"מ', -135.14),
           *FEE_AND_ACCRUAL]
    res = cal_check(old)
    assert res["status"] == "fail"
    head, *offenders = res["details"]
    assert head["amount"] == -1003.7 and "the dump is complete" in head["reason"]
    assert {o["description"] for o in offenders} == {"RAILWAY", "מחסני חשמל-אילת", "דמי כרטיס", "החזר CashPro"}
    assert any("ledger carries -1,059.00; CAL billed -114.00" in o["reason"] for o in offenders)


def test_cal_card_fee_and_loyalty_accrual_billed_zero_are_pinned_down():
    # residual after the trnAmt fix: ledger 328.88 vs statement 259.66 -> off by 69.22
    res = cal_check(BILLED + FEE_AND_ACCRUAL)
    assert res["status"] == "fail"
    head, *offenders = res["details"]
    assert head["amount"] == -69.22
    assert [(o["description"], o["amount"]) for o in offenders] == [("החזר CashPro", -49.32), ("דמי כרטיס", -19.9)]
    assert "CAL billed +0.00" in offenders[0]["reason"]


def test_cal_cycle_with_incomplete_dump_is_told_apart_from_a_normalizer_bug():
    body = json.loads(json.dumps(CAL_CYCLE))
    body["result"]["bankAccounts"][0]["debitDates"][0]["totalDebits"][0]["amount"] = 1000
    res = cal_check(BILLED, body)
    assert res["status"] == "fail" and "incomplete or paginated" in res["details"][0]["reason"]


def voucher(d, name, billing, **kw):
    return {"purchaseDate": d, "businessName": name, "billingAmount": billing, "ilsAmount": billing,
            "seqVoucherNumber": kw.pop("seq", name), **kw}


def amex_body(vouchers, total, immediate=()):
    groups = [{"immediateVouchersCurrencyDate": [v], "totalVouchersCurrencyDate": {
        "totalImmediateVouchers": v["billingAmount"], "dateImmediateVouchers": when}}
        for v, when in immediate]
    return {"data": {"israelAbroadVouchers": {
        "vouchers": {"israelAbroadVouchersList": vouchers, "totalForStatement": {"totalIlsBillingDate": total}},
        "outOfStatementChargeDateVouchers": groups}}}


# AMEX 7696, statement month 10-2026: a Metro installment credit, two installments
# and a cash withdrawal charged immediately (billed 04/10, outside the statement).
V_METRO = voucher("22/09/2026", "מטרו", -250.28, seq="163996724")
V_KING = voucher("06/09/2026", 'קינג אקספרס בע"מ', 558.06, seq="071400853")
V_METRO2 = voucher("02/09/2026", "מטרו", 125, seq="049855806")
V_CASH = voucher("01/10/2026", "משיכת מזומנים", 700, seq="232489530")
AMEX_LEDGER = [{"card_last4": "7696", "date": "2026-09-22", "amount": 250.28},
               {"card_last4": "7696", "date": "2026-09-06", "amount": -558.06},
               {"card_last4": "7696", "date": "2026-09-02", "amount": -125}]


def amex_months_of(body):
    return validate.amex_months([(Path("transactions_7696_10-2026.json"), body)], {"7696": 10})


def test_amex_statement_sums_and_every_voucher_is_in_the_ledger():
    months = amex_months_of(amex_body([V_METRO, V_KING, V_METRO2], 432.78))
    assert validate.check_amex_statements(months, AMEX_LEDGER)["status"] == "pass"


def test_amex_statement_total_mismatch_flags_a_pagination_gap():
    months = amex_months_of(amex_body([V_METRO, V_KING, V_METRO2], 1432.78))      # a page is missing
    res = validate.check_amex_statements(months, AMEX_LEDGER)
    assert res["status"] == "fail" and res["details"][0]["amount"] == 1000


def test_amex_immediate_cash_withdrawal_missing_from_ledger_is_flagged():
    # AMEX bills cash withdrawals immediately (bank row "אמריקן אקס חיוב" -700 on
    # 2026-10-04); the vouchers sit outside the statement and normalize.py skips them.
    months = amex_months_of(amex_body([V_METRO, V_KING, V_METRO2], 432.78, immediate=[(V_CASH, "04/10/2026")]))
    res = validate.check_amex_statements(months, AMEX_LEDGER)
    assert res["status"] == "fail"
    [d] = res["details"]
    assert d["description"] == "משיכת מזומנים" and d["amount"] == -700 and d["date"] == "2026-10-01"
    present = AMEX_LEDGER + [{"card_last4": "7696", "date": "2026-10-01", "amount": -700}]
    assert validate.check_amex_statements(months, present)["status"] == "pass"
    # and that immediate charge is a statement the bank debit must match (Discount, Sun 10-04)
    stmts = validate.amex_statements(months, AS_OF)
    assert [(s["kind"], s["amount"], s["billing_date"].isoformat()) for s in stmts] == [
        ("cycle", 432.78, "2026-10-10"), ("immediate", 700.0, "2026-10-04")]


def test_amex_pulls_that_errored_are_ignored():
    assert validate.amex_months([(Path("transactions_8146_09-2026.json"), AMEX_NO_DATA)], {}) == []


# =============================================================================
# 4. Checking balance continuity
# =============================================================================

def op(d, amount, balance, desc=""):
    return {"date": date.fromisoformat(d), "amount": amount, "balance_after": balance, "description": desc}


# Leumi, newest first as the dump returns it (real, 2026-10-08 .. 2026-10-11)
LEUMI_TAIL = [op("2026-10-11", -22500, 2813.94, "העברת משכורת_י"),
              op("2026-10-11", -1914, 25313.94, "ל.מאסטרקארד"),
              op("2026-10-08", 26144, 27227.94, "העברת משכורת")]


def leumi_rows(ops):
    return [bank("leumi", o["date"].isoformat(), o["amount"], o["description"]) for o in ops]


def test_chain_orientation_is_detected_whatever_the_dump_order():
    assert [o["amount"] for o in validate.orient_ops(LEUMI_TAIL)] == [26144, -1914, -22500]
    assert [o["amount"] for o in validate.orient_ops(list(reversed(LEUMI_TAIL)))] == [26144, -1914, -22500]


def test_balance_chain_closes_on_the_current_balance():
    res = validate.check_balance("leumi", LEUMI_TAIL, 2813.94, leumi_rows(LEUMI_TAIL))
    assert res["status"] == "pass", res["details"]


def test_missing_operation_breaks_the_balance_chain():
    gappy = [LEUMI_TAIL[0], LEUMI_TAIL[2]]            # the -1914 card bill never made it in
    res = validate.check_balance("leumi", gappy, 2813.94, leumi_rows(gappy))
    assert res["status"] == "fail"
    assert "chain break" in res["summary"]
    assert res["details"][0]["date"] == "2026-10-11" and "operation is missing" in res["details"][0]["reason"]


def test_closing_balance_must_equal_last_operation():
    res = validate.check_balance("leumi", LEUMI_TAIL, 3000.00, leumi_rows(LEUMI_TAIL))
    assert res["status"] == "fail" and "closing balance" in res["summary"]


# Leumi Aug 2026: loan 2529's arrears operations share FITID 202608022529001 with
# the 08-02 repayment, so the FITID-keyed normalizer kept one of the three rows.
AUG_CHAIN = [op("2026-08-02", 870, 887.04, "בנק דיסקונט"), op("2026-08-02", -1844.42, -957.38, "פרעון הלוואה"),
             op("2026-08-02", -8.25, -965.63, "עמל.ערוץ יש  5"), op("2026-08-03", 323.26, -642.37, "מענק בנק לאומי"),
             op("2026-08-03", 8.25, -634.12, "מענק בנק לאומי"), op("2026-08-04", -867.8, -1501.92, "פרעון הלוואה"),
             op("2026-08-05", -342.5, -1844.42, "סלוק חלקי פגור"), op("2026-08-05", 1844.42, 0, "העברה לפיגור")]


def test_ledger_rows_lost_to_a_fitid_collision_break_the_window_sum():
    kept = [o for o in AUG_CHAIN if o["description"] not in ("סלוק חלקי פגור", "העברה לפיגור")]
    res = validate.check_balance("leumi", AUG_CHAIN, 0, leumi_rows(kept))
    assert res["status"] == "fail"
    assert "off by -1,501.92" in res["summary"]
    lost = {d["description"]: d["amount"] for d in res["details"] if "missing from the normalized" in d["reason"]}
    assert lost == {"סלוק חלקי פגור": -342.5, "העברה לפיגור": 1844.42}
    assert validate.check_balance("leumi", AUG_CHAIN, 0, leumi_rows(AUG_CHAIN))["status"] == "pass"


def test_discount_history_hole_between_june_and_september_is_reported_with_its_range():
    rows = [bank("discount", "2026-06-12", -779.02, "חיוב לכרטיס מכאל 9947"),
            bank("discount", "2026-09-29", 1510, "משיכה מפיקדון נזיל יומי+"),
            bank("discount", "2026-10-13", -700, "משיכת מזומן ללא כרטיס")]
    chain = [op("2026-09-29", 1510, 2813.48), op("2026-10-13", -700, 2113.48)]
    res = validate.check_balance("discount", chain, 2113.48, rows)
    assert res["status"] == "fail" and "1 history gap" in res["summary"]
    [d] = res["details"]
    assert d["date"] == "2026-06-12" and "2026-09-29" in d["description"] and "109-day" in d["reason"]


def test_account_without_a_running_balance_chain_is_skipped_unless_it_has_a_hole():
    rows = [bank("discount-business", "2026-08-02", -2650.59, "אמריקן אקס חיוב"),
            bank("discount-business", "2026-09-02", -715.94, "אמריקן אקס חיוב"),
            bank("discount-business", "2026-10-02", -169.79, "אמריקן אקס חיוב")]
    assert validate.check_balance("discount-business", [], None, rows)["status"] == "skip"


def test_scrape_date_extends_coverage_of_a_quiet_account():
    # discount-business last posted on 2026-10-02 but was scraped 2026-10-09
    rows = [bank("discount-business", d, a, "אמריקן אקס חיוב")
            for d, a in (("2026-09-02", -715.94), ("2026-10-02", -169.79))]
    assert ctx(rows)[0]["discount-business"][1] == date(2026, 10, 2)
    cov, _ = validate.bank_context(rows, {"discount-business": date(2026, 10, 9)})
    assert cov["discount-business"][1] == date(2026, 10, 9)


def test_telebank_and_leumi_dump_parsers():
    [o] = validate.telebank_ops(DISCOUNT_TX)
    assert (o["date"], o["amount"], o["balance_after"]) == (date(2026, 10, 13), -700, -5831.15)
    body = {"ProcessRequestResult": 0, "jsonResp": {"HistoryTransactionsItems": [
        {"DateSO": "11/10/2026", "Amount": -1914, "RunningBalance": 25313.94, "Description": "ל.מאסטרקארד"}]}}
    [o] = validate.leumi_ops(body)
    assert (o["date"], o["amount"], o["balance_after"]) == (date(2026, 10, 11), -1914, 25313.94)


# =============================================================================
# 5. Internal transfers
# =============================================================================

FORWARD_OUT = ("leumi", "2026-10-11", -22500, "העברת משכורת_י")
FORWARD_IN = ("discount", "2026-10-11", 22500, "בנק לאומי משכורת")
SEP_FORWARD = ("leumi", "2026-09-09", -22550, "העברת משכורת_י")


def business_filler():
    return [bank("discount-business", d, a, "אמריקן אקס חיוב") for d, a in (
        ("2026-06-02", -881.18), ("2026-07-02", -870.53), ("2026-08-02", -2650.59),
        ("2026-09-02", -715.94), ("2026-10-02", -169.79))]


def transfers(rows, as_of=AS_OF):
    cov, gaps = ctx(rows)
    return validate.check_internal_transfers(rows, as_of, cov, gaps)


def test_salary_forward_has_both_legs():
    res = transfers([bank(*FORWARD_OUT), bank(*FORWARD_IN)] + business_filler())
    assert res["status"] == "pass" and res["summary"].startswith("1 transfers paired")


def test_leg_two_banking_days_apart_still_pairs_but_five_do_not():
    near = transfers([bank(*FORWARD_OUT), bank("discount", "2026-10-13", 22500, "בנק לאומי משכורת")]
                     + business_filler())
    assert near["status"] == "pass"
    far = transfers([bank(*FORWARD_OUT), bank("discount", "2026-10-15", 22500, "בנק לאומי משכורת")]
                    + blanket("2026-10-05", "2026-10-16"))
    assert far["status"] == "fail" and "2 orphaned" in far["summary"]


def test_orphan_leg_with_the_other_bank_present_is_a_failure():
    # Leumi forwarded 22,550 on 2026-09-09; Discount has rows either side but no +22,550
    discount = [bank("discount", d, -666.72, "פירעון הלוואה 10800100014")
                for d in ("2026-09-02", "2026-09-14", "2026-09-28")]
    res = transfers([bank(*SEP_FORWARD)] + discount + business_filler())
    assert res["status"] == "fail"
    [d] = [d for d in res["details"] if d["level"] == "fail"]
    assert d["description"] == "העברת משכורת_י" and d["amount"] == -22550 and d["source"] == "leumi"


def test_orphan_inside_the_discount_hole_is_a_warning():
    # same leg, but Discount's history has the 2026-06-12 .. 2026-09-29 hole
    discount = [bank("discount", "2026-06-12", -779.02, "חיוב לכרטיס מכאל 9947"),
                bank("discount", "2026-09-29", 1510, "משיכה מפיקדון נזיל יומי+")]
    res = transfers([bank(*SEP_FORWARD)] + discount + business_filler())
    assert res["status"] == "warn" and "1 orphaned inside history gaps" in res["summary"]


def test_leg_before_the_other_account_was_scraped_is_out_of_coverage():
    # Discount "בנק לאומי משכורת" +26,150 on 2026-06-09; Leumi's history starts 2026-07-06
    rows = [bank("discount", "2026-06-09", 26150, "בנק לאומי משכורת"),
            bank("leumi", "2026-07-06", 1844.42, "העברה לפיגור"), bank("leumi", "2026-07-08", 26145, "העברת משכורת")]
    res = transfers(rows + business_filler())
    assert res["status"] == "pass" and "1 outside the other account's coverage" in res["summary"]


def test_transfers_to_untracked_accounts_are_not_orphans():
    rows = [bank("discount", "2026-10-05", 450, "העברה מירין ששון חשבון ב.הפועלים-ביט משיכה לחשבון בנק"),
            bank("discount", "2026-10-13", 2490, "משיכה מפיקדון נזיל יומי+")]
    res = transfers(rows)
    assert res["status"] == "pass" and "2 to/from untracked accounts" in res["summary"]


def test_branch_number_in_description_says_where_the_other_leg_lives():
    # "מסניף 11-034" on the business account = a standing order FROM Discount
    assert validate.transfer_hint(
        {"description": 'הו"ק מששון ירין מסניף 11-034'}, "discount-business") == \
        ("expect", ["discount"])
    assert validate.transfer_hint({"description": "הע. לירין ששון בסניף 10-806"}, "discount") == \
        ("expect", ["leumi"])


# =============================================================================
# 6. Loan payments
# =============================================================================

def loans(exps, rows, origin="discount", as_of=AS_OF, cid="loans.x"):
    cov, gaps = ctx(rows)
    return validate.check_loan_group(cid, "test", exps, rows, origin, as_of, cov, gaps)


def mort_match(r):
    return "משכנתא" in (r.get("description") or "")


MORTGAGE = ("Discount mortgage", 5817.26, date(2026, 11, 10), mort_match)
MORT_DEBIT = ("discount", "2026-10-11", -5817.25, "דסק-משכנתא חיוב")
OCT_FILLER = [bank("discount", "2026-10-02", -666.72, "פירעון הלוואה 10800100014"),
              bank("discount", "2026-10-13", -700, "משיכת מזומן ללא כרטיס")]


def test_mortgage_next_payment_matches_the_october_debit():
    # six tracks' NextPayment sum 5,817.26; the bank debited 5,817.25 on Sun 10-11
    res = loans([MORTGAGE], [bank(*MORT_DEBIT)])
    assert res["status"] == "pass" and "1 installment(s) found" in res["summary"]


def test_installment_outside_the_bank_ledgers_coverage_is_skipped_not_passed():
    res = loans([MORTGAGE], [bank("discount", "2026-10-13", -700, "משיכת מזומן ללא כרטיס")])
    assert res["status"] == "skip"


def test_mortgage_debit_far_from_the_dump_is_a_failure():
    res = loans([MORTGAGE], [bank("discount", "2026-10-11", -6400, "דסק-משכנתא חיוב")])
    assert res["status"] == "fail" and "+582.74" in res["details"][0]["reason"]


def test_mortgage_debit_missing_in_a_covered_month_is_a_failure():
    res = loans([MORTGAGE], OCT_FILLER)
    assert res["status"] == "fail" and "no matching debit" in res["details"][0]["reason"]


def test_older_mortgage_installments_inside_the_discount_hole_only_warn():
    rows = [bank("discount", "2026-06-10", -1707.54, "דסק-משכנתא חיוב"),
            bank("discount", "2026-06-12", -779.02, "חיוב לכרטיס מכאל 9947"),
            bank("discount", "2026-09-29", 1510, "משיכה מפיקדון נזיל יומי+"), bank(*MORT_DEBIT)]
    res = loans([MORTGAGE], rows)
    assert res["status"] == "warn"
    assert [d["date"] for d in res["details"]] == ["2026-09-10", "2026-08-10"]


def test_discount_consumer_loan_matched_by_account_suffix_with_variable_rate_drift():
    body = {"LoansQuery": {"LoanDetailsBlock": {"LoanEntry": [{
        "LoanAccount": "0034015500316168", "LoanName": "הלוואה לא צמודה ברבית משתנה",
        "NextPayment": 308.25, "NextPaymentDate": "20261101"}]}}}
    [(name, amount, due, acct)] = validate.discount_loan_expectations(body)
    assert (amount, due) == (308.25, date(2026, 11, 1))
    exps = [(name, amount, due, lambda r: acct[-11:] in (r.get("description") or ""))]
    # actual 2026-10-02 debit 306.47 (variable rate), a different loan's 666.72 alongside
    rows = [bank("discount", "2026-09-29", 1510, "משיכה מפיקדון נזיל יומי+"),
            bank("discount", "2026-10-02", -306.47, "פירעון הלוואה 15500316168")] + OCT_FILLER
    res = loans(exps, rows)
    assert res["status"] == "pass" and "1 installment(s) found" in res["summary"]


LEUMI_LOANS = {"loans": [
    {"loanLabel": "‏ללא ריבית הצטרפות ‏ ‎2529-1/3‎", "generalInfo": {"מספר הלוואה": "25290013"},
     "balances": {"סכום התשלום הבא": "1,844.42"}, "dates": {"תאריך התשלום הבא": "02/11/26"}},
    {"loanLabel": "‏מילואים‏ ‎6673-1/4‎", "generalInfo": {"מספר הלוואה": "66730014"},
     "balances": {"סכום התשלום הבא": "867.80"}, "dates": {"תאריך התשלום הבא": "04/11/26"}}]}


def leumi_exps():
    return [(n, a, d, lambda r, a=a: "פרעון" in (r.get("description") or "") and abs(abs(r["amount"]) - a) < 5)
            for n, a, d in validate.leumi_loan_expectations(LEUMI_LOANS)]


def test_leumi_loan_installments_found_as_october_debits():
    assert [(a, d.isoformat()) for _, a, d, _ in leumi_exps()] == [(1844.42, "2026-11-02"), (867.8, "2026-11-04")]
    rows = [bank("leumi", "2026-10-02", -1844.42, "פרעון הלוואה"), bank("leumi", "2026-10-04", -867.8, "פרעון הלוואה")]
    assert loans(leumi_exps(), rows, origin="leumi")["status"] == "pass"


def test_leumi_loan_installment_without_a_debit_fails():
    rows = [bank("leumi", "2026-10-02", -1844.42, "פרעון הלוואה"),
            bank("leumi", "2026-10-01", -6.6, "עמל.ערוץ יש  4"), bank("leumi", "2026-10-08", 26144, "העברת משכורת")]
    res = loans(leumi_exps(), rows, origin="leumi")
    assert res["status"] == "fail"
    [d] = res["details"]
    assert "6673" in d["description"] and d["amount"] == -867.8


def test_mortgage_dump_expectation_is_the_sum_of_next_payments():
    entry = lambda pay: {"NextPayment": pay, "NextPaymentDate": "20261110"}
    body = {"MortgagesDetails": {"MortgagesBlock": {"MortgageEntry": [{"MortgageDetailsBlock": {
        "LoanEntry": [entry(843.86), entry(1600.43), entry(1665.43), entry(461.59), entry(659.51), entry(586.44)]}}]}}}
    name, total, due = validate.mortgage_expectations(body)
    assert (total, due) == (5817.26, date(2026, 11, 10)) and "6 tracks" in name


# =============================================================================
# 7. Salary arrival
# =============================================================================

SALARY = [("2026-07-08", 26145), ("2026-08-09", 26144), ("2026-09-08", 26145), ("2026-10-08", 26144)]
CARD_BILLS_LEUMI = [("2026-07-10", -2107.55), ("2026-08-10", -3200), ("2026-09-10", -2256.7), ("2026-10-11", -1914)]
LOAN_2529 = [("2026-08-02", -1844.42), ("2026-09-02", -1844.42), ("2026-10-02", -1844.42)]


def leumi_salary_ledger(skip=None):
    rows = [bank("leumi", d, a, "העברת משכורת") for d, a in SALARY if d != skip]
    rows += [bank("leumi", d, a, "ל.מאסטרקארד") for d, a in CARD_BILLS_LEUMI]
    rows += [bank("leumi", d, a, "פרעון הלוואה") for d, a in LOAN_2529]
    return rows


def salary(rows, as_of=AS_OF):
    cov, gaps = ctx(rows)
    return validate.check_salary(rows, as_of, cov, gaps)


def test_salary_arrived_in_each_of_the_last_four_months():
    res = salary(leumi_salary_ledger())
    assert res["status"] == "pass"
    assert "4 of 4" in res["summary"] and "העברת משכורת" in res["summary"]


def test_missing_september_salary_is_a_failure():
    res = salary(leumi_salary_ledger(skip="2026-09-08"))
    assert res["status"] == "fail"
    [d] = res["details"]
    assert d["date"] == "2026-09-08" and d["description"] == "העברת משכורת" and d["source"] == "leumi"


def test_august_salary_due_on_a_saturday_is_expected_sunday():
    # day 8 of Aug 2026 is a Saturday -> the real row posted Sun 08-09; had it
    # not, the miss is reported against Sunday, the day the bank would post it
    res = salary(leumi_salary_ledger(skip="2026-08-09"))
    assert res["status"] == "fail" and res["details"][0]["date"] == "2026-08-09"


def test_payday_window_not_yet_over_is_not_judged():
    # asked on 2026-10-07, October's window (10-06 .. 10-12) is still open
    rows = [r for r in leumi_salary_ledger() if r["date"] != "2026-10-08"]
    res = salary(rows, as_of=date(2026, 10, 7))
    assert res["status"] == "pass" and "3 of 3" in res["summary"]


def test_no_recurring_salary_in_the_bank_ledger_warns():
    assert salary([bank("leumi", "2026-10-11", -1914, "ל.מאסטרקארד")])["status"] == "warn"


# =============================================================================
# Orchestration, report, actions
# =============================================================================

def test_run_all_on_empty_data_dir_does_not_crash_or_fail(tmp_path):
    report = validate.run_all(tmp_path, AS_OF)
    assert report["summary"]["fail"] == 0 and report["as_of"] == "2026-10-16"
    assert sum(report["summary"].values()) == len(report["checks"])
    ids = {c["id"] for c in report["checks"]}
    assert {"card_bills", "card_statements.cal", "card_statements.amex", "internal_transfers",
            "loans.mortgage", "loans.discount", "loans.leumi", "salary"} <= ids


def test_run_all_end_to_end_on_a_minimal_discount_dump(tmp_path):
    write_discount(tmp_path)
    write_prev(tmp_path, "discount", "transactions", [
        {"date": "2026-10-13", "amount": -700, "description": "משיכת מזומן ללא כרטיס"}])
    report = validate.run_all(tmp_path, AS_OF, dry_run=False)
    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["balance.discount"]["status"] == "pass"
    assert by_id["dump.discount"]["status"] in ("pass", "warn")


def test_write_report_emits_json_and_markdown(tmp_path):
    report = {"generated_at": "2026-10-16T09:00:00+03:00", "as_of": "2026-10-16",
              "summary": {"pass": 0, "warn": 0, "fail": 1, "skip": 0},
              "checks": [validate.result("balance.leumi", "balance", "fail", "leumi: off by -1,501.92", [
                  {"date": date(2026, 8, 5), "source": "leumi", "description": "סלוק חלקי פגור", "amount": -342.5,
                   "level": "fail", "reason": "missing from the normalized ledger"}])]}
    validate.write_report(report, tmp_path)
    data = json.loads((tmp_path / "validation.json").read_text())
    assert data["checks"][0]["details"][0]["date"] == "2026-08-05"
    md = (tmp_path / "validation.md").read_text()
    assert "balance.leumi" in md and "סלוק חלקי פגור" in md


def test_validation_actions_follow_the_actions_py_shape():
    report = {"generated_at": "2026-10-16T09:00:00+03:00", "checks": [
        validate.result("dump.discount", "dump", "fail", "discount: transactions.json: error stub"),
        validate.result("balance.leumi", "balance", "fail", "leumi: off by -1,501.92", [
            {"amount": -342.5, "level": "fail"}, {"amount": 1844.42, "level": "fail"}]),
        validate.result("loans.mortgage", "loan_payment", "warn", "2 warned"),
        validate.result("salary", "salary", "pass", "ok")]}
    acts = validate.validation_actions(report)
    assert [a["id"] for a in acts] == ["validation:dump.discount:2026-10", "validation:balance.leumi:2026-10"]
    assert [a["severity"] for a in acts] == ["critical", "high"]
    assert acts[1]["amount"] == 2186.92 and acts[1]["cta"] == {"label": "לסנכרונים", "to": "/syncs"}
    assert set(acts[0]) == {"id", "severity", "title", "detail", "cta", "amount"}
    low = validate.validation_actions(report, include_warn=True)
    assert low[-1]["severity"] == "low" and low[-1]["id"].startswith("validation:loans.mortgage")
