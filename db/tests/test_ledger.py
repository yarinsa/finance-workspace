"""Tests for the two-layer transactions database.

The rows are made up but shaped like ledger entries (no household data). The
property under test is the reason the database exists: a re-import of the scraped ledger never loses a human edit.
"""
import json

import edit
import goal_store
from finance import categories as taxonomy
import ledger
import offset_store
import overrides
import tags

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


VIEW_ADDED = ("category_id", "horizon_id", "category_group", "kind", "kind_source")


def plain(rows):
    """Ledger rows without the ids, group and kind the view adds (these rows were not
    stamped by the digest; see test_digest_stamped_rows_round_trip_unchanged)."""
    return [{f: v for f, v in r.items() if f not in VIEW_ADDED} for r in rows]


def test_round_trip_without_overrides_is_identity(conn):
    # No edits: digest must get back exactly what it sent, in the same order.
    assert plain(ledger.sync(conn, LEDGER)) == LEDGER


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
    assert plain(out[1:]) == [SALARY, CARD_BILL]


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
    assert plain(ledger.sync(conn, LEDGER)) == LEDGER          # empty override is pruned
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


def test_taxonomy_seeds_the_table_and_rows_are_assigned_by_id(conn):
    # finance/categories.py is the list; each row points at one of its categories by id.
    out = ledger.sync(conn, LEDGER)
    ids = dict(conn.execute("SELECT name, id FROM categories WHERE source = 'builtin'").fetchall())
    assert set(ids) == set(taxonomy.CATEGORY_GROUP)
    assert [r.get("category_id") for r in out] == [ids["קניות"], ids["משכורת"], None]
    assert conn.execute("SELECT g.name FROM categories c JOIN category_groups g ON g.id = c.group_id "
                        "WHERE c.name = 'דלק'").fetchone()[0] == "תחבורה"


def test_a_card_sector_label_is_mapped_for_a_row_riseup_never_saw(conn):
    # As the household, a CAL row RiseUp never saw ("תיירות יוצאת קניות") is still
    # categorised: the card's sector maps into the one taxonomy (it used to be dropped).
    bank_only = {"date": "2026-01-20", "amount": -80.0, "description": "חנות בחו\"ל",
                 "category": "תיירות יוצאת קניות", "origin": "cal", "sources": ["cal"]}
    taxonomy.stamp([bank_only])
    row = ledger.sync(conn, [bank_only])[0]
    assert (row["category_group"], row["category"], row["kind"]) == ("פנאי", "תיירות", "variable")
    assert conn.execute("SELECT count(*) FROM categories WHERE name = 'תיירות יוצאת קניות'").fetchone()[0] == 0


def test_an_unmapped_source_label_is_kept_without_a_group(conn):
    row = ledger.sync(conn, [{"date": "2026-01-20", "amount": -40.0, "description": "חנות חיות",
                              "category": "חיות מחמד", "sources": ["riseup"]}])[0]
    assert row["category"] == "חיות מחמד" and "category_group" not in row
    assert conn.execute("SELECT source FROM categories WHERE name = 'חיות מחמד'").fetchone()[0] == "riseup"


# --- kind: fixed (קבוע) / variable (משתנה) ---------------------------------------------

METRO = {"date": "2026-10-02", "amount": -500.0, "description": "מטרו מוטור שווק (1981)בעמ",
         "category": "תשלומים", "origin": "cal", "is_income": False, "sources": ["cal", "riseup"],
         "budget_type": "fixed"}   # RiseUp's fixed envelope "מטרו מוטור"
FUEL = {"date": "2026-10-05", "amount": -36.88, "description": "פז אפליקצית-YELLOW",
        "category": "רכב", "origin": "amex", "is_income": False, "sources": ["amex", "riseup"]}
SPOTIFY = [{"date": f"2026-{m:02d}-09", "amount": -43.9, "description": "SpotifyIL", "category": "דיגיטל",
            "origin": "cal", "is_income": False, "sources": ["riseup"]} for m in (7, 8, 9)]


