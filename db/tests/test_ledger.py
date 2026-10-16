"""Tests for the two-layer transactions database.

The rows are made up but shaped like ledger entries (no household data). The
property under test is the reason the database exists: a re-import of the scraped ledger never loses a human edit.
"""
import edit
import ledger

# Made-up rows in the digested ledger's shape.
CAL_PURCHASE = {"date": "2026-01-15", "amount": -123.45, "description": "חנות לדוגמה",
                "category": "קניות", "origin": "cal", "is_income": False, "sources": ["riseup"]}
SALARY = {"date": "2026-01-10", "amount": 1000.0, "description": "העברת משכורת",
          "category": "משכורת", "origin": "discount", "is_income": True, "sources": ["discount", "riseup"]}
CARD_BILL = {"date": "2026-01-02", "amount": -500.0, "description": "כאל-חיוב לכרטיס",
             "origin": "discount", "is_income": False, "sources": ["discount"], "card_bill_payment": True}
LEDGER = [CAL_PURCHASE, SALARY, CARD_BILL]


def k(t):
    return ledger.key(t["date"], t["amount"])


def test_round_trip_without_overrides_is_identity(conn):
    # No edits: digest must get back exactly what it sent, in the same order.
    assert ledger.sync(conn, LEDGER) == LEDGER


def test_category_override_survives_reimport(conn):
    # As the household, when I recategorise the 123.45 CAL charge, a fresh scrape
    # (which still says קניות) must not undo it.
    ledger.load(conn, LEDGER)
    edit.set_field(conn, k(CAL_PURCHASE), "category", "אלקטרוניקה")
    out = ledger.sync(conn, LEDGER)
    row = out[0]
    assert row["category"] == "אלקטרוניקה"
    assert row["overridden"] is True
    assert row["description"] == CAL_PURCHASE["description"]   # untouched fields fall through
    assert out[1:] == [SALARY, CARD_BILL]


def test_scraper_updates_still_flow_through_unedited_fields(conn):
    # Sparse overrides: a later scrape that fixes the description still shows up.
    ledger.load(conn, LEDGER)
    edit.set_field(conn, k(CAL_PURCHASE), "note", "gift")
    fixed = {**CAL_PURCHASE, "description": "חנות לדוגמה בע\"מ"}
    row = ledger.sync(conn, [fixed, SALARY, CARD_BILL])[0]
    assert row["description"] == fixed["description"]
    assert row["note"] == "gift"


def test_excluded_row_is_hidden_and_include_restores_it(conn):
    ledger.load(conn, LEDGER)
    edit.set_field(conn, k(SALARY), "excluded", True)
    assert [t["date"] for t in ledger.sync(conn, LEDGER)] == ["2026-01-15", "2026-01-02"]
    edit.set_field(conn, k(SALARY), "excluded", False)
    assert ledger.sync(conn, LEDGER) == LEDGER                 # empty override is pruned
    assert conn.execute("SELECT count(*) FROM transaction_overrides").fetchone()[0] == 0


def test_key_ignores_sign_like_the_dedup_key(conn):
    # Addressing the charge as 123.45 (positive) hits the -123.45 row.
    ledger.load(conn, LEDGER)
    edit.set_field(conn, ledger.key("2026-01-15", "123.45"), "category", "אלקטרוניקה")
    assert ledger.materialize(conn)[0]["category"] == "אלקטרוניקה"


def test_override_whose_transaction_vanished_is_reported_orphaned(conn):
    # A bank corrects the charge to 123.40: the edit no longer matches any row.
    ledger.load(conn, LEDGER)
    edit.set_field(conn, k(CAL_PURCHASE), "category", "אלקטרוניקה")
    ledger.sync(conn, [{**CAL_PURCHASE, "amount": -123.40}, SALARY, CARD_BILL])
    orphans = ledger.orphaned(conn)
    assert [(str(d), str(a)) for d, a, *_ in orphans] == [("2026-01-15", "123.45")]
