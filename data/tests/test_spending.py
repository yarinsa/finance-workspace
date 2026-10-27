"""Real-case tests for the month spending explorer (data/spending.py).

Cases come from the live ledger: the AMEX bill debited from Discount, a transfer
from Yarin's own Bit account, and Apple's differently-padded card descriptions.
"""
from datetime import date

import spending

AMEX_BILL = {"date": "2026-09-02", "amount": -8339.89, "description": "אמריקן אקס,חיוב",
             "category": "תשלומים", "origin": "discount", "card_bill_payment": True}
SELF_TRANSFER = {"date": "2026-09-05", "amount": 200,
                 "description": "העברה מירין ששון,חשבון ב.הפועלים-ביט,משיכה לחשבון בנק",
                 "origin": "discount", "internal_transfer": True}
APPLE_CORK = {"date": "2026-09-10", "amount": -39.9, "category": "מנויים", "origin": "cal",
              "description": "APPLE.COM/BILL         CORK          IRL"}
APPLE_CUP = {"date": "2026-09-12", "amount": -12.38, "category": "מנויים", "origin": "cal",
             "description": "APPLE.COM/BILL         CUPERTINO     USA"}
GROCERY = {"date": "2026-09-14", "amount": -250.0, "category": "מזון", "description": "שופרסל דיל"}
AUG_GROCERY = {"date": "2026-08-14", "amount": -200.0, "category": "מזון", "description": "שופרסל דיל"}
SALARY = {"date": "2026-09-09", "amount": 15000, "is_income": True, "description": "משכורת"}
PENSION = {"date": "2026-09-11", "amount": -900, "savings": True, "description": "הפקדה לפנסיה"}

LEDGER = [AMEX_BILL, SELF_TRANSFER, APPLE_CORK, APPLE_CUP, GROCERY, AUG_GROCERY, SALARY, PENSION]


def sep():
    return next(m for m in spending.build_spending(LEDGER)["months"] if m["month"] == "2026-09")


class TestExclusion:
    def test_card_bill_is_not_spending_but_is_listed(self):
        m = sep()
        assert m["excluded"]["card_bills"] == {"amount": 8339.89, "count": 1}
        assert all("אמריקן" not in t["merchant"] for t in m["transactions"])

    def test_internal_transfer_counted_as_transfer(self):
        assert sep()["excluded"]["transfers"] == {"amount": 200, "count": 1}

    def test_savings_and_income_are_separate_buckets(self):
        m = sep()
        assert m["excluded"]["savings"] == {"amount": 900, "count": 1}
        assert m["excluded"]["income"] == {"amount": 15000, "count": 1}

    def test_total_only_counts_real_purchases(self):
        assert sep()["total"] == round(39.9 + 12.38 + 250, 2)

    def test_card_bill_that_is_also_internal_transfer_counts_once(self):
        both = dict(AMEX_BILL, amount=-700, internal_transfer=True)
        m = spending.build_spending([both])["months"][0]
        assert m["excluded"]["card_bills"]["count"] == 1
        assert m["excluded"]["transfers"]["count"] == 0


class TestMerchants:
    def test_apple_rows_group_under_one_merchant(self):
        assert spending.merchant_name(APPLE_CORK["description"]) == "APPLE.COM/BILL"
        assert spending.merchant_name(APPLE_CUP["description"]) == "APPLE.COM/BILL"
        apple = [x for x in sep()["by_merchant"] if x["name"] == "APPLE.COM/BILL"]
        assert apple == [{"name": "APPLE.COM/BILL", "amount": 52.28, "count": 2}]

    def test_bank_memo_fields_keep_only_the_counterparty(self):
        assert spending.merchant_name(SELF_TRANSFER["description"]) == "העברה מירין ששון"

    def test_plain_hebrew_name_untouched(self):
        assert spending.merchant_name("  שופרסל   דיל ") == "שופרסל דיל"