def stamped(rows):
    rows = [dict(r) for r in rows]
    taxonomy.stamp(rows)
    return rows


def test_digest_stamped_rows_round_trip_unchanged(conn):
    # The digest (no DB) and the view (DB) must give the same category, group and kind.
    rows = stamped([METRO, FUEL, *SPOTIFY, CAL_PURCHASE, SALARY, CARD_BILL])
    out = ledger.sync(conn, rows)
    assert [{f: v for f, v in r.items() if f not in ("category_id", "horizon_id")} for r in out] == rows
    assert [(r["category"], r.get("kind"), r.get("kind_source")) for r in out[:3]] == [
        ("רכב", "fixed", "riseup"), ("דלק", "variable", "category"), ("דיגיטל", "fixed", "recurring")]


def test_kind_override_beats_the_default_and_survives_reimport(conn):
    rows = stamped([FUEL])
    ledger.load(conn, rows)
    edit.set_field(conn, k(FUEL), "kind", "fixed")
    row = ledger.sync(conn, rows)[0]
    assert (row["kind"], row["kind_source"], row["overridden"]) == ("fixed", "manual", True)
    edit.set_field(conn, k(FUEL), "kind", None)
    assert conn.execute("SELECT count(*) FROM transaction_overrides").fetchone()[0] == 0


def test_merchant_rule_applies_to_every_row_of_the_merchant(conn):
    # As the household, "every פז אפליקצית-YELLOW is fuel I fill monthly at a fixed ₪37"
    # is one rule, not an edit per transaction; a single override still wins.
    second = {**FUEL, "date": "2026-09-05", "amount": -34.27}
    rows = stamped([FUEL, second])
    ledger.load(conn, rows)
    overrides.set_merchant_rule(conn, rows[0]["merchant"], {"kind": "fixed", "category": "רכב"}, "test")
    edit.set_field(conn, k(second), "kind", "variable")
    out = ledger.materialize(conn)
    assert [(r["category"], r["kind"], r["kind_source"]) for r in out] == [
        ("רכב", "fixed", "rule"), ("רכב", "variable", "manual")]
    audit = conn.execute("SELECT field, new FROM override_audit WHERE txn_date IS NULL ORDER BY id").fetchall()
    assert audit == [(f"merchant_rule.category:{rows[0]['merchant']}", "רכב"),
                     (f"merchant_rule.kind:{rows[0]['merchant']}", "fixed")]


def test_empty_merchant_rule_is_deleted(conn):
    overrides.set_merchant_rule(conn, "WOLT", {"kind": "fixed"}, "test")
    assert overrides.set_merchant_rule(conn, "WOLT", {"kind": None}, "test") is None
    assert conn.execute("SELECT count(*) FROM merchant_rules").fetchone()[0] == 0


def test_recategorising_to_a_usage_based_category_makes_it_variable(conn):
    # Spotify recurs (fixed); moved by hand into groceries (usage-based) it follows usage.
    rows = stamped(SPOTIFY)
    ledger.load(conn, rows)
    edit.set_field(conn, k(rows[0]), "category", "כלכלה")
    row = ledger.materialize(conn)[0]
    assert (row["category_group"], row["kind"], row["kind_source"]) == ("אוכל", "variable", "category")


def test_non_expenses_have_no_kind(conn):
    out = ledger.sync(conn, stamped([SALARY, CARD_BILL]))
    assert [r.get("kind") for r in out] == [None, None]


def test_legacy_alias_category_moves_its_overrides(conn):
    # An override that pointed at RiseUp's "עמלת דמי כרטיס - בנקים" ends up on עמלות.
    conn.execute("INSERT INTO categories (name, source) VALUES ('עמלת דמי כרטיס - בנקים', 'riseup')")
    ledger.load(conn, [CAL_PURCHASE])
    edit.set_field(conn, k(CAL_PURCHASE), "category", "עמלת דמי כרטיס - בנקים")
    ledger.load(conn, [CAL_PURCHASE])
    assert ledger.materialize(conn)[0]["category"] == "עמלות"
    assert conn.execute("SELECT count(*) FROM categories WHERE name = 'עמלת דמי כרטיס - בנקים'").fetchone()[0] == 0


