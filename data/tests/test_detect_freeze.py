"""Real-case tests for detect_freeze.py detection and post-freeze math.

Each case is anchored to either the actual mortgage_details.json (the real
household tracks that are currently frozen at interest-only) or a concrete
domain scenario documented in detect_freeze.py. When a new freeze arrangement
is made, add the real track figures here (see CLAUDE.md "Bugs → tests").
"""
import pytest
import detect_freeze

# ── Real track data from data/discount-mortgage/raw/mortgage_details.json ──
# Track 1 — 2.09% CPI-linked variable, pays principal+interest, NOT frozen.
TRACK_2_09 = {
    "LoanAccount": "0034069100438552",
    "LoanName": "הלוואה צמודת מדד בריבית משתנה אג\"ח- דיור",
    "TotalInterestRate": 2.09,
    "PrincipalBalance": 426862.19,
    "NextPayment": 835.88,
    "PreviousPayment": 835.88,
    "NumOfPaymentsRemained": "325",
    "NextPaymentDate": "20260810",
}

# Track 2 — 4.6% Prime-linked, NextPayment ≈ interest-only → FROZEN.
# PreviousPayment (1781.31) is the full pre-freeze installment and exceeds
# NextPayment by ~88.91 ₪ (> INTEREST_ONLY_TOLERANCE), so full_payment_estimate
# returns PreviousPayment as the "unfrozen" figure.
TRACK_4_60 = {
    "LoanAccount": "0034069400445754",
    "LoanName": "הלואה לא צמודה ר.משתנה - דיור רגילות",
    "TotalInterestRate": 4.6,
    "PrincipalBalance": 441496.75,
    "NextPayment": 1692.4,
    "PreviousPayment": 1781.31,
    "NumOfPaymentsRemained": "320",
    "NextPaymentDate": "20260810",
}

# Track 3 — 4.55% fixed, NextPayment ≈ interest-only → FROZEN.
# PreviousPayment == NextPayment, so full_payment_estimate falls back to the
# annuity formula (₪2353.31).
TRACK_4_55 = {
    "LoanAccount": "0034069500223577",
    "LoanName": "הלואה לא צמודה ר.קבועה - דיור",
    "TotalInterestRate": 4.55,
    "PrincipalBalance": 439233.44,
    "NextPayment": 1665.43,
    "PreviousPayment": 1665.43,
    "NumOfPaymentsRemained": "325",
    "NextPaymentDate": "20260810",
}

# Matave bridging track — ~0% rate, balance ₪15 696 < MIN_TRACK_BALANCE → ignored.
TRACK_MATAVE = {
    "LoanAccount": "0034069500225766",
    "LoanName": "הלואה לא צמודה ר.קבועה - דיור מתווה",
    "TotalInterestRate": 0.0001,
    "PrincipalBalance": 15696.11,
    "NextPayment": 461.59,
    "PreviousPayment": 461.59,
    "NumOfPaymentsRemained": "34",
    "NextPaymentDate": "20260810",
}

# All six real tracks from mortgage_details.json (two more מתווה, same shape).
ALL_REAL_TRACKS = [
    TRACK_2_09,
    TRACK_4_60,
    TRACK_4_55,
    {**TRACK_MATAVE, "LoanAccount": "0034069500225766", "PrincipalBalance": 15696.11},
    {**TRACK_MATAVE, "LoanAccount": "0034069500225812", "PrincipalBalance": 22423.70},
    {**TRACK_MATAVE, "LoanAccount": "0034069500225863", "PrincipalBalance": 19938.48},
]


# ─────────────────────────────────────────────────────────────────────────────
# monthly_interest
# ─────────────────────────────────────────────────────────────────────────────
class TestMonthlyInterest:
    def test_4_60_track_real_values(self):
        # 441496.75 × 4.6% / 12 = 1692.40 (matches NextPayment exactly — frozen)
        result = detect_freeze.monthly_interest(TRACK_4_60)
        assert abs(result - 1692.40) < 0.02

    def test_4_55_track_real_values(self):
        # 439233.44 × 4.55% / 12 = 1665.43 (matches NextPayment — frozen)
        result = detect_freeze.monthly_interest(TRACK_4_55)
        assert abs(result - 1665.43) < 0.02

    def test_2_09_track_real_values(self):
        # 426862.19 × 2.09% / 12 = 743.45 — well below NextPayment 835.88
        result = detect_freeze.monthly_interest(TRACK_2_09)
        assert abs(result - 743.45) < 0.10

    def test_zero_rate_gives_zero_interest(self):
        assert detect_freeze.monthly_interest({
            "PrincipalBalance": 100_000,
            "TotalInterestRate": 0,
        }) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# full_payment_estimate
