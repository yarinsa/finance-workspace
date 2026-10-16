"""Horizon buckets (current / near / future), from real ledger rows."""
import horizons
from horizons import build_horizons, default_horizon


def tx(desc, amount, date="2026-09-10", **kw):
    return {"date": date, "amount": amount, "description": desc, **kw}


def test_liquid_deposit_is_near():
    assert default_horizon(tx("הפקדה לפיקדון נזיל יומי+", -5000, savings=True)) == "near"


def test_excellence_investment_transfer_is_near():
    assert default_horizon(tx("העברה לאקסלנס ניהול השק בנק 12,ל 12-600-", -2000, savings=True)) == "near"


def test_loan_principal_is_near_but_interest_is_current():
    assert default_horizon(tx("פירעון הלוואה 15500316168", -1450, category="הלוואה")) == "near"
    assert default_horizon(tx("פרעון ריבית", -120, category="הלוואה")) == "current"
    assert default_horizon(tx("תשלום ריבית על משיכת יתר- מינוס", -80, category="הלוואה")) == "current"


def test_pension_and_gemel_are_future():
    assert default_horizon(tx('הו"ק לקרן פנסיה', -1200)) == "future"
    assert default_horizon(tx("הפקדה לקופת גמל אנליסט", -800)) == "future"


def test_harel_insurance_is_not_retirement():
    # Harel also sells health/car insurance: the name alone is "current".
    assert default_horizon(tx("הראל ביטוח בריאות", -150, category="ביטוח")) == "current"


def test_rent_and_mortgage_are_current():
    assert default_horizon(tx("עיין ניהול נכסי", -6000)) == "current"
    assert default_horizon(tx("משכנתא", -8500, category="משכנתא")) == "current"


def test_non_expenses_have_no_horizon():
    assert default_horizon(tx("משכורת", 20000, is_income=True)) is None
    assert default_horizon(tx("כאל", -3000, card_bill_payment=True)) is None
    assert default_horizon(tx("העברה לחשבון", -1000, internal_transfer=True)) is None


def test_split_is_against_net_income_with_override_winning():
    rows = [
        tx("משכורת", 30000, is_income=True),
        tx("עיין ניהול נכסי", -6000),
        tx("הפקדה לפיקדון נזיל יומי+", -9000, savings=True),
        # a manual override moves this from current to future
        tx("BUY ETF", -3000, horizon="future", overridden=True),
        tx("כאל", -4000, card_bill_payment=True),           # not counted twice
    ]
    m = build_horizons(rows)["months"][0]
    assert m["income"] == 30000
    assert m["buckets"]["current"]["amount"] == 6000 and m["buckets"]["current"]["pct"] == 20.0
    assert m["buckets"]["near"]["pct"] == 30.0
    assert m["buckets"]["future"]["amount"] == 3000
    assert m["buckets"]["future"]["top"][0]["overridden"] is True
    assert m["unallocated"] == {"amount": 12000, "pct": 40.0}
    assert m["buckets"]["future"]["gap_pts"] == round(10.0 - horizons.TARGET_PCT, 1)


def test_month_without_income_has_no_pct():
    m = build_horizons([tx("עיין ניהול נכסי", -6000)])["months"][0]
    assert m["buckets"]["current"]["pct"] is None
