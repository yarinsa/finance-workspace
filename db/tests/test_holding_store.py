"""Hand assignments of savings holdings (db/holding_store.py) against the throwaway test database."""
import pytest

import goal_store
import holding_store

HAREL_PENSION = "harel:70"       # Harel's funds carry no liquidity date, so the user places them


def test_assign_sets_horizon_then_goal_and_keeps_the_other_field(conn):
    assert holding_store.assign(conn, HAREL_PENSION, horizon="future") == {"horizon": "future", "goal_id": None}
    goal = goal_store.create_goal(conn, "חופשות", 30000)
    assert holding_store.assign(conn, HAREL_PENSION, goal_id=goal["id"]) == {"horizon": "future", "goal_id": goal["id"]}
    assert holding_store.all_assignments(conn) == {HAREL_PENSION: {"horizon": "future", "goal_id": goal["id"]}}


def test_clearing_both_fields_deletes_the_row(conn):
    holding_store.assign(conn, HAREL_PENSION, horizon="near")
    assert holding_store.assign(conn, HAREL_PENSION, horizon=None) is None
    assert holding_store.all_assignments(conn) == {}


def test_unknown_horizon_or_goal_is_rejected_before_anything_is_written(conn):
    with pytest.raises(ValueError):
        holding_store.assign(conn, HAREL_PENSION, horizon="someday")
    with pytest.raises(ValueError):
        holding_store.assign(conn, HAREL_PENSION, goal_id=999999)
    assert holding_store.all_assignments(conn) == {}


def test_deleting_a_goal_unassigns_its_holdings_but_keeps_the_horizon(conn):
    goal = goal_store.create_goal(conn, "חופשות", 30000)
    holding_store.assign(conn, "harel:62", horizon="near", goal_id=goal["id"])
    goal_store.delete_goal(conn, goal["id"])
    assert holding_store.all_assignments(conn) == {"harel:62": {"horizon": "near", "goal_id": None}}
