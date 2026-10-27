"""finance/categories.py: one taxonomy (category + group) and the fixed/variable kind.

Every case is a real ledger row that the old split (RiseUp labels for the ledger,
RiseUp envelopes for budgets, hardcoded sets for the fixed-cost review) got wrong
or disagreed on.
"""
from finance import categories as cat


def row(date, amount, description, **kw):
    return {"date": date, "amount": amount, "description": description, **kw}


def monthly(description, amount, months, day=2, **kw):
    return [row(f"2026-{m:02d}-{day:02d}", amount, description, **kw) for m in months]


# --- category ----------------------------------------------------------------

def test_metro_motor_is_transport_not_installments():
    """As the household, Metro Motor's ₪500 on 2026-10-02 is the motorcycle: תחבורה/רכב,
    fixed. RiseUp labelled it "תשלומים" (how it is paid), its fixed envelope "רכב"."""
    ledger = monthly("מטרו מוטור שווק (1981)בעמ", -500.0, range(4, 11), category="תשלומים",
                     sources=["cal", "riseup"])
    cat.stamp(ledger)
    t = ledger[-1]
    assert (t["category_group"], t["category"], t["kind"], t["kind_source"]) == ("תחבורה", "רכב", "fixed", "recurring")
    assert t["source_category"] == "תשלומים"


def test_fuel_is_transport_and_variable():
    """פז אפליקצית-YELLOW ₪36.88 on 2026-10-05 is fuel: תחבורה/דלק, variable. RiseUp's
    tracking envelope "תחבורה" is too broad to name it, so the merchant decides."""
    ledger = [row("2026-10-05", -36.88, "פז אפליקצית-YELLOW", category="רכב", budget_category="תחבורה")]
    cat.stamp(ledger)
    assert (ledger[0]["category_group"], ledger[0]["category"], ledger[0]["kind"]) == ("תחבורה", "דלק", "variable")


def test_gas_bill_is_not_fuel():
    """פזגז בע"מ is the gas bill (חשבונות/גז), not a פז fuel station."""
    ledger = [row("2026-09-20", -52.22, 'פזגז בע"מ', category="גז")]
    cat.stamp(ledger)
    assert ledger[0]["category"] == "גז"


def test_rent_is_housing_not_transfers():
    """The ₪6,800 standing order to the property manager is rent (דיור/שכר דירה, fixed);
    RiseUp labels it "העברות"."""
    ledger = [row("2026-10-11", -6800.0, 'הו"ק לעיין ניהול נכסי,לסניף 20-406', category="העברות")]
    cat.stamp(ledger)
    assert (ledger[0]["category"], ledger[0]["kind"], ledger[0]["kind_source"]) == ("שכר דירה", "fixed", "merchant")


def test_tracking_envelope_becomes_the_category():
    """A RiseUp tracking envelope is a deliberate budget line: שומשום בר placed in
    "אוכל בעבודה" is that category, not RiseUp's generic "אוכל בחוץ"."""
    ledger = [row("2026-09-14", -37.0, "שומשום בר בריאות", category="אוכל בחוץ", budget_category="אוכל בעבודה")]
    cat.stamp(ledger)
    assert (ledger[0]["category_group"], ledger[0]["category"]) == ("אוכל", "אוכל בעבודה")


def test_old_tracking_names_are_categories():
    for name in ("עציצים", "דירה בת ים", "דייטים", "מתנות", "גינה", "אלכוהול", "הוצאות עסק", "wellness"):
        assert name in cat.CATEGORY_GROUP, name


def test_vacation_envelope_merges_into_tourism():
    ledger = [row("2026-08-10", -558.0, 'קינג אקספרס בע"מ', category="תשלומים", budget_category="חופשה ✈️")]
    cat.stamp(ledger)
    assert ledger[0]["category"] == "תיירות"


def test_card_issuer_sector_labels_map_in():
    """A card-only row carries CAL/Max's sector ("רכב ותחבורה"), not RiseUp's label."""
    ledger = [row("2026-07-19", -63.0, "סופר יודה", category="מזון וצריכה", sources=["max"])]
    assert cat.stamp(ledger) == set()
    assert ledger[0]["category"] == "כלכלה"


def test_unknown_label_passes_through_and_is_reported():
    ledger = [row("2026-07-19", -40.0, "חנות חיות", category="חיות מחמד")]
    assert cat.stamp(ledger) == {"חיות מחמד"}
    assert ledger[0]["category"] == "חיות מחמד" and ledger[0]["kind"] == "variable"