def test_manual_category_is_added_as_a_user_category(conn):
    ledger.load(conn, LEDGER)
    edit.set_field(conn, k(CAL_PURCHASE), "category", "אלקטרוניקה")
    assert conn.execute("SELECT source FROM categories WHERE name = 'אלקטרוניקה'").fetchone()[0] == "user"


# --- tags ----------------------------------------------------------------------------

def test_tags_survive_reimport_and_reach_the_ledger_sorted(conn):
    # As the household, I tag the 123.45 charge for a trip; the next scrape keeps it.
    ledger.load(conn, LEDGER)
    assert tags.set_tags(conn, k(CAL_PURCHASE), ["טיול", "החזר"], "cli") == ["החזר", "טיול"]
    out = ledger.sync(conn, LEDGER)
    assert out[0]["tags"] == ["החזר", "טיול"]
    assert "tags" not in out[1]                     # untagged rows don't grow a field
    assert plain([{f: v for f, v in r.items() if f != "tags"} for r in out]) == LEDGER


def test_set_tags_replaces_the_set_and_audits_each_change(conn):
    ledger.load(conn, LEDGER)
    tags.set_tags(conn, k(CAL_PURCHASE), ["טיול", "החזר"], "cli")
    tags.set_tags(conn, k(CAL_PURCHASE), ["טיול", "עבודה"], "cli")
    assert tags.tags_of(conn, k(CAL_PURCHASE)) == ["טיול", "עבודה"]
    audit = conn.execute("SELECT old, new FROM override_audit WHERE field = 'tags' ORDER BY id").fetchall()
    assert audit == [(None, "החזר"), (None, "טיול"), ("החזר", None), (None, "עבודה")]
    assert {t["name"]: t["count"] for t in tags.all_tags(conn)} == {"החזר": 0, "טיול": 1, "עבודה": 1}


def test_a_tag_is_shared_between_transactions_and_deleting_it_unlinks_both(conn):
    ledger.load(conn, LEDGER)
    tags.set_tags(conn, k(CAL_PURCHASE), ["טיול"], "cli")
    tags.set_tags(conn, k(SALARY), ["טיול"], "cli")
    [tag] = tags.all_tags(conn)
    assert tag["count"] == 2
    assert tags.delete_tag(conn, tag["id"])
    assert conn.execute("SELECT count(*) FROM transaction_tags").fetchone()[0] == 0
    assert all("tags" not in r for r in ledger.materialize(conn))


def test_tag_whose_transaction_vanished_is_reported_orphaned(conn):
    # The bank corrects the charge to 123.40: the tag is kept, and listed as orphaned.
    ledger.load(conn, LEDGER)
    tags.set_tags(conn, k(CAL_PURCHASE), ["טיול"], "cli")
    ledger.sync(conn, [{**CAL_PURCHASE, "amount": -123.40}, SALARY, CARD_BILL])
    assert tags.orphaned(conn) == [{"date": "2026-01-15", "abs_amount": "123.45", "tag": "טיול"}]


def test_orm_session_shares_the_connection_and_never_closes_it(conn):
    s = ledger.orm_session(conn)
    s.close()
    assert conn.execute("SELECT 1").fetchone() == (1,)


# --- horizons and goals --------------------------------------------------------------

