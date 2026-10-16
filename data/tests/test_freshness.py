"""Real-case tests for freshness.py — per-source targets behind the stale-data action
and the scheduled sync's due list."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import freshness

IL = timezone(timedelta(hours=3))
NOW = datetime(2026, 10, 16, 7, 30, tzinfo=IL)


def ago(**kw):
    return NOW - timedelta(**kw)


def state(source, last):
    return freshness.classify(source, last, NOW)["state"]


def test_harel_synced_20_days_ago_is_fresh():
    # Savings are monthly; a pension balance 20 days old is within target.
    assert state("harel", ago(days=20)) == "fresh"


def test_amex_synced_2_days_ago_is_overdue():
    # Cards are daily (24h + 12h grace); a 14/10 dump is well past that.
    row = freshness.classify("amex", ago(days=2), NOW)
    assert row["state"] == "overdue"
    assert row["age"] == 48.0 and row["target"] == 24.0
    assert freshness.lateness(row) == 24.0


def test_amex_synced_30_hours_ago_is_due_not_overdue():
    # Past the daily target but inside the grace -> scrape it, don't alarm.
    assert state("amex", ago(hours=30)) == "due"


def test_discount_business_synced_9_days_ago_is_overdue():
    # The real 2026-10-09 dump while everything else was refreshed on 10-15/16.
    last = datetime(2026, 10, 9, 23, 59, tzinfo=IL)
    assert state("discount-business", last) == "overdue"


def test_mortgage_weekly_target():
    assert state("discount-mortgage", ago(days=6)) == "fresh"
    assert state("discount-mortgage", ago(days=8)) == "due"
    assert state("discount-mortgage", ago(days=10)) == "overdue"


def test_never_scraped_and_future_mtime():
    assert state("cal", None) == "never"
    assert state("cal", NOW + timedelta(hours=2)) == "fresh"   # clock skew clamps to age 0


def test_accepts_iso_strings_from_the_syncs_list():
    assert state("leumi", "2026-10-16T08:38:10+03:00") == "fresh"


def test_riseup_has_no_target():
    assert "riseup" not in freshness.TARGETS
    assert "riseup" not in [r["source"] for r in freshness.status(NOW)]


def test_every_normalized_source_has_a_target_or_is_exempt():
    # A newly scaffolded source must pick a freshness target (or opt out).
    data = Path(freshness.__file__).parent
    sources = {p.parent.name for p in data.glob("*/normalize.py")}
    # (A target may land before its normalize.py, e.g. the max scaffold.)
    assert sources <= set(freshness.TARGETS) | freshness.NO_TARGET


def _dump(root, source, when):
    raw = root / source / "raw"
    raw.mkdir(parents=True)
    f = raw / "dump.json"
    f.write_text("{}")
    os.utime(f, (when.timestamp(), when.timestamp()))


def test_last_synced_is_newest_raw_mtime_and_empty_raw_is_never(tmp_path):
    _dump(tmp_path, "amex", ago(days=2))
    (tmp_path / "cal" / "raw").mkdir(parents=True)
    assert freshness.last_synced("amex", tmp_path) == ago(days=2)
    assert freshness.last_synced("cal", tmp_path) is None
    assert freshness.last_synced("leumi", tmp_path) is None


def test_due_sources_picks_late_and_never_in_scrape_order(tmp_path):
    _dump(tmp_path, "discount", ago(hours=2))          # fresh
    _dump(tmp_path, "discount-mortgage", ago(days=3))  # fresh (weekly)
    _dump(tmp_path, "discount-business", ago(days=9))  # overdue
    _dump(tmp_path, "leumi", ago(hours=30))            # due
    _dump(tmp_path, "cal", ago(hours=2))               # fresh
    _dump(tmp_path, "amex", ago(days=2))               # overdue
    _dump(tmp_path, "harel", ago(days=20))             # fresh (monthly)
    _dump(tmp_path, "more", ago(days=20))
    _dump(tmp_path, "riseup", ago(days=60))            # no target: never listed
    # max, analyst never scraped
    assert freshness.due_sources(NOW, tmp_path) == ["discount-business", "leumi", "amex", "max", "analyst"]


def test_daily_source_scraped_just_after_todays_run_time_is_still_due(tmp_path):
    # Yesterday's run finished at 07:35; today's starts at 07:30 -> 23h55 old.
    for s in freshness.TARGETS:
        _dump(tmp_path, s, ago(hours=23, minutes=55) if s == "amex" else ago(hours=1))
    assert freshness.due_sources(NOW, tmp_path) == ["amex"]
