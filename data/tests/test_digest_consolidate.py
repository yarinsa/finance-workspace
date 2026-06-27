"""Real-case tests for digest.consolidate_transactions and spending_summary.

Cases mirror the dedup rules in CLAUDE.md: same purchase = (date, abs amount);
RiseUp wins on conflict and carries the category; sources are unioned; exclusion
flags are re-evaluated on the merged row (never OR-ed across colliding legs).
"""
import digest


def raw(source, date, amount, description="", **extra):
    return {"_source": source, "date": date, "amount": amount,
            "description": description, **extra}


class TestDedup:
    def test_riseup_and_bank_copy_of_same_purchase_collapse_to_one_row(self):
        ledger = digest.consolidate_transactions([
            raw("cal", "2026-06-01", -120.0, "שופרסל"),
            raw("riseup", "2026-06-01", -120.0, "שופרסל דיל", origin="cal", category="מזון"),
        ])
        assert len(ledger) == 1
        row = ledger[0]
        assert sorted(row["sources"]) == ["cal", "riseup"]
        # RiseUp wins descriptive fields — it carries the category the bank lacks.
        assert row["category"] == "מזון"
        assert row["origin"] == "cal"

    def test_different_amounts_same_day_stay_separate(self):
        ledger = digest.consolidate_transactions([
            raw("cal", "2026-06-01", -120.0, "א"),
            raw("cal", "2026-06-01", -55.0, "ב"),
        ])
        assert len(ledger) == 2

    def test_bank_backfills_fields_riseup_is_missing(self):
        ledger = digest.consolidate_transactions([
            raw("riseup", "2026-06-02", -200.0, "", origin="cal"),
            raw("cal", "2026-06-02", -200.0, "חיוב מסעדה", card_last4="1234"),
        ])
        row = ledger[0]
        assert row["card_last4"] == "1234"          # backfilled from the bank copy
        assert row["description"] == "חיוב מסעדה"


class TestDedupEdgeCases:
    def test_empty_input(self):
        assert digest.consolidate_transactions([]) == []

    def test_three_sources_collide_into_one_row(self):
        # RiseUp + both a bank and a card copy of the same purchase.
        ledger = digest.consolidate_transactions([
            raw("amex", "2026-06-01", -50.0, "bank"),
            raw("cal", "2026-06-01", -50.0, "card", card_last4="9999"),
            raw("riseup", "2026-06-01", -50.0, "rise", origin="cal", category="מזון"),
        ])
        assert len(ledger) == 1
        row = ledger[0]
        assert sorted(row["sources"]) == ["amex", "cal", "riseup"]
        assert row["category"] == "מזון"           # RiseUp still wins descriptive fields
        assert row["card_last4"] == "9999"          # backfilled from the card leg

    def test_riseup_wins_regardless_of_insertion_order(self):
        # Order must not change the outcome: RiseUp's category/description win and
        # the bank leg's card_last4 is backfilled either way.
        bank = raw("cal", "2026-06-01", -50.0, "bank", card_last4="9999")
        rise = raw("riseup", "2026-06-01", -50.0, "rise", origin="cal", category="מזון")
        for recs in ([bank, rise], [rise, bank]):
            row = digest.consolidate_transactions(recs)[0]
            assert row["description"] == "rise"
            assert row["category"] == "מזון"
            assert row["card_last4"] == "9999"

    def test_two_riseup_copies_keep_first_and_do_not_duplicate(self):
        # Neither copy outranks the other (both _riseup), so the first stays winner;
        # the row must not split into two.
        ledger = digest.consolidate_transactions([
            raw("riseup", "2026-06-01", -50.0, "first", origin="cal", category="A"),
            raw("riseup", "2026-06-01", -50.0, "second", origin="cal", category="B"),
        ])
        assert len(ledger) == 1
        assert ledger[0]["description"] == "first"
        assert ledger[0]["sources"] == ["riseup"]

    def test_amounts_collapse_after_rounding_to_two_places(self):
        # The key rounds abs(amount) to 2dp, so sub-cent differences are the same row.
        ledger = digest.consolidate_transactions([
            raw("cal", "2026-06-01", -120.001, "a"),
            raw("cal", "2026-06-01", -120.004, "b"),
        ])
        assert len(ledger) == 1

    def test_same_day_equal_refund_and_charge_collapse(self):
        # Known tradeoff of the (date, abs amount) key: a +X refund and a -X charge
        # on the same day merge into one row. Pin it so the behavior is intentional,
        # not an accident — if we ever sign-qualify the key, this test must change.
        ledger = digest.consolidate_transactions([
            raw("cal", "2026-06-01", -150.0, "charge"),
            raw("cal", "2026-06-01", 150.0, "refund"),
        ])
        assert len(ledger) == 1

    def test_same_amount_different_days_stay_separate(self):
        ledger = digest.consolidate_transactions([
            raw("cal", "2026-06-01", -150.0, "a"),
            raw("cal", "2026-06-02", -150.0, "b"),
        ])
        assert len(ledger) == 2

    def test_output_is_sorted_newest_first(self):
        ledger = digest.consolidate_transactions([
            raw("cal", "2026-06-01", -10.0, "old"),
            raw("cal", "2026-06-15", -20.0, "new"),
            raw("cal", "2026-06-09", -30.0, "mid"),
        ])
        assert [r["date"] for r in ledger] == ["2026-06-15", "2026-06-09", "2026-06-01"]

    def test_winner_origin_is_not_overwritten_by_backfill(self):
        # Backfill only fills *falsy* fields, so a RiseUp row that already mapped its
        # origin keeps it even when the other leg's origin differs.
        ledger = digest.consolidate_transactions([
            raw("riseup", "2026-06-01", -50.0, "rise", origin="cal", category="X"),
            raw("amex", "2026-06-01", -50.0, "card"),
        ])
        assert ledger[0]["origin"] == "cal"