def test_stamp_is_idempotent():
    ledger = monthly("מטרו מוטור שווק (1981)בעמ", -500.0, range(4, 11), category="תשלומים")
    cat.stamp(ledger)
    first = [dict(t) for t in ledger]
    cat.stamp(ledger)
    assert ledger == first


# --- kind --------------------------------------------------------------------

def test_spotify_monthly_is_fixed_by_recurrence():
    ledger = monthly("SpotifyIL", -43.9, range(5, 10), day=9, category="דיגיטל")
    cat.stamp(ledger)
    assert {(t["kind"], t["kind_source"]) for t in ledger} == {("fixed", "recurring")}


def test_partner_bill_with_small_drift_is_fixed():
    """פרטנר went ₪129 -> ₪135 (4.6%): still the same bill."""
    ledger = [row("2026-06-12", -129.0, 'פרטנר תקשורת בע"מ', category="תקשורת"),
              row("2026-07-12", -129.0, 'פרטנר תקשורת בע"מ', category="תקשורת"),
              row("2026-08-12", -135.14, 'פרטנר תקשורת בע"מ', category="תקשורת")]
    cat.stamp(ledger)
    assert all(t["recurring"] for t in ledger)


def test_electricity_is_variable_even_in_a_riseup_fixed_envelope():
    """חב החשמל ₪611 sits in a RiseUp fixed envelope, but it follows usage."""
    ledger = [row("2026-09-16", -611.37, "חב החשמל-דן תש אינט'", category="חשמל", budget_type="fixed")]
    cat.stamp(ledger)
    assert (ledger[0]["kind"], ledger[0]["kind_source"]) == ("variable", "category")


def test_frequent_merchant_repeat_amount_is_not_fixed():
    """A ₪29 Wolt order on different days in three months is a coincidence, not a bill."""
    ledger = [row("2026-07-03", -29.0, "WOLT"), row("2026-08-17", -29.0, "WOLT"),
              row("2026-09-25", -29.0, "WOLT")]
    cat.stamp(ledger)
    assert not any(t.get("recurring") for t in ledger)
    assert {t["kind"] for t in ledger} == {"variable"}


def test_weekly_grocery_order_of_similar_size_is_not_fixed():
    """כרמלה delivers ~₪200 several times a month: variable groceries."""
    ledger = [row(f"2026-{m:02d}-{d:02d}", -200.0, "כרמלה") for m in (6, 7, 8) for d in (2, 5, 9, 16)]
    cat.stamp(ledger)
    assert not any(t.get("recurring") for t in ledger)


def test_riseup_fixed_envelope_makes_an_installment_fixed():
    """ח.י אלקטרוניקה ₪230.75 is an installment RiseUp keeps in a fixed envelope."""
    ledger = [row("2026-09-02", -230.75, "ח.י אלקטרוניקה -טרקלין חש", category="תשלומים", budget_type="fixed")]
    cat.stamp(ledger)
    assert (ledger[0]["category"], ledger[0]["kind"], ledger[0]["kind_source"]) == ("מוצרי חשמל לבית", "fixed", "riseup")


def test_non_expenses_have_no_kind():
    ledger = [row("2026-09-10", 26428.43, "העברת משכורת", category="משכורת", is_income=True),
              row("2026-09-10", -4329.0, "ל.מאסטרקרד(יש)", card_bill_payment=True),
              row("2026-09-20", -250.0, "הראל פנסיה חיוב")]
    cat.stamp(ledger)
    assert [t.get("kind") for t in ledger] == [None, None, None]
    assert ledger[2]["category"] == "השקעה וחיסכון"


def test_overdraft_interest_is_a_variable_loan_cost():
    ledger = monthly("תשלום ריבית על משיכת יתר- מינוס", -63.0, range(6, 10), day=1)
    cat.stamp(ledger)
    assert {(t["category"], t["kind"]) for t in ledger} == {("הלוואה", "variable")}


def test_loan_payoff_next_to_the_installment_is_a_one_off():
    """פירעון הלוואה 15500316168: ₪311 every month is fixed; the ₪52,312.43 payoff on
    2026-06-07 is a one-off, so variable, though הלוואה defaults to fixed."""
    desc = "פירעון הלוואה 15500316168"
    ledger = monthly(desc, -311.21, range(3, 10), category="הלוואה")
    ledger.append(row("2026-06-07", -52312.43, desc, category="הלוואה"))
    cat.stamp(ledger)
    assert {(t["kind"], t["kind_source"]) for t in ledger[:-1]} == {("fixed", "recurring")}
    assert (ledger[-1]["kind"], ledger[-1]["kind_source"]) == ("variable", "one_off")