class TestMonths:
    def test_vs_prev_is_delta_against_previous_month(self):
        m = sep()
        assert m["vs_prev"] == round((39.9 + 12.38 + 250) - 200, 2)

    def test_oldest_month_has_no_previous(self):
        aug = next(m for m in spending.build_spending(LEDGER)["months"] if m["month"] == "2026-08")
        assert aug["vs_prev"] is None

    def test_newest_first_and_category_pct(self):
        months = spending.build_spending(LEDGER)["months"]
        assert [m["month"] for m in months] == ["2026-09", "2026-08"]
        cats = {c["name"]: c for c in months[0]["by_category"]}
        assert cats["מזון"]["pct"] == round(250 / 302.28 * 100, 1)
        assert months[0]["by_category"][0]["name"] == "מזון"

    def test_future_dated_rows_dropped_and_month_flagged_partial(self):
        future = dict(GROCERY, date="2026-09-29")
        m = spending.build_spending([GROCERY, future], today=date(2026, 9, 16))["months"][0]
        assert m["total"] == 250 and m["partial"] is True

    def test_transactions_capped_and_sorted_desc(self):
        many = [dict(GROCERY, date=f"2026-09-{1 + i % 28:02d}") for i in range(400)]
        txs = spending.build_spending(many)["months"][0]["transactions"]
        assert len(txs) == spending.MAX_TX_PER_MONTH
        assert txs[0]["date"] >= txs[-1]["date"]


def test_overridden_flag_reaches_the_month_rows():
    # A row recategorised in the ledger DB keeps its "edited" marker in the app.
    edited = {**GROCERY, "category": "מסעדות", "overridden": True}
    month = next(m for m in spending.build_spending([edited, APPLE_CORK])["months"] if m["month"] == "2026-09")
    rows = {t["merchant"]: t for t in month["transactions"]}
    assert rows[spending.merchant_name(GROCERY["description"])]["overridden"] is True
    assert "overridden" not in rows[spending.merchant_name(APPLE_CORK["description"])]


class TestSections:
    """Rows carry the ledger's kind and group so /monthly can group by section."""
    RENT = {"date": "2026-10-01", "amount": -6800.0, "description": 'הו"ק לעיין ניהול נכסי',
            "category": "שכר דירה", "category_group": "דיור", "kind": "fixed"}
    MORTGAGE = {"date": "2026-10-02", "amount": -5817.25, "description": "דסק-משכנתא",
                "category": "משכנתא", "category_group": "פיננסים", "kind": "fixed"}
    FOOD = {"date": "2026-10-14", "amount": -250.0, "description": "שופרסל דיל",
            "category": "כלכלה", "category_group": "אוכל", "kind": "variable"}
    # a household edit made this grocery run fixed; the edit wins, never re-derived
    EDITED = {"date": "2026-10-15", "amount": -100.0, "description": "שופרסל דיל",
              "category": "כלכלה", "category_group": "אוכל", "kind": "fixed", "overridden": True}
    PENSION_DEBIT = {"date": "2026-10-10", "amount": -250.0, "description": "הראל פנסיה חיוב",
                     "category": "השקעה וחיסכון", "category_group": "הכנסות וחיסכון"}

    def oct(self):
        rows = [self.RENT, self.MORTGAGE, self.FOOD, self.EDITED, self.PENSION_DEBIT]
        return spending.build_spending(rows)["months"][0]

    def test_rows_carry_kind_group_and_block(self):
        tx = {t["merchant"]: t for t in self.oct()["transactions"]}
        rent = tx['הו"ק לעיין ניהול נכסי']
        assert (rent["kind"], rent["group"], rent["block"]) == ("fixed", "דיור", "fixed")
        assert tx["שופרסל דיל"]["block"] in ("fixed", "variable")
        assert tx["דסק-משכנתא"]["block"] == "debt_savings"
        assert tx["הראל פנסיה חיוב"]["block"] == "debt_savings"
        assert "kind" not in tx["הראל פנסיה חיוב"]

    def test_by_line_splits_a_category_by_section(self):
        lines = {(x["block"], x["category"]): x["amount"] for x in self.oct()["by_line"]}
        assert lines[("variable", "כלכלה")] == 250.0
        assert lines[("fixed", "כלכלה")] == 100.0
        assert lines[("fixed", "שכר דירה")] == 6800.0
        assert lines[("debt_savings", "משכנתא")] == 5817.25
        assert sum(lines.values()) == self.oct()["total"]
