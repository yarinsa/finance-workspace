"""Default goals (the general targets) in db/goal_store.py against the throwaway test database."""
import pytest

import goal_store


def test_a_default_goal_holds_a_target_stays_out_of_the_goal_list_and_cannot_be_deleted(conn):
    goal_store.set_targets(conn, emergency_fund_target=60000)
    assert goal_store.get_targets(conn)["emergency_fund_target"] == 60000
    assert goal_store.all_goals(conn) == []
    default_id = conn.execute("SELECT id FROM goals WHERE key = 'emergency_fund'").fetchone()[0]
    with pytest.raises(ValueError):
        goal_store.delete_goal(conn, default_id)
    goal_store.set_targets(conn, emergency_fund_target=None)
    assert goal_store.get_targets(conn)["emergency_fund_target"] is None
