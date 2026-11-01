"""Per-source freshness targets and the status rule (data/freshness.py reads the dump mtimes).

A source's age is `now - last_synced`. Each target is a max age plus a grace period:
fresh within max_age, due within the grace, overdue past it, never without a dump.
RiseUp is deliberately absent: it has no target and never appears in the output.
"""
from datetime import datetime, timedelta

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


def lateness(row):
    """Hours past the target (0 within target), for a status row."""
    return max((row["age"] or 0) - row["target"], 0)


def fmt_span(hours):
    """Hebrew span: hours under two days, else whole days."""
    return f"{round(hours)} שעות" if hours < 48 else f"{round(hours / 24)} ימים"
