"""The apartment's hand-typed value and the daily position history (db/asset_store.py,
db/position_store.py), against the throwaway test database."""
import datetime as dt

import pytest

import asset_store
import position_store


def test_property_value_is_created_then_revalued_today(conn):
    a = asset_store.create_asset(conn, "property", "דירה בבת ים", 2_350_000, dt.date(2026, 10, 1))
    assert (a["value"], a["valued_at"], a["valuation_source"]) == (2_350_000.0, "2026-10-01", "manual")

    b = asset_store.update_asset(conn, a["id"], value="2400000.00")
    assert b["value"] == 2_400_000.0
    assert b["valued_at"] == dt.date.today().isoformat()     # a new value is a new valuation
    assert asset_store.all_assets(conn) == [b]


def test_asset_rejects_negative_value_and_unknown_kind(conn):
    with pytest.raises(ValueError):
        asset_store.create_asset(conn, "car", "רכב", 50_000)
    a = asset_store.create_asset(conn, "property", "דירה", 1)
    with pytest.raises(ValueError):
        asset_store.update_asset(conn, a["id"], value=-5)
    assert asset_store.update_asset(conn, 99_999, value=1) is None


def test_position_of_a_day_is_overwritten_by_a_later_digest(conn):
    # 2026-10-27 snapshot.totals: bank 3,984.68, cards 4,092.23, loans 114,240.26 (after the
    # Leumi duplicate fix), mortgage 1,418,853.49, savings 639,880.88, no property yet.
    day = dt.date(2026, 10, 27)
    position_store.record(conn, day, cash=3984.68, card_debt=4092.23, consumer_loans=127566.17,
                          mortgage=1418853.49, savings=639880.88, property=None, net_worth=-906646.33)
    position_store.record(conn, day, cash=3984.68, card_debt=4092.23, consumer_loans=114240.26,
                          mortgage=1418853.49, savings=639880.88, property=None, net_worth=-893320.42)
    [row] = position_store.series(conn)
    assert row["date"] == "2026-10-27"
    assert row["consumer_loans"] == 114240.26
    assert row["property"] is None