def test_digest_horizon_default_is_assigned_by_id_and_an_override_replaces_it(conn):
    # The digest stamps the 123.45 charge "current"; I move it to "near" by hand.
    rows = [{**CAL_PURCHASE, "horizon": "current"}, SALARY, CARD_BILL]
    ledger.load(conn, rows)
    ids = dict(conn.execute("SELECT key, id FROM horizons").fetchall())
    assert conn.execute("SELECT horizon_id FROM scraped_transactions WHERE amount < -100 AND amount > -200"
                        ).fetchone()[0] == ids["current"]
    edit.set_field(conn, k(CAL_PURCHASE), "horizon", "near")
    out = ledger.sync(conn, rows)
    assert (out[0]["horizon"], out[0]["horizon_id"]) == ("near", ids["near"])
    assert overrides.get_row(conn, k(CAL_PURCHASE))["horizon"] == "near"
    edit.set_field(conn, k(CAL_PURCHASE), "horizon", None)   # back to the digest's default
    assert ledger.materialize(conn)[0]["horizon"] == "current"


def test_horizons_are_the_three_seeded_buckets_in_order(conn):
    assert [h["key"] for h in goal_store.horizons(conn)] == ["current", "near", "future"]


def test_goal_gets_a_horizon_and_a_transaction_can_go_to_it(conn):
    # As the household, the phone I bought on 2026-01-15 is the "החלפת טלפון" goal.
    ledger.load(conn, LEDGER)
    g = goal_store.create_goal(conn, "החלפת טלפון", 3000, slug="phone-2026", end_date="2026-11-23",
                               horizon="near")
    assert (g["horizon"], g["end_date"]) == ("near", "2026-11-23")
    row = overrides.patch(conn, k(CAL_PURCHASE), {"goal_id": g["id"]}, "cli")
    assert (row["goal_id"], row["goal"]) == (g["id"], "החלפת טלפון")
    assert ledger.materialize(conn)[0]["goal"] == "החלפת טלפון"
    assert goal_store.all_goals(conn)[0]["transactions"] == 1
    assert goal_store.update_goal(conn, g["id"], horizon="future")["horizon"] == "future"
    assert goal_store.delete_goal(conn, g["id"])
    assert "goal" not in ledger.materialize(conn)[0]
    assert overrides.get_override(conn, k(CAL_PURCHASE)) is None   # the now-empty override is pruned


def test_patch_rejects_an_unknown_goal(conn):
    ledger.load(conn, LEDGER)
    try:
        overrides.patch(conn, k(CAL_PURCHASE), {"goal_id": 999}, "cli")
    except ValueError as e:
        assert "999" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_goals_are_imported_once_from_the_json_store(conn, tmp_path):
    store = tmp_path / "goals.json"
    store.write_text(json.dumps({"goals": [
        {"id": "phone-2026", "description": "החלפת טלפון", "amount": 3000, "start_date": "2026-01-01",
         "end_date": "2026-11-23", "interval": None, "repetitions": 1, "rise": 0, "from_asset_id": None}]}),
        encoding="utf-8")
    assert goal_store.import_json(conn, store) == 1
    assert goal_store.import_json(conn, store) == 0      # re-running adds nothing
    [g] = goal_store.all_goals(conn)
    assert (g["slug"], g["amount"], g["horizon"]) == ("phone-2026", 3000.0, "near")


# --- offsets (קיזוז) -----------------------------------------------------------
FRIEND_BIT = {"date": "2026-01-20", "amount": 100.0, "description": "העברה מחבר",
              "origin": "discount", "is_income": True, "sources": ["discount"]}


def test_a_manual_offset_survives_reimport_and_rides_on_the_payback(conn):
    # As the household, a friend's ₪100 paid back part of the 123.45 dinner.
    rows = [CAL_PURCHASE, SALARY, CARD_BILL, FRIEND_BIT]
    ledger.load(conn, rows)
    stored = offset_store.set_offsets(conn, k(FRIEND_BIT), [(k(CAL_PURCHASE), 100)], "cli")
    assert stored == [{"date": "2026-01-15", "abs_amount": "123.45", "amount": "100.00"}]
    out = ledger.sync(conn, rows)
    assert out[3]["manual_offsets"] == [{"date": "2026-01-15", "abs_amount": 123.45, "amount": 100.0,
                                         "kind": "manual"}]
    assert all("manual_offsets" not in r for r in out[:3])