class TestMergedFlagReevaluation:
    def test_colliding_purchase_and_self_transfer_do_not_taint_each_other(self):
        # A real purchase and a same-day same-value self-transfer collide on the
        # dedup key. The surviving row's flag must reflect ITS description only.
        ledger = digest.consolidate_transactions([
            raw("riseup", "2026-06-03", -500.0, "ספק כלשהו", origin="cal", category="קניות"),
            raw("discount", "2026-06-03", -500.0, "העברה לירין ששון"),
        ])
        row = ledger[0]
        # RiseUp's purchase description wins -> not flagged internal.
        assert not row.get("internal_transfer")
        assert row["category"] == "קניות"


class TestSpendingSummary:
    def test_excluded_rows_are_not_spend(self):
        ledger = digest.consolidate_transactions([
            raw("discount", "2026-06-01", -100.0, "שופרסל"),
            raw("discount", "2026-06-02", -8000.0, "חיוב ויזה כ.א.ל"),   # card bill
            raw("discount", "2026-06-03", -5000.0, "העברה לירין ששון"),   # internal
            raw("discount", "2026-06-04", -2000.0, "הפקדה לפיקדון"),       # savings
            raw("riseup", "2026-06-05", 20000.0, "משכורת", is_income=True),
        ])
        s = digest.spending_summary(ledger)
        assert s["total_spent"] == 100.0
        assert s["total_income"] == 20000.0
        assert s["total_saved"] == 2000.0
        assert s["card_bill_payments_excluded"] == 1
        assert s["internal_transfers_excluded"] == 1
        assert s["savings_deposits"] == 1

    def test_spend_is_grouped_by_category(self):
        ledger = digest.consolidate_transactions([
            raw("riseup", "2026-06-01", -100.0, "א", category="מזון"),
            raw("riseup", "2026-06-02", -40.0, "ב", category="מזון"),
            raw("riseup", "2026-06-03", -250.0, "ג", category="תחבורה"),
        ])
        s = digest.spending_summary(ledger)
        assert s["by_category"] == {"מזון": 140.0, "תחבורה": 250.0}
