"""Real-case tests for goals.py — the יעדים digest (docs/plangram-prd/04-goals.md).

Cases mirror real plan decisions: an unset target must degrade to "needs input"
(never a fake 100%), emergency-fund coverage caps at 100%, and a personal goal's
on-track verdict turns on its end-date runway.
"""
from datetime import date, timedelta

import goals


class TestPct:
    def test_unset_denominator_is_none_not_zero(self):
        # An unset target (0) must NOT read as 0% — it is "needs input".
        assert goals.pct(1619.15, 0) is None

    def test_coverage_caps_at_100(self):
        # Liquid buffer far above target still reads 100%, not 300%.
        assert goals.pct(180000, 60000) == 100.0

    def test_partial_coverage_rounds_to_one_dp(self):
        # ₪1,619.15 liquid vs a ₪60,000 emergency-fund target → 2.7%.
        assert goals.pct(1619.15, 60000) == 2.7


class TestEmergencyFundCard:
    def test_unset_target_needs_input(self):
        card = goals.emergency_fund_card(1619.15, 0)
        assert card["status"] == "needs_input"
        assert card["value"] is None
        assert card["shortfall"] is None

    def test_shortfall_is_target_minus_buffer(self):
        card = goals.emergency_fund_card(1619.15, 60000)
        assert card["value"] == 2.7
        assert card["shortfall"] == round(60000 - 1619.15, 2)


class TestInheritanceCard:
    def test_modelled_estate_vs_target_verdict(self):
        # The card shows the modelled estate (₪) and flags whether it meets target.
        card = goals.inheritance_card(6816471, 1000000)
        assert card["value"] == 6816471
        assert card["meets_target"] is True

    def test_no_estate_needs_input(self):
        card = goals.inheritance_card(None, 1000000)
        assert card["status"] == "needs_input"
        assert card["meets_target"] is None


class TestStoreMutations:
    """CLI-backed store edits (PRD 11) — real cases: add a goal, edit its amount,
    reject bad input. These operate on an in-memory store, no disk."""

    def _store(self):
        return {"emergency_fund_target": 0, "inheritance_target": 0, "goals": []}

    def test_add_goal_assigns_unique_id_and_fields(self):
        s = self._store()
        g = goals.add_goal(s, "רכב חדש", 80000, "2027-12-31")
        assert g["id"] and g["id"] in {x["id"] for x in s["goals"]}
        assert g["amount"] == 80000 and g["end_date"] == "2027-12-31"
        assert len(s["goals"]) == 1

    def test_add_rejects_nonpositive_amount(self):
        import pytest
        with pytest.raises(ValueError):
            goals.add_goal(self._store(), "x", -5, "2027-01-01")

    def test_add_rejects_bad_date(self):
        import pytest
        with pytest.raises(ValueError):
            goals.add_goal(self._store(), "x", 100, "nope")

    def test_add_rejects_duplicate_id(self):
        import pytest
        s = self._store()
        goals.add_goal(s, "a", 100, "2027-01-01", goal_id="dup")
        with pytest.raises(ValueError):
            goals.add_goal(s, "b", 100, "2027-01-01", goal_id="dup")

    def test_edit_updates_amount(self):
        s = self._store()
        goals.add_goal(s, "רכב", 80000, "2027-12-31", goal_id="car")
        goals.edit_goal(s, "car", amount=90000)
        assert s["goals"][0]["amount"] == 90000

    def test_edit_unknown_id_raises(self):
        import pytest
        with pytest.raises(ValueError):
            goals.edit_goal(self._store(), "missing", amount=1)

    def test_remove_goal(self):
        s = self._store()
        goals.add_goal(s, "a", 100, "2027-01-01", goal_id="gone")
        goals.remove_goal(s, "gone")
        assert s["goals"] == []

    def test_remove_unknown_id_raises(self):
        import pytest
        with pytest.raises(ValueError):
            goals.remove_goal(self._store(), "missing")


class TestPerGoal:
    def test_future_end_date_is_on_track(self):
        end = (date.today() + timedelta(days=149)).isoformat()
        g = goals.per_goal(
            {"id": "phone", "description": "החלפת טלפון", "amount": 3000, "end_date": end},
            buffer=1619.15,
        )
        # progress = min(buffer, amount) / amount; runway still open → on track.
        assert g["progress_pct"] == 54.0
        assert g["on_track"] is True
        assert g["days_left"] == 149

    def test_past_end_date_underfunded_is_off_track(self):
        end = (date.today() - timedelta(days=10)).isoformat()
        g = goals.per_goal(
            {"id": "late", "description": "יעד שעבר", "amount": 50000, "end_date": end},
            buffer=1000,
        )
        assert g["on_track"] is False

    def test_fully_funded_is_on_track_regardless_of_date(self):
        end = (date.today() - timedelta(days=10)).isoformat()
        g = goals.per_goal(
            {"id": "done", "description": "ממומן", "amount": 500, "end_date": end},
            buffer=10000,
        )
        assert g["progress_pct"] == 100.0
        assert g["on_track"] is True