def test_an_empty_offset_decision_is_stored_and_reset_returns_to_auto(conn):
    ledger.load(conn, [CAL_PURCHASE, FRIEND_BIT])
    offset_store.set_offsets(conn, k(FRIEND_BIT), [], "cli")
    assert offset_store.offsets_of(conn, k(FRIEND_BIT)) == []
    assert ledger.materialize(conn)[1]["manual_offsets"] == []
    offset_store.reset_offsets(conn, k(FRIEND_BIT), "cli")
    assert offset_store.offsets_of(conn, k(FRIEND_BIT)) is None
    audit = conn.execute("SELECT old, new FROM override_audit WHERE field = 'offsets' ORDER BY id").fetchall()
    assert audit == [("auto", []), ([], "auto")]


def test_offset_amounts_must_be_positive_and_each_expense_linked_once(conn):
    import pytest
    ledger.load(conn, [CAL_PURCHASE, FRIEND_BIT])
    with pytest.raises(ValueError):
        offset_store.set_offsets(conn, k(FRIEND_BIT), [(k(CAL_PURCHASE), 0)], "cli")
    with pytest.raises(ValueError):
        offset_store.set_offsets(conn, k(FRIEND_BIT), [(k(CAL_PURCHASE), 50), (k(CAL_PURCHASE), 50)], "cli")


def test_offset_whose_expense_vanished_is_reported_orphaned(conn):
    ledger.load(conn, [CAL_PURCHASE, FRIEND_BIT])
    offset_store.set_offsets(conn, k(FRIEND_BIT), [(k(CAL_PURCHASE), 100)], "cli")
    ledger.sync(conn, [{**CAL_PURCHASE, "amount": -123.40}, FRIEND_BIT])
    [(missing_payback, missing_expense)] = conn.execute(
        "SELECT payback_missing, expense_missing FROM orphaned_offsets").fetchall()
    assert (missing_payback, missing_expense) == (False, True)


# --- plan targets --------------------------------------------------------------------

def test_targets_start_unset_and_unset_is_a_zero_row(conn):
    assert goal_store.get_targets(conn) == {"emergency_fund_target": None, "inheritance_target": None,
                                            "retirement_target": None}
    out = goal_store.set_targets(conn, emergency_fund_target=60000, retirement_target=2500000.5)
    assert out == {"emergency_fund_target": 60000.0, "inheritance_target": None,
                   "retirement_target": 2500000.5}
    goal_store.set_targets(conn, emergency_fund_target=65000)   # update in place
    assert goal_store.get_targets(conn)["emergency_fund_target"] == 65000.0
    goal_store.set_targets(conn, emergency_fund_target=None, retirement_target=0)   # None and 0 both unset
    assert goal_store.get_targets(conn) == {"emergency_fund_target": None, "inheritance_target": None,
                                            "retirement_target": None}
    # unsetting keeps the row (amount 0) so it differs from "never decided"
    assert goal_store.stored_targets(conn) == {"emergency_fund_target": 0.0, "retirement_target": 0.0}


def test_set_targets_rejects_bad_input_without_writing(conn):
    for bad in ({"emergency_fund_target": 1, "retirement_target": -5}, {"nope_target": 1}):
        try:
            goal_store.set_targets(conn, **bad)
        except ValueError:
            pass
        else:
            raise AssertionError(bad)
    assert goal_store.get_targets(conn)["emergency_fund_target"] is None


def test_import_json_copies_targets_but_keeps_ones_with_a_row(conn, tmp_path):
    store = tmp_path / "goals.json"
    store.write_text('{"emergency_fund_target": 60000, "inheritance_target": 1000000, '
                     '"retirement_target": 0, "goals": []}')
    goal_store.set_targets(conn, inheritance_target=750000, retirement_target=None)
    goal_store.import_json(conn, store)
    assert goal_store.get_targets(conn) == {"emergency_fund_target": 60000.0,
                                            "inheritance_target": 750000.0, "retirement_target": None}
