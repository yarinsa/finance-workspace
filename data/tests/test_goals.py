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
            monthly_surplus=2000,
        )
        # progress = min(buffer, amount) / amount; the remaining ₪1,380.85 over
        # ~4.9 months (~₪282/mo) fits a ₪2,000/mo surplus → on track. Runway
        # alone is not enough (see TestOverdrawnGoals).
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


# --- Regression: overdrawn checking (bank_balances_sum = -2,979.12, Oct 2026) ---
#
# As the household, with checking at -₪2,979.12 and a forecast month net of
# -₪1,025.76 (cashflow.json pace.expected.net), my goals "החלפת טלפון" (₪3,000 by
# 2026-11-23) and "טיול שנתי" (₪25,000 by 2027-08-01) showed -99.3% / -11.9%
# progress yet "on track", goal compliance read 100%, the emergency fund read
# -5% with status "ok", and retirement coverage read 100% against a target that
# was just the projection itself.

OVERDRAWN = -2979.12
NEG_SURPLUS = -1025.76


def _store():
    return {
        "emergency_fund_target": 60000,
        "inheritance_target": 1000000,
        "goals": [
            {"id": "phone-2026", "description": "החלפת טלפון", "amount": 3000,
             "end_date": (date.today() + timedelta(days=39)).isoformat()},
            {"id": "trip-2027", "description": "טיול שנתי", "amount": 25000,
             "end_date": (date.today() + timedelta(days=290)).isoformat()},
        ],
    }


def _snapshot(buffer=OVERDRAWN):
    return {"totals": {"bank_balances_sum": buffer}}


def _cashflow(net=NEG_SURPLUS):
    return {
        "today": {"net": -503.89},
        "pace": {"expected": {"net": net}},
        "projection": {
            "net_worth_at_retirement": 12000000,
            "focal_points": [{"net_val": 21903065}],
        },
    }


def _card(out, key):
    return next(c for c in out["general"] if c["key"] == key)


class TestOverdrawnGoals:
    def test_progress_floors_at_zero_when_overdrawn(self):
        g = goals.per_goal(_store()["goals"][0], buffer=OVERDRAWN)
        assert g["progress_pct"] == 0.0

    def test_overdrawn_with_negative_surplus_is_not_on_track(self):
        for raw in _store()["goals"]:
            g = goals.per_goal(raw, buffer=OVERDRAWN, monthly_surplus=NEG_SURPLUS)
            assert g["progress_pct"] == 0.0
            assert g["on_track"] is False, raw["description"]

    def test_unknown_surplus_is_never_reported_on_track(self):
        # Runway alone does not make a goal fundable.
        g = goals.per_goal(_store()["goals"][0], buffer=OVERDRAWN)
        assert g["on_track"] is not True

    def test_required_monthly_fits_positive_surplus(self):
        # ₪3,000 in 39 days needs ≈ ₪2,341/mo; a ₪5,000/mo surplus covers it.
        g = goals.per_goal(_store()["goals"][0], buffer=0, monthly_surplus=5000)
        assert g["required_monthly"] == round(3000 / (39 / goals.DAYS_PER_MONTH), 2)
        assert g["on_track"] is True

    def test_required_monthly_exceeds_small_surplus(self):
        g = goals.per_goal(_store()["goals"][0], buffer=0, monthly_surplus=1000)
        assert g["on_track"] is False


class TestBuildDigest:
    def test_goal_compliance_counts_only_fundable_goals(self):
        out = goals.build(_store(), _snapshot(), _cashflow())
        assert _card(out, "goal_compliance")["value"] == 0.0
        assert all(g["on_track"] is False for g in out["personal_goals"])

    def test_missing_piece_uses_floored_accrual(self):
        # Nothing accrued → the full 3,000 + 25,000, not inflated by the overdraft.
        out = goals.build(_store(), _snapshot(), _cashflow())
        assert out["missing_piece"] == 28000

    def test_shared_surplus_funds_earliest_goal_first(self):
        # ₪4,000/mo covers the phone (~₪2,341/mo) but not phone + trip together
        # (trip needs ~₪2,624/mo on top) — one surplus can't be spent twice.
        out = goals.build(_store(), _snapshot(0), _cashflow(net=4000))
        by_id = {g["id"]: g for g in out["personal_goals"]}
        assert by_id["phone-2026"]["on_track"] is True
        assert by_id["trip-2027"]["on_track"] is False
        assert _card(out, "goal_compliance")["value"] == 50.0

    def test_emergency_fund_floors_and_flags_unmet(self):
        card = _card(goals.build(_store(), _snapshot(), _cashflow()), "emergency_fund_coverage")
        assert card["value"] == 0.0
        assert card["shortfall"] == 60000
        assert card["meets_target"] is False

    def test_retirement_without_target_needs_input(self):
        card = _card(goals.build(_store(), _snapshot(), _cashflow()), "retirement_coverage")
        assert card["value"] is None
        assert card["status"] == "needs_input"
        assert card["target_derived"] is True

    def test_retirement_with_target_reports_coverage(self):
        store = {**_store(), "retirement_target": 24000000}
        card = _card(goals.build(store, _snapshot(), _cashflow()), "retirement_coverage")
        assert card["value"] == 50.0
        assert card["status"] == "ok"
        assert card["meets_target"] is False


class TestEmergencyFundOverdrawn:
    def test_negative_buffer_coverage_is_zero_not_negative(self):
        card = goals.emergency_fund_card(OVERDRAWN, 60000)
        assert card["value"] == 0.0
        assert card["shortfall"] == 60000
        assert card["meets_target"] is False

    def test_funded_meets_target(self):
        card = goals.emergency_fund_card(70000, 60000)
        assert card["value"] == 100.0
        assert card["shortfall"] == 0
        assert card["meets_target"] is True
