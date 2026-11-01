"""Real-case tests for forecast.py's freeze-aware mortgage payment logic.

These tests cover payment_for_track, load_freeze, and
authoritative_mortgage_payment when a freeze is in effect. The philosophy
matches CLAUDE.md: scenarios are anchored to real household numbers and the
actual freeze parameters that produced them.

freeze.json is never written to disk here — we use monkeypatching to inject
a synthetic freeze dict so we don't clobber any real freeze.json that might
exist, and the tests remain idempotent.
"""
import json
import pytest

import forecast as forecast_loader   # data/forecast.py: the file loaders
from finance.views import forecast
from finance.paths import data_root

# The real Discount mortgage tracks, as the digest stores them (one Loan per track).
MORTGAGE_LOANS = data_root() / "discount-mortgage" / "normalized" / "loans.json"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _freeze_dict(loan_account, resume_month, frozen_payment, resume_payment):
    """Minimal freeze entry keyed by loan_account, matching the freeze.json shape."""
    return {
        loan_account: {
            "resume_month": resume_month,
            "frozen_payment": frozen_payment,
            "resume_payment": resume_payment,
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# payment_for_track — the per-track routing function
# ─────────────────────────────────────────────────────────────────────────────
class TestPaymentForTrack:
    """payment_for_track(track, target_month, freeze) routes to the correct ₪
    figure depending on whether target_month is before or after resume_month."""

    # The real 4.6% frozen track's NextPayment (interest-only, current bank dump).
    FROZEN_NEXT = 1692.4
    # The post-freeze resume payment computed by post_freeze_payment (principal_only,
    # push=False, 3 months): ≈ ₪2408.60 — see test_detect_freeze.py for derivation.
    RESUME_PAY = 2408.60
    LOAN_ACCT = "0034069400445754"

    @pytest.fixture
    def track(self):
        return {
            "loan_id": self.LOAN_ACCT,
            "monthly_payment": self.FROZEN_NEXT,
        }

    @pytest.fixture
    def freeze(self):
        return _freeze_dict(
            self.LOAN_ACCT,
            resume_month="2026-11",
            frozen_payment=self.FROZEN_NEXT,
            resume_payment=self.RESUME_PAY,
        )

    def test_no_target_month_returns_raw_next_payment(self, track, freeze):
        # target_month=None → fall back to raw NextPayment regardless of freeze.
        result = forecast.payment_for_track(track, None, freeze)
        assert result == self.FROZEN_NEXT

    def test_month_before_resume_returns_frozen_payment(self, track, freeze):
        # 2026-08 < 2026-11 → still in freeze window
        assert forecast.payment_for_track(track, "2026-08", freeze) == self.FROZEN_NEXT

    def test_month_exactly_at_resume_returns_resume_payment(self, track, freeze):
        # 2026-11 >= 2026-11 → freeze has lifted
        result = forecast.payment_for_track(track, "2026-11", freeze)
        assert abs(result - self.RESUME_PAY) < 0.01

    def test_month_after_resume_returns_resume_payment(self, track, freeze):
        # 2027-03 >= 2026-11 → well past resume
        result = forecast.payment_for_track(track, "2027-03", freeze)
        assert abs(result - self.RESUME_PAY) < 0.01

    def test_no_freeze_record_returns_next_payment(self, track):
        # Empty freeze dict — track not in it — returns raw NextPayment.
        result = forecast.payment_for_track(track, "2026-11", {})
        assert result == self.FROZEN_NEXT

    def test_none_freeze_falls_back_to_next_payment(self, track):
        # freeze=None (nothing known) behaves like an empty freeze.
        result = forecast.payment_for_track(track, "2026-11", None)
        assert result == self.FROZEN_NEXT


# ─────────────────────────────────────────────────────────────────────────────
# load_freeze
# ─────────────────────────────────────────────────────────────────────────────
class TestLoadFreeze:
    def test_returns_empty_dict_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(forecast_loader, "FREEZE", tmp_path / "no_freeze.json")
        assert forecast_loader.load_freeze() == {}

    def test_returns_tracks_dict_from_valid_file(self, tmp_path, monkeypatch):
        data = {
            "generated_at": "2026-06-14",
            "tracks": {
                "ACC123": {
                    "resume_month": "2026-11",
                    "frozen_payment": 1692.4,
                    "resume_payment": 2408.60,
                }
            },
        }
        f = tmp_path / "freeze.json"
        f.write_text(json.dumps(data))
        monkeypatch.setattr(forecast_loader, "FREEZE", f)
        result = forecast_loader.load_freeze()
        assert "ACC123" in result
        assert result["ACC123"]["resume_month"] == "2026-11"


# ─────────────────────────────────────────────────────────────────────────────
# authoritative_mortgage_payment — integration with freeze applied
# ─────────────────────────────────────────────────────────────────────────────
class TestAuthoritativeMortgagePaymentFreeze:
    """authoritative_mortgage_payment sums per-track payment_for_track calls,
    so the frozen months return less than the resume months when a freeze is
    active.  We monkeypatch load_freeze to inject the household's real freeze
    without touching the real freeze.json file."""

    # The two frozen tracks and their real figures:
    #   4.6% track: NextPayment=1692.4 → frozen, resume≈2408.60
    #   4.55% track: NextPayment=1665.43 → frozen, resume≈2353.31 (annuity)
    # The other 4 tracks are unfrozen and contribute their raw NextPayments.

    FREEZE_TRACKS = {
        "0034069400445754": {
            "resume_month": "2026-11",
            "frozen_payment": 1692.40,
            "resume_payment": 2408.60,
        },
        "0034069500223577": {
            "resume_month": "2026-11",
            "frozen_payment": 1665.43,
            "resume_payment": 2353.31,
        },
    }

    @staticmethod
    def src(freeze):
        """The real mortgage tracks with ``freeze`` injected (nothing written to disk)."""
        loans = json.loads(MORTGAGE_LOANS.read_text())["records"]
        return forecast.Sources(mortgage=[l for l in loans if l["category"] == "mortgage"], freeze=freeze)

    def test_frozen_month_lower_than_resume_month(self):
        src = self.src(self.FREEZE_TRACKS)
        total_frozen, _ = forecast.authoritative_mortgage_payment(src, "2026-09")
        total_resume, _ = forecast.authoritative_mortgage_payment(src, "2026-11")
        assert total_resume > total_frozen

    def test_frozen_month_returns_interest_only_for_frozen_tracks(self):
        total, _ = forecast.authoritative_mortgage_payment(self.src(self.FREEZE_TRACKS), "2026-09")
        # Frozen tracks contribute 1692.40 + 1665.43 = 3357.83.
        # Unfrozen tracks: 2.09% NextPayment=835.88, three מתווה=461.59+659.51+586.44=1707.54
        # Total frozen month ≈ 3357.83 + 835.88 + 1707.54 = 5901.25
        # (allow ±50 for floating-point and CPI drift)
        assert 5800 < total < 6100

    def test_resume_month_includes_higher_annuity_payments(self):
        total, _ = forecast.authoritative_mortgage_payment(self.src(self.FREEZE_TRACKS), "2026-11")
        # Resume: 2408.60 + 2353.31 + 835.88 + 1707.54 = 7305.33 (approx)
        assert total > 7000

    def test_due_date_is_returned_as_date_string(self):
        _, due = forecast.authoritative_mortgage_payment(self.src({}), "2026-09")
        # Due date is the 10th (PrincipalPaymentDayOfMonth) of the target month.
        assert due == "2026-09-10"


# ─────────────────────────────────────────────────────────────────────────────
# forecast.add_months — same helper exists in both modules; test the copy here
# ─────────────────────────────────────────────────────────────────────────────
class TestForecastAddMonths:
    """forecast.add_months is a copy of detect_freeze.add_months — lock it down
    independently in case the two diverge."""

    def test_year_rollover(self):
        assert forecast.add_months("2026-12", 1) == "2027-01"

    def test_multi_month_crosses_year(self):
        assert forecast.add_months("2026-08", 6) == "2027-02"

    def test_zero(self):
        assert forecast.add_months("2026-06", 0) == "2026-06"


# The tables win over the side files once imported (db/input_store.py); empty tables fall back.

def test_freeze_reads_the_table_first(monkeypatch):
    import stores
    rows = {"X": {"frozen_payment": 1.0, "resume_month": "2026-07", "resume_payment": 2.0}}
    monkeypatch.setattr(stores, "from_db", lambda store, read, what=None: rows)
    assert forecast_loader.load_freeze() == rows


def test_schedule_falls_back_to_the_file_while_the_table_is_empty(monkeypatch, tmp_path):
    import stores
    monkeypatch.setattr(stores, "from_db", lambda store, read, what=None: [])
    f = tmp_path / "mortgage_schedule.json"
    f.write_text('{"periods": [{"from": "2026-09", "to": "2026-12", "payment": 5717}]}')
    monkeypatch.setattr(forecast_loader, "SCHEDULE", f)
    assert forecast_loader.load_mortgage_schedule() == [{"from": "2026-09", "to": "2026-12", "payment": 5717}]


# The mortgage tracks come from the stored loans; a table from before migration 0025 (no
# next_payment_date until the next digest) defers to snapshot.json.

TRACK = {"lender": "Bank Discount", "category": "mortgage", "loan_id": "0034069100438552",
         "monthly_payment": 839.87, "final_date": "2053-08-10"}


def test_mortgage_reads_the_stored_loans_first(monkeypatch):
    import stores
    rows = [{**TRACK, "next_payment_date": "2026-11-10"},
            {"lender": "Bank Leumi", "category": "consumer", "loan_id": "25290013", "monthly_payment": 1844.42}]
    monkeypatch.setattr(stores, "from_db", lambda store, read, what=None: rows)
    assert forecast_loader.load_mortgage() == rows[:1]


def test_mortgage_falls_back_to_the_snapshot_until_a_digest_fills_the_date(monkeypatch, tmp_path):
    import stores
    monkeypatch.setattr(stores, "from_db", lambda store, read, what=None: [{**TRACK, "next_payment_date": None}])
    f = tmp_path / "snapshot.json"
    f.write_text(json.dumps({"loans": [{**TRACK, "next_payment_date": "2026-12-10"}]}))
    monkeypatch.setattr(forecast_loader, "SNAPSHOT", f)
    assert forecast_loader.load_mortgage() == [{**TRACK, "next_payment_date": "2026-12-10"}]
    assert forecast.authoritative_mortgage_payment(forecast_loader.load_sources(), None)[1] == "2026-12-10"