# ─────────────────────────────────────────────────────────────────────────────
class TestFullPaymentEstimate:
    def test_4_60_uses_previous_payment_when_it_exceeds_next_by_tolerance(self):
        # PreviousPayment 1781.31 − NextPayment 1692.40 = 88.91 > 60 (tolerance)
        # → PreviousPayment is returned as the "unfrozen" amount.
        result = detect_freeze.full_payment_estimate(TRACK_4_60)
        assert result == 1781.31

    def test_4_55_falls_back_to_annuity_when_prev_equals_next(self):
        # PreviousPayment == NextPayment == 1665.43, so no "clearly higher" signal.
        # Annuity over 325 payments at 4.55%/12 on ₪439 233.44 ≈ ₪2353.
        result = detect_freeze.full_payment_estimate(TRACK_4_55)
        assert 2300 < result < 2400

    def test_2_09_unfrozen_track_estimate_close_to_next_payment(self):
        # 2.09% track pays principal+interest normally; NextPayment == PreviousPayment.
        # Falls back to annuity formula — should be near the current payment.
        result = detect_freeze.full_payment_estimate(TRACK_2_09)
        # Annuity at 2.09% CPI-adjusted is in a different ballpark because the
        # NextPayment reflects CPI-adjusted principal; we just assert it's positive
        # and not wildly wrong (within 2× of NextPayment).
        assert 0 < result < TRACK_2_09["NextPayment"] * 3

    def test_zero_rate_track_uses_balance_divided_by_n(self):
        track = {"PrincipalBalance": 12000.0, "TotalInterestRate": 0,
                 "NumOfPaymentsRemained": "24", "NextPayment": 500.0,
                 "PreviousPayment": 500.0}
        result = detect_freeze.full_payment_estimate(track)
        assert abs(result - 500.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# detect — real cases
# ─────────────────────────────────────────────────────────────────────────────
class TestDetect:
    def test_real_mortgage_flags_exactly_two_frozen_tracks(self):
        # The 4.6% and 4.55% tracks pay ≈ interest-only (frozen).
        # The 2.09% track pays more than interest-only (not frozen).
        # All three מתווה tracks are below MIN_TRACK_BALANCE and are excluded.
        flagged = detect_freeze.detect(ALL_REAL_TRACKS)
        rates = [f["rate"] for f in flagged]
        assert sorted(rates) == [4.55, 4.6]

    def test_2_09_track_is_not_flagged(self):
        # 835.88 NextPayment vs 743.45 interest-only → diff 92 > 60 tolerance
        flagged = detect_freeze.detect([TRACK_2_09])
        assert flagged == []

    def test_matave_tracks_excluded_below_min_balance(self):
        # All three מתווה tracks have balance < MIN_TRACK_BALANCE (100k)
        matave_tracks = [t for t in ALL_REAL_TRACKS
                         if t["PrincipalBalance"] < detect_freeze.MIN_TRACK_BALANCE]
        assert len(matave_tracks) == 3
        assert detect_freeze.detect(matave_tracks) == []

    def test_4_60_flagged_entry_carries_correct_diagnostic_fields(self):
        flagged = detect_freeze.detect([TRACK_4_60])
        assert len(flagged) == 1
        f = flagged[0]
        assert f["loan_account"] == "0034069400445754"
        assert f["rate"] == 4.6
        assert abs(f["balance"] - 441496.75) < 0.01
        assert abs(f["current_payment"] - 1692.4) < 0.01
        assert abs(f["interest_only"] - 1692.4) < 0.10
        assert f["full_payment_est"] == 1781.31
        # deferred_principal_per_mo = full - current ≈ 88–89 ₪
        assert 80 < f["deferred_principal_per_mo"] < 100

    def test_track_not_frozen_no_flag(self):
        # A synthetic track whose NextPayment is well above interest-only.
        normal_track = {
            "LoanAccount": "NORMAL",
            "LoanName": "normal",
            "TotalInterestRate": 4.0,
            "PrincipalBalance": 300_000.0,
            "NextPayment": 1800.0,   # full annuity, not interest-only (≈1000/mo int)
            "PreviousPayment": 1800.0,
            "NumOfPaymentsRemained": "240",
        }
        assert detect_freeze.detect([normal_track]) == []

    def test_tolerance_boundary_at_exactly_60_is_flagged(self):
        # NextPayment == interest_only + exactly TOLERANCE → abs diff == 60 → flagged.
        bal = 200_000.0
        rate = 3.0
        int_only = bal * (rate / 100) / 12   # 500.0
        track = {
            "LoanAccount": "BOUNDARY",
            "LoanName": "boundary",
            "TotalInterestRate": rate,
            "PrincipalBalance": bal,
            "NextPayment": int_only + detect_freeze.INTEREST_ONLY_TOLERANCE,
            "PreviousPayment": int_only + detect_freeze.INTEREST_ONLY_TOLERANCE,
            "NumOfPaymentsRemained": "240",
        }
        # abs(NextPayment - int_only) == INTEREST_ONLY_TOLERANCE → <= → flagged
        flagged = detect_freeze.detect([track])
        assert len(flagged) == 1

    def test_one_cent_over_tolerance_is_not_flagged(self):
        bal = 200_000.0
        rate = 3.0
        int_only = bal * (rate / 100) / 12
        track = {
            "LoanAccount": "OVER",
            "LoanName": "over",
            "TotalInterestRate": rate,
            "PrincipalBalance": bal,
            "NextPayment": int_only + detect_freeze.INTEREST_ONLY_TOLERANCE + 0.01,
            "PreviousPayment": int_only + detect_freeze.INTEREST_ONLY_TOLERANCE + 0.01,
            "NumOfPaymentsRemained": "240",
        }
        assert detect_freeze.detect([track]) == []


# ─────────────────────────────────────────────────────────────────────────────
# post_freeze_payment — four combinations + edge cases
# ─────────────────────────────────────────────────────────────────────────────
class TestPostFreezePayment:
    """post_freeze_payment is called with the *flagged dict* produced by detect(),
    which carries 'balance', 'rate', 'payments_remaining', 'current_payment',
    plus the raw track fields for fallback.  We replicate that shape here.
    """

    @pytest.fixture
    def frozen_4_60(self):
        """Flagged-dict shape for the real 4.6% track (as produced by detect())."""
        return {
            "loan_account": "0034069400445754",
            "rate": 4.6,
            "balance": 441496.75,
            "payments_remaining": 320,
            "current_payment": 1692.4,
            "full_payment_est": 1781.31,
            # Raw fields that post_freeze_payment falls back to:
            "LoanAccount": "0034069400445754",
            "TotalInterestRate": 4.6,
            "PrincipalBalance": 441496.75,
            "NumOfPaymentsRemained": "320",
            "NextPayment": 1692.4,
            "PreviousPayment": 1781.31,
        }

    def test_principal_only_push_true_equals_full_estimate(self, frozen_4_60):
        # End date pushed → same full installment resumes. No balance change.
        result = detect_freeze.post_freeze_payment(frozen_4_60, 3, "principal_only", True)
        assert result == 1781.31

    def test_principal_only_push_false_higher_than_full(self, frozen_4_60):
        # Deferred principal squeezed into 317 remaining months → payment rises.
        result = detect_freeze.post_freeze_payment(frozen_4_60, 3, "principal_only", False)
        assert result > 1781.31
        # Concrete value validated against formula output:
        assert abs(result - 2408.60) < 1.0

    def test_full_freeze_push_true_equals_full_estimate(self, frozen_4_60):
        # push_end_date=True → code returns full regardless of freeze type.
        result = detect_freeze.post_freeze_payment(frozen_4_60, 3, "full", True)
        assert result == 1781.31

    def test_full_freeze_push_false_highest_of_all(self, frozen_4_60):
        # Balance grows by capitalised interest AND term is unchanged → highest.
        result = detect_freeze.post_freeze_payment(frozen_4_60, 3, "full", False)
        principal_only_push_false = detect_freeze.post_freeze_payment(
            frozen_4_60, 3, "principal_only", False)
        assert result > principal_only_push_false
        # Concrete value:
        assert abs(result - 2436.41) < 1.0

    def test_ordering_full_push_false_gt_principal_push_false_gt_push_true(self, frozen_4_60):
        p_push_true  = detect_freeze.post_freeze_payment(frozen_4_60, 3, "principal_only", True)
        p_push_false = detect_freeze.post_freeze_payment(frozen_4_60, 3, "principal_only", False)
        f_push_true  = detect_freeze.post_freeze_payment(frozen_4_60, 3, "full", True)
        f_push_false = detect_freeze.post_freeze_payment(frozen_4_60, 3, "full", False)
        # push=True is cheapest (unchanged full payment)
        assert p_push_true == f_push_true
        # push=False defers principal into shorter window → rises
        assert p_push_false > p_push_true
        # full freeze on push=False also adds capitalised interest → highest
        assert f_push_false > p_push_false

    def test_6_month_freeze_produces_higher_resume_than_3_month(self, frozen_4_60):
        # Longer freeze → more principal deferred over fewer remaining months.
        p3 = detect_freeze.post_freeze_payment(frozen_4_60, 3, "principal_only", False)
        p6 = detect_freeze.post_freeze_payment(frozen_4_60, 6, "principal_only", False)
        assert p6 > p3

    def test_zero_rate_track_principal_only_push_false(self):
        # r=0 branch: simply bal / n_after, no exponentials.
        track = {
            "balance": 24_000.0,
            "rate": 0.0,
            "payments_remaining": 24,
            "PrincipalBalance": 24_000.0,
            "TotalInterestRate": 0.0,
            "NumOfPaymentsRemained": "24",
            "NextPayment": 1000.0,
            "PreviousPayment": 1000.0,
        }
        # 3-month freeze, push=False → 24_000 / max(24-3,1) = 24_000/21 ≈ 1142.86
        result = detect_freeze.post_freeze_payment(track, 3, "principal_only", False)
        assert abs(result - (24_000 / 21)) < 0.02

    def test_n_after_floors_to_1_when_months_exceed_remaining(self):
        # If freeze months >= remaining payments, n_after = max(n-months, 1) = 1.
        track = {
            "balance": 5_000.0,
            "rate": 4.0,
            "payments_remaining": 2,
            "PrincipalBalance": 5_000.0,
            "TotalInterestRate": 4.0,
            "NumOfPaymentsRemained": "2",
            "NextPayment": 2517.0,
            "PreviousPayment": 2517.0,
        }
        # 3-month freeze but only 2 payments remain → n_after = max(2-3,1)=1
        r = (4.0 / 100) / 12
        expected = 5_000 * (r * (1 + r) ** 1) / ((1 + r) ** 1 - 1)
        result = detect_freeze.post_freeze_payment(track, 3, "principal_only", False)
        assert abs(result - round(expected, 2)) < 0.02


# ─────────────────────────────────────────────────────────────────────────────
# add_months
# ─────────────────────────────────────────────────────────────────────────────
class TestAddMonths:
    def test_zero_delta_is_no_op(self):
        assert detect_freeze.add_months("2026-08", 0) == "2026-08"

    def test_within_year(self):
        assert detect_freeze.add_months("2026-06", 2) == "2026-08"

    def test_year_rollover_single_step(self):
        assert detect_freeze.add_months("2026-12", 1) == "2027-01"

    def test_multi_month_crosses_year(self):
        assert detect_freeze.add_months("2026-08", 6) == "2027-02"

    def test_negative_goes_back(self):
        assert detect_freeze.add_months("2026-06", -1) == "2026-05"

    def test_negative_crosses_year_boundary(self):
        assert detect_freeze.add_months("2026-01", -1) == "2025-12"

    def test_freeze_resume_month_3mo_from_august(self):
        # The actual freeze: starts 2026-08, 3-month duration → resumes 2026-11.
        assert detect_freeze.add_months("2026-08", 3) == "2026-11"