def test_a_new_subscription_is_fixed_by_its_category():
    """A second month of a new service has no history yet: דיגיטל defaults to fixed."""
    ledger = [row("2026-09-12", -61.0, "CURSOR"), row("2026-10-12", -61.0, "CURSOR")]
    cat.stamp(ledger)
    assert {(t["category"], t["kind"], t["kind_source"]) for t in ledger} == {("דיגיטל", "fixed", "category")}


def test_card_only_row_takes_the_merchants_usual_category():
    """שומשום בר ₪50.73, a recent amex-only row labelled "עסקאות רגילות", is אוכל בעבודה
    like the merchant's other rows that RiseUp categorised."""
    ledger = [row("2026-09-14", -37.0, "שומשום בר בריאות", category="אוכל בחוץ", budget_category="אוכל בעבודה"),
              row("2026-09-21", -41.0, "שומשום בר בריאות", category="אוכל בחוץ", budget_category="אוכל בעבודה"),
              row("2026-10-20", -50.73, "שומשום בר בריאות", category="עסקאות רגילות", sources=["amex"])]
    cat.stamp(ledger)
    assert ledger[-1]["category"] == "אוכל בעבודה"


def test_the_accountant_is_a_fixed_business_expense():
    """בן חיים אד חיוב ₪354 a month from the business account is the accountant."""
    ledger = [row("2026-09-02", -354.0, "בן חיים אד חיוב", sources=["discount-business"])]
    cat.stamp(ledger)
    assert (ledger[0]["category_group"], ledger[0]["category"], ledger[0]["kind"]) == (
        "עבודה ולימודים", "הוצאות עסק", "fixed")


def test_levers_follow_the_taxonomy():
    """The "what can I cut?" grouping is the category's, not a RiseUp label set."""
    assert cat.lever("עמלות")[0] == "fees"              # דמי כרטיס /הנפקה ₪102.38
    assert cat.lever("דיגיטל")[0] == "subscriptions"    # SPOTIFY ₪43.90
    assert cat.lever("תקשורת")[0] == "bills"            # פרטנר ₪135.14
    assert cat.lever("שכר דירה")[0] == "committed"      # rent ₪6,800
    assert cat.lever("הלוואה", "תשלומים")[0] == "committed"
    assert cat.lever("רכב", "תשלומים")[0] == "installments"   # Metro Motor ₪500
    assert cat.lever("ביטוח", "תשלומים")[0] == "bills"        # ליברה premium ₪30
    assert cat.lever("הוצאות עסק")[0] == "other"        # the accountant ₪354
    assert [key for key, *_ in cat.LEVERS][-1] == "other"


def test_bill_kind_and_tracking_names():
    assert cat.bill_kind("משכנתא") == "loan" and cat.bill_kind("דיגיטל") == "subscription"
    assert cat.bill_kind("ספר") == "bill"
    assert cat.tracking_category("חופשה ✈️") == "תיירות"
    assert cat.tracking_category("תחבורה") == "תחבורה"        # a whole group
    assert cat.tracking_category("wellness ") == "wellness"
    assert cat.tracking_category("__saving-hidden-category__") is None


def test_envelope_label_and_ledger_category():
    """A RiseUp envelope payee: merchant default > RiseUp label; the ledger's latest
    category for the payee (with the household's edits) wins over both."""
    assert cat.label_category('הו"ק לעיין ניהול נכסי,לסניף 20-406', "דיור") == "שכר דירה"
    assert cat.label_category("פרטנר תקשורת בע\"מ", "תקשורת") == "תקשורת"
    assert cat.label_category("הו\"ק לששון ירין", "תשלומים") is None
    known = cat.ledger_categories([
        row("2026-10-14", -59.5, "APPLE.COM/BILL         CORK    ", category="פנאי"),
        row("2026-10-15", -59.5, "APPLE.COM/BILL", category="דיגיטל"),
    ])
    assert known == {"APPLE.COM/BILL": "דיגיטל"}


def test_the_barber_is_fixed():
    """גורביץ מרק (₪120–240 a month) is the monthly barber: קבוע, so it is a bill."""
    ledger = [row("2026-09-20", -200.0, "גורביץ מרק", category="ספר")]
    cat.stamp(ledger)
    assert (ledger[0]["category"], ledger[0]["kind"], ledger[0]["kind_source"]) == ("ספר", "fixed", "merchant")
