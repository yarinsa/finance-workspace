#!/usr/bin/env python3
"""Per-source freshness targets: how old each source's data may get.

One source of truth for "is this data current enough?", used by

  * `digest.py`  -> writes `freshness` into snapshot.json for the app,
  * `actions.py` -> raises the "נתונים לא עדכניים" action for overdue sources,
  * the scheduled sync -> `due_sources(now)` says which sources to scrape today.

A source's age is `now - last_synced`, where `last_synced` is the newest raw-dump
mtime under data/<source>/raw (the moment the scraper last wrote, not when
normalize/digest re-ran). Each target is a max age plus a grace period:

    age <= max_age                  fresh
    max_age < age <= max_age+grace  due      (should be scraped; not yet alarming)
    age > max_age+grace             overdue  (raises the action)
    no raw dump at all              never

RiseUp is deliberately absent: it has no target and never appears in the output.
Pure file reads only; never touches a session, Chrome or a scraper.

    python3 data/freshness.py            # table
    python3 data/freshness.py --json     # status list
    python3 data/freshness.py --root DIR # read dumps from another checkout (read-only)
"""
import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(os.environ.get("FINANCE_DATA_DIR") or Path(__file__).resolve().parent)

HOUR, DAY = timedelta(hours=1), timedelta(days=1)

# source: (max_age, grace). Ordered so that `due_sources` respects the Discount
# rule: account -> mortgage -> business (the business app rebinds the shared
# login; see refresh-all). Leumi's loan total is scraped with its account, so it
# shares the daily leumi target.
TARGETS = {
    "discount":          (1 * DAY, 12 * HOUR),   # bank: daily
    "discount-mortgage": (7 * DAY, 2 * DAY),     # loans: weekly
    "discount-business": (1 * DAY, 12 * HOUR),   # bank: daily
    "leumi":             (1 * DAY, 12 * HOUR),   # bank: daily
    "cal":               (1 * DAY, 12 * HOUR),   # card: daily
    "amex":              (1 * DAY, 12 * HOUR),   # card: daily
    "max":               (1 * DAY, 12 * HOUR),   # card: daily
    "harel":             (30 * DAY, 7 * DAY),    # savings: monthly
    "more":              (30 * DAY, 7 * DAY),    # savings: monthly
    "analyst":           (30 * DAY, 7 * DAY),    # savings: monthly
}

# Sources that deliberately have no target (excluded from status and due lists).
NO_TARGET = {"riseup"}

# `due_sources` treats a source as due this long BEFORE its max age elapses, so a
# daily 07:30 run that scraped at 07:35 yesterday still picks it up today.
DUE_LEAD = 4 * HOUR


def _aware(dt):
    """Naive datetimes are local time; return an aware one."""
    return dt if dt.tzinfo else dt.astimezone()


def _hours(td):
    """timedelta -> hours (float), the JSON-friendly unit for target/grace/age."""
    return round(td.total_seconds() / 3600, 1)


def raw_mtime(raw_dir):
    """Newest mtime (epoch seconds) of any dump file under `raw_dir`, or None."""
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        return None
    mtimes = [f.stat().st_mtime for f in raw_dir.rglob("*")
              if f.is_file() and not f.name.startswith(".")]
    return max(mtimes) if mtimes else None


def last_synced(source, root=None):
    """When `source` was last scraped (aware datetime), or None if never."""
    newest = raw_mtime(Path(root or ROOT) / source / "raw")
    return datetime.fromtimestamp(newest).astimezone() if newest is not None else None


def classify(source, last, now):
    """Status row for `source` given its last sync (datetime, ISO string or None)."""
    max_age, grace = TARGETS[source]
    if isinstance(last, str):
        last = datetime.fromisoformat(last)
    row = {"source": source, "last_synced": None, "target": _hours(max_age),
           "grace": _hours(grace), "age": None, "state": "never"}
    if last is None:
        return row
    last, now = _aware(last), _aware(now)
    age = max(now - last, timedelta(0))
    state = "fresh" if age <= max_age else "due" if age <= max_age + grace else "overdue"
    row.update(last_synced=last.isoformat(timespec="seconds"), age=_hours(age), state=state)
    return row


def status(now=None, root=None):
    """One row per targeted source: {source, last_synced, target, grace, age, state}.

    `target`, `grace` and `age` are in hours. State is fresh|due|overdue|never.
    """
    now = now or datetime.now().astimezone()
    return [classify(s, last_synced(s, root), now) for s in TARGETS]


def due_sources(now=None, root=None):
    """Sources the scheduled sync should scrape now, in safe scrape order.

    Everything `never` scraped, `due` or `overdue`, plus fresh sources that will
    cross their max age within DUE_LEAD (so a daily run is not skipped because
    yesterday's scrape finished a few minutes later than today's start). Cheap:
    stat calls only.
    """
    out = []
    for row in status(now, root):
        if row["state"] != "fresh" or row["age"] + _hours(DUE_LEAD) >= row["target"]:
            out.append(row["source"])
    return out


def lateness(row):
    """Hours past the target (0 within target), for a status row."""
    return max((row["age"] or 0) - row["target"], 0)


def fmt_span(hours):
    """Hebrew span: hours under two days, else whole days."""
    return f"{round(hours)} שעות" if hours < 48 else f"{round(hours / 24)} ימים"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="emit the status list as JSON")
    ap.add_argument("--root", help="data directory to read dumps from (read-only)")
    args = ap.parse_args()
    rows = status(root=args.root)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return
    print(f"{'source':<18}{'state':<9}{'age':>7}{'target':>8}{'grace':>7}  last_synced")
    for r in rows:
        age = "-" if r["age"] is None else f"{r['age']:.0f}h"
        print(f"{r['source']:<18}{r['state']:<9}{age:>7}{r['target']:>7.0f}h{r['grace']:>6.0f}h  "
              f"{r['last_synced'] or 'never'}")
    print("due now:", ", ".join(due_sources(root=args.root)) or "-")


if __name__ == "__main__":
    main()
