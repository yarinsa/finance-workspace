"""Real-case tests for digest.py's transaction classifiers.

Each case is anchored to an actual decision documented in digest.py / CLAUDE.md
about what counts as cashflow vs. an internal move, a card-bill double-count, or
a savings deposit. When a misclassification is reported as a bug, add the exact
description that went wrong here as a new case (see CLAUDE.md "Bugs → tests").
"""
import digest


def tx(amount, description, origin="discount"):
    return {"amount": amount, "description": description, "origin": origin}


class TestInternalTransfer:
    def test_own_holder_name_in_description_is_internal(self):
        # A move that names the household holder is a self-transfer, not income.
        assert digest.is_internal_transfer(tx(5000, "העברה מירין ששון"))
        assert digest.is_internal_transfer(tx(-5000, "העברה לששון ירין"))

    def test_own_account_number_in_description_is_internal(self):
        assert digest.is_internal_transfer(tx(-3000, "העברה לחשבון 806-6719"))

    def test_leumi_digital_sweep_is_internal(self):
        # "העברה דיגיטל" empties the Leumi account into Discount — confirmed self-move.
        assert digest.is_internal_transfer(tx(-12000, "העברה דיגיטל", origin="leumi"))

    def test_external_salary_is_not_internal(self):
        # Salary does NOT name the holder, so it must survive as real income.
        assert not digest.is_internal_transfer(tx(20000, "העברת משכורת"))
        assert not digest.is_internal_transfer(tx(20000, "בנק לאומי משכורת"))

    def test_ordinary_purchase_is_not_internal(self):
        assert not digest.is_internal_transfer(tx(-89, "שופרסל דיל"))


class TestCardBillPayment:
    def test_bank_settlement_to_issuer_is_a_bill(self):
        # Bank→card-issuer monthly clearing — purchases already in the ledger.
        assert digest.is_card_bill_payment(tx(-8000, "חיוב ויזה כ.א.ל", origin="discount"))
        assert digest.is_card_bill_payment(tx(-4200, "חיוב ישראכרט", origin="leumi"))

    def test_ascii_issuer_name_is_matched_case_insensitively(self):
        assert digest.is_card_bill_payment(tx(-1500, "חיוב MAX איט", origin="discount"))

    def test_card_origin_purchase_is_not_a_bill(self):
        # Same issuer word but the row comes from a card source, not a bank — it's
        # an actual purchase, must not be excluded.
        assert not digest.is_card_bill_payment(tx(-89, "חיוב ויזה כ.א.ל", origin="cal"))

    def test_inbound_credit_is_not_a_bill(self):
        # Settlements are debits; a positive amount is never a bill payment.
        assert not digest.is_card_bill_payment(tx(8000, "חיוב ויזה כ.א.ל", origin="discount"))


class TestSavingsDeposit:
    def test_standing_order_to_investment_manager_is_savings(self):
        assert digest.is_savings_deposit(tx(-2000, 'הו"ק אקסלנס'))
        assert digest.is_savings_deposit(tx(-1000, "הפקדה לפיקדון"))

    def test_keren_hishtalmut_transfer_is_savings(self):
        assert digest.is_savings_deposit(tx(-1500, "העברה לקרן השתלמות"))

    def test_rent_standing_order_is_not_savings(self):
        # "ניהול נכסי" is RENT, deliberately excluded from the savings phrases.
        assert not digest.is_savings_deposit(tx(-6500, 'הו"ק עיין ניהול נכסי'))

    def test_inbound_is_not_savings(self):
        assert not digest.is_savings_deposit(tx(2000, "הפקדה לפיקדון"))


class TestDepositWithdrawalIsNotIncome:
    """2026-08 leak: withdrawing from our own liquid deposit (פיקדון נזיל) came
    back tagged as real income. It's the user's own money returning, not cashflow
    — should be tagged internal_transfer just like the deposit leg is tagged
    savings, so spending_summary excludes both sides of the round-trip.
    """

    def test_liquid_deposit_withdrawal_is_internal(self):
        assert digest.is_internal_transfer(tx(9507, "משיכה מפיקדון נזיל יומי+"))
        assert digest.is_internal_transfer(tx(8900, "משיכה מפיקדון נזיל יומי+"))
        assert digest.is_internal_transfer(tx(4200, "משיכה מפיקדון נזיל יומי+"))
        assert digest.is_internal_transfer(tx(300, "משיכה מפיקדון נזיל יומי+"))

    def test_liquid_deposit_withdrawal_profit_is_internal(self):
        # Small interest/profit credited alongside a withdrawal — also our own money.
        assert digest.is_internal_transfer(tx(0.03, "רווחים ממשיכת הפקדה מפיקדון"))

    def test_liquid_deposit_deposit_leg_still_savings_not_internal(self):
        # The deposit leg (money leaving to the deposit) keeps its existing
        # `savings` classification — do not silently reclassify it.
        assert digest.is_savings_deposit(tx(-23296, "הפקדה לפיקדון נזיל יומי+"))
        assert not digest.is_internal_transfer(tx(-23296, "הפקדה לפיקדון נזיל יומי+"))


class TestLoanRoundTrip:
    """2026-08 leak: a loan opened and repaid within days (same loan id
    13200898802) netted to ~zero but both legs counted as real income/spend.
    Match on the specific loan-number pairing that actually round-tripped, not a
    blanket rule on every 'הקמת הלוואה'/'פירעון הלוואה' — most loan repayments in
    the ledger (leumi, discount loans 10800100014 / 15500316168) are real ongoing
    debt service and must stay counted as spend.
    """

    def test_opened_and_repaid_same_loan_id_is_internal(self):
        assert digest.is_internal_transfer(tx(10000, "הקמת הלוואה 13200898802"))
        assert digest.is_internal_transfer(tx(-10008.67, "פירעון הלוואה 13200898802"))

    def test_ordinary_ongoing_loan_repayment_is_not_internal(self):
        # These loan ids never had a matching "הקמת הלוואה" — real debt service.
        assert not digest.is_internal_transfer(tx(-666.72, "פירעון הלוואה 10800100014"))
        assert not digest.is_internal_transfer(tx(-310.44, "פירעון הלוואה 15500316168"))
        assert not digest.is_internal_transfer(tx(-867.8, "פרעון הלוואה", origin="leumi"))

