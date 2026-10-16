#!/usr/bin/env python3
"""Cashflow dashboard model — Phase 1 (today + breakdowns, no projection).

Reads the two digested outputs and emits ``data/digested/cashflow.json`` (+ a
human ``cashflow.md``), the model behind a Plangram-style "תזרים כספי" screen.
See ``docs/plangram-prd/01-cashflow.md`` for the full spec.

This file is self-contained and idempotent — safe to re-run after every digest.
It reads only ``transactions.json`` and ``snapshot.json``; it never scrapes or
mutates source data. Stdlib only.

Pipeline position::

    data/digested/{transactions,snapshot}.json  --(this)-->  data/digested/cashflow.json
"""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DIGESTED = os.path.join(HERE, "digested")
TRANSACTIONS = os.path.join(DIGESTED, "transactions.json")
SNAPSHOT = os.path.join(DIGESTED, "snapshot.json")
FORECAST = os.path.join(DIGESTED, "forecast.json")
VALIDATION = os.path.join(DIGESTED, "validation.json")
OUT_JSON = os.path.join(DIGESTED, "cashflow.json")
OUT_MD = os.path.join(DIGESTED, "cashflow.md")
OUT_HTML = os.path.join(DIGESTED, "cashflow.html")

CURRENCY = "₪"

# --- Category bucketing -----------------------------------------------------
# Raw Hebrew categories (from RiseUp / banks) folded into the canonical cashflow
# buckets the dashboard charts and KPIs agree on. Anything unmapped falls through
# to "other" (income) or "running" (expense) — the dominant 'uncategorized' bulk
# is everyday spend, so it reads as running expense.

INCOME_BUCKETS = {
    "work": "הכנסות מעבודה",
    "benefits": "הכנסה מקצבאות",
    "other": "הכנסה אחרת",
}
EXPENSE_BUCKETS = {
    "running": "הוצאה שוטפת",
    "goals": "יעדים",
    "loans": "הלוואות",
    "taxes": "מיסים",
    "investments": "השקעות",
    "other": "אחר",
}

# raw category -> expense bucket (only the non-"running" overrides need listing)
EXPENSE_CATEGORY_MAP = {
    "הלוואה": "loans",
    "משכנתא": "loans",
    "תשלומים": "loans",
    "השקעה וחיסכון": "investments",
    "ביטוח ופיננסים": "investments",
    "מוסדות": "taxes",
    "עמלות": "taxes",
    "דמי כרטיס": "taxes",
    "עמלת דמי כרטיס - בנקים": "taxes",
}
# raw category -> income bucket (default income -> "work" unless benefit-like)
INCOME_CATEGORY_MAP = {
    "קצבה": "benefits",
    "קצבאות": "benefits",
    "ביטוח לאומי": "benefits",
    "העברות": "other",
    "P2P BIT": "other",
}


def _expense_bucket(category):
    return EXPENSE_CATEGORY_MAP.get((category or "").strip(), "running")


def _income_bucket(category):
    return INCOME_CATEGORY_MAP.get((category or "").strip(), "work")


# --- Monthly aggregation ----------------------------------------------------

def is_non_cashflow(t):
    """Money moving between our own accounts, and card-bill settlements (the
    underlying purchases are already in the ledger) — not income or spend."""
    return bool(t.get("internal_transfer") or t.get("card_bill_payment"))


def aggregate_by_month(transactions):
    """Group transactions by ``YYYY-MM`` into income/expense/net + bucketed splits.

    Money-out is negative in the ledger; we report expense as a positive figure.
    Returns an ordered dict keyed by month.
    """
    months = defaultdict(lambda: {
        "income": 0.0,
        "expense": 0.0,
        "saved": 0.0,        # routed to own savings/investments — not spend
        "net": 0.0,
        "count": 0,
        "income_by_bucket": defaultdict(float),
        "expense_by_bucket": defaultdict(float),
    })
    for t in transactions:
        # Not cashflow: money moving between our own accounts, and card-bill
        # settlements (the underlying purchases are already in the ledger).
        if is_non_cashflow(t):
            continue
        date = t.get("date")
        if not date or len(date) < 7:
            continue
        ym = date[:7]
        amount = float(t.get("amount") or 0)
        cat = t.get("category")
        m = months[ym]
        m["count"] += 1
        if t.get("savings"):              # outflow, but saved not spent
            m["saved"] += -amount
        elif t.get("is_income") or amount > 0:
            m["income"] += amount
            m["income_by_bucket"][_income_bucket(cat)] += amount
        else:
            m["expense"] += -amount  # store as positive
            m["expense_by_bucket"][_expense_bucket(cat)] += -amount
    for m in months.values():
        # Net keeps savings on the books (it left the checking account), so the
        # cashflow line still reflects liquidity. 'saved' is surfaced separately.
        m["net"] = round(m["income"] - m["expense"] - m["saved"], 2)
        m["income"] = round(m["income"], 2)
        m["expense"] = round(m["expense"], 2)
        m["saved"] = round(m["saved"], 2)
        m["income_by_bucket"] = {k: round(v, 2) for k, v in m["income_by_bucket"].items()}
        m["expense_by_bucket"] = {k: round(v, 2) for k, v in m["expense_by_bucket"].items()}
    return dict(sorted(months.items()))


def pick_current_month(months):
    """The most relevant month to display: the current calendar month if it has
    data, otherwise the most recent month that does have data.

    The old design always excluded the current calendar month as "still accruing,"
    but that caused a systematic one-month lag (e.g. showing June on July 26 when
    July already had 157 transactions). We now show the current calendar month
    whenever the ledger contains any transactions for it, and fall back to the
    latest available month only when the current month is absent entirely (e.g.
    first hour of a new month before any transactions clear).
    """
    if not months:
        return None
    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    if this_month in months:
        return this_month
    # Current month not in ledger yet — return whatever is latest
    return list(months)[-1]


# --- Month-to-date pace -----------------------------------------------------

AVG_MONTHS = 12  # trailing window for the "vs. your average" comparison


def _prev_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def _days_in_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    nxt = datetime(y + (m == 12), m % 12 + 1, 1)
    return (nxt - timedelta(days=1)).day


def top_categories(by_cat, n=5):
    """Largest ``n`` spending categories, the rest folded into "אחר" — sized for a
    donut. Returns ``[{"name", "amount"}]`` largest first, "אחר" always last."""
    ranked = sorted(((k, v) for k, v in by_cat.items() if v > 0), key=lambda kv: -kv[1])
    out = [{"name": k, "amount": round(v, 2)} for k, v in ranked[:n]]
    rest = sum(v for _, v in ranked[n:])
    if rest > 0:
        out.append({"name": "אחר", "amount": round(rest, 2)})
    return out


def build_pace(transactions, current_key, today=None):
    """Month-to-date vs. the previous month up to the *same day* — the wallet
    header's "am I ahead or behind" signal.

    Comparing a half-month to a whole month always looks like a win, so the
    previous month is cut at the same day-of-month as the current month's latest
    ledger date (clamped to the shorter month). The cut-off is the ledger's own
    latest date, not the wall clock, so stale data still compares like-for-like.

    ``average`` does the same against the mean of the trailing ``AVG_MONTHS``
    months the ledger covers (each cut at the same day), so one unusual
    September doesn't make every October look good.

    Uses the same inclusion rules as ``aggregate_by_month`` (no internal
    transfers, card-bill settlements or savings). ``daily_expense`` is the
    cumulative spend per day for the sparkline: the current month up to
    ``as_of_day``, the previous month in full (so its end-of-month is visible).

    ``today`` (a ``date``) drops rows dated after it: RiseUp emits card purchases
    at their future billing date (e.g. on 10-15, rows dated 10-22 and 10-29), and
    money that hasn't moved yet is not month-to-date. That also caps
    ``as_of_day`` at today, so the previous month and the average are cut at the
    same day. A stale ledger still uses its own latest date. ``None`` = no cap
    (pure, for tests); ``build()`` passes the local date.
    """
    prev_key = _prev_month(current_key)
    trailing = [prev_key]                      # the 12 months before this one
    for _ in range(AVG_MONTHS - 1):
        trailing.append(_prev_month(trailing[-1]))
    keys = {current_key, *trailing}
    cutoff = today.isoformat() if today else None
    rows = [t for t in transactions
            if (t.get("date") or "")[:7] in keys
            and not (cutoff and t["date"][:10] > cutoff)
            and not (t.get("internal_transfer") or t.get("card_bill_payment")
                     or t.get("savings"))]
    cur_days = [int(t["date"][8:10]) for t in rows if t["date"][:7] == current_key]
    as_of_day = max(cur_days) if cur_days else 1

    def side(key, upto):
        n = _days_in_month(key)
        daily = [0.0] * n
        income = expense = 0.0
        for t in rows:
            if t["date"][:7] != key:
                continue
            day = int(t["date"][8:10])
            amount = float(t.get("amount") or 0)
            is_in = t.get("is_income") or amount > 0
            if not is_in:
                daily[day - 1] += -amount
            if day <= upto:
                if is_in:
                    income += amount
                else:
                    expense += -amount
        by_cat = defaultdict(float)
        for t in rows:
            if t["date"][:7] == key and int(t["date"][8:10]) <= upto:
                amount = float(t.get("amount") or 0)
                if not (t.get("is_income") or amount > 0):
                    by_cat[(t.get("category") or "").strip() or "ללא קטגוריה"] += -amount
        cum, run = [], 0.0
        for d in daily:
            run += d
            cum.append(round(run, 2))
        return {
            "month": key,
            "income": round(income, 2),
            "expense": round(expense, 2),
            "net": round(income - expense, 2),
            "month_expense": cum[-1] if cum else 0.0,
            "by_category": top_categories(by_cat),
            "daily_expense": cum,
        }

    cur = side(current_key, as_of_day)
    cur["daily_expense"] = cur["daily_expense"][:as_of_day]
    prev = side(prev_key, min(as_of_day, _days_in_month(prev_key)))

    # 12-month average, cut at the same day — only months the ledger actually
    # covers count, so a gap (no scrape that month) doesn't drag the mean to 0.
    covered = {t["date"][:7] for t in rows}
    sides = [side(k, min(as_of_day, _days_in_month(k))) for k in trailing if k in covered]
    average = None
    if sides:
        n_days = _days_in_month(current_key)
        mean = lambda xs: round(sum(xs) / len(xs), 2)
        # cumulative curve per day; a shorter month holds its last value
        curve = [mean([sd["daily_expense"][min(i, len(sd["daily_expense"]) - 1)] for sd in sides])
                 for i in range(n_days)]
        average = {
            "months": len(sides),
            "income": mean([sd["income"] for sd in sides]),
            "expense": mean([sd["expense"] for sd in sides]),
            "month_expense": mean([sd["month_expense"] for sd in sides]),
            "daily_expense": curve,
        }
    return {"as_of_day": as_of_day, "days_in_month": _days_in_month(current_key),
            "current": cur, "previous": prev, "average": average}


def expected_for_month(forecast, month_key):
    """The forecast's full-month expectation for ``month_key`` — or None.

    Only the forecast's ``current_month`` block counts, and only when its budget
    month is the month being shown: a stale forecast (last month's budget) must
    not be passed off as this month's target. Returns positive figures, the same
    convention as the pace block it sits next to.
    """
    cur = (forecast or {}).get("current_month")
    if not cur or cur.get("forecast_month") != month_key:
        return None
    income = cur["income"]["total"]
    expense = cur["expenses"]["total"]
    return {
        "income": income,
        "expense": expense,
        "net": round(income - expense, 2),
        "source": f"forecast.py · RiseUp budget {cur.get('based_on_budget')}",
    }


# --- Metrics ----------------------------------------------------------------

def _verdict(value, *, good_above=None, bad_below=None, bad_above=None, good_below=None):
    """Map a value to good/warning/bad given thresholds. None -> neutral."""
    if value is None:
        return None
    if good_above is not None and value >= good_above:
        return "good"
    if bad_below is not None and value < bad_below:
        return "bad"
    if bad_above is not None and value > bad_above:
        return "bad"
    if good_below is not None and value <= good_below:
        return "good"
    return "warning"


def build_metrics(month, snapshot):
    """The computable subset of Plangram's 28 metrics (PRD §4). Forward-looking
    metrics (Plangram score, growth, missing-piece) are deferred to phase 2."""
    income = month["income"]
    expense = month["expense"]
    net = month["net"]
    totals = snapshot.get("totals", {})
    net_worth = totals.get("tracked_net_position")
    loan_service = totals.get("monthly_loan_service") or 0.0
    overdraft = totals.get("bank_balances_sum")

    debt_repayment_pct = round(loan_service / expense * 100, 1) if expense else None
    # Savings% proxy: net cashflow as a share of income — negative when the month
    # overspent. True net-worth-delta savings needs snapshot history (phase 2).
    savings_pct = round(net / income * 100, 1) if income else None

    metrics = [
        {
            "key": "net_cashflow", "name": "תזרים", "value": net, "units": CURRENCY,
            "rank": _verdict(net, good_above=0, bad_below=0), "higher_is_better": True,
            "description": "ההפרש בין ההכנסות להוצאות בחודש",
        },
        {
            "key": "income", "name": "הכנסות", "value": income, "units": CURRENCY,
            "rank": None, "higher_is_better": True,
            "description": "סך ההכנסות בחודש",
        },
        {
            "key": "expense", "name": "הוצאות", "value": expense, "units": CURRENCY,
            "rank": None, "higher_is_better": False,
            "description": "סך ההוצאות בחודש",
        },
        {
            "key": "net_worth", "name": "שווי נקי", "value": net_worth, "units": CURRENCY,
            "rank": _verdict(net_worth, good_above=0, bad_below=0), "higher_is_better": True,
            "description": "נכסים פחות התחייבויות (חשבונות במעקב בלבד)",
        },
        {
            "key": "debt_repayment_pct", "name": "אחוז החזר חוב", "value": debt_repayment_pct,
            "units": "%", "rank": _verdict(debt_repayment_pct, good_below=30, bad_above=50),
            "higher_is_better": False,
            "description": "שיעור החזר הלוואות מתוך סך ההוצאות החודשיות",
        },
        {
            "key": "savings_pct", "name": "אחוז חיסכון", "value": savings_pct, "units": "%",
            "rank": _verdict(savings_pct, good_above=15, bad_below=5), "higher_is_better": True,
            "description": "אומדן: התזרים כאחוז מההכנסה, שלילי כשההוצאות עולות על ההכנסות (אומדן — דורש היסטוריית שווי נקי לחישוב מדויק)",
            "estimated": True,
        },
        {
            "key": "overdraft", "name": "עודף בעובר ושב", "value": round(overdraft, 2) if overdraft is not None else None,
            "units": CURRENCY, "rank": _verdict(overdraft, good_above=0, bad_below=0),
            "higher_is_better": True,
            "description": "סך יתרות חשבונות העו""ש",
        },
    ]
    return metrics


# --- Charts -----------------------------------------------------------------

def _plot(graph_type, title, x_axis, datasets, ylabel=None, xlabel=None, name=None):
    return {
        "graph_type": graph_type, "graph_title": title,
        "xlabel": xlabel, "ylabel": ylabel,
        "x_axis": x_axis, "datasets": datasets, "unique_name": name,
    }


def build_charts(months, current_key):
    cur = months[current_key]

    today = {
        "income": cur["income"], "expense": cur["expense"],
        "saved": cur.get("saved", 0.0), "net": cur["net"],
    }

    income_ds = [
        {"name": INCOME_BUCKETS.get(b, b), "value": v}
        for b, v in sorted(cur["income_by_bucket"].items(), key=lambda kv: -kv[1])
    ]
    expense_ds = [
        {"name": EXPENSE_BUCKETS.get(b, b), "value": v}
        for b, v in sorted(cur["expense_by_bucket"].items(), key=lambda kv: -kv[1])
    ]

    # months trend (income / expense / net over available months)
    keys = list(months.keys())
    trend = _plot(
        "area", "תזרים לאורך זמן", keys,
        [
            {"name": "הכנסות", "ds": [months[k]["income"] for k in keys], "color": "#22c55e"},
            {"name": "הוצאות", "ds": [months[k]["expense"] for k in keys], "color": "#f97316"},
            {"name": "תזרים", "ds": [months[k]["net"] for k in keys], "color": "#6366f1"},
        ],
        ylabel=CURRENCY, name="cashflow_trend",
    )

    return {
        "today": today,
        "income_breakdown": _plot("pie", "הכנסות", [d["name"] for d in income_ds],
                                  income_ds, name="income_plot"),
        "expense_breakdown": _plot("pie", "הוצאות", [d["name"] for d in expense_ds],
                                   expense_ds, name="expense_plot"),
        "trend": trend,
    }


# --- Orchestration ----------------------------------------------------------

# --- Fixed expenses review ---------------------------------------------------
# The month's recurring bills (forecast.py's fixed envelopes) grouped by how
# realistically they can be cut — the "easy recurring cuts" lever in CLAUDE.md.
# Order = review order: cheapest wins first, committed debt last.

FIXED_GROUPS = [
    # key, label, ease, what to do about it, categories
    ("fees", "עמלות", "trivial", "לבקש ויתור מהבנק / חברת האשראי",
     {"עמלות", "דמי כרטיס", "עמלת דמי כרטיס - בנקים"}),
    ("subscriptions", "מנויים", "easy", "לבטל מה שלא בשימוש ומה שכפול",
     {"דיגיטל", "ספר"}),
    ("bills", "חשבונות ושירותים", "moderate", "להשוות ספקים ולמקח מחדש",
     {"תקשורת", "חשמל", "מים", "גז", "תמי 4", "ביטוח", "בריאות", "רכב"}),
    ("installments", "תשלומים ורכישות", "wait", "מסתיימים מעצמם — לא לפתוח חדשים",
     {"מוצרי חשמל לבית"}),
    ("committed", "דיור והלוואות", "committed", "פירעון מוקדם / מחזור — לא קיצוץ",
     {"דיור", "משכנתא", "הלוואה", "תשלומים"}),
]

# International-call plans are the same service from different carriers.
_SAME_SERVICE = [("שיחות לחו״ל", ("018", "019", "טלזר", "אקספון"))]


def _merchant_key(name):
    """'APPLE.COM/BILL   CORK  IRL' → 'APPLE.COM/BILL' — enough to spot repeats."""
    return " ".join(str(name).split()[:1]).upper()


def _last_charged(name, transactions):
    """Latest ledger date whose description starts like this bill's name."""
    probe = " ".join(str(name).split())[:10].lower()
    dates = [t["date"][:10] for t in transactions
             if t.get("date") and float(t.get("amount") or 0) < 0
             and " ".join((t.get("description") or "").split()).lower().startswith(probe)]
    return max(dates) if dates else None


def fixed_expenses(forecast, transactions, month_key):
    """Group this month's fixed bills for a "what can I cut?" review.

    Each group carries an ``ease`` (trivial → committed) and a one-line lever.
    Reviewable items (not loans/installments) flag ``duplicate`` when the same
    merchant bills more than once or two items are the same service (e.g. two international-call plans), and carry
    ``last_charged`` from the ledger so a cancelled service shows as stale.
    ``cuttable_total`` sums the fees + subscriptions groups — the low-effort
    ceiling, not a promise. Returns None without a current-month forecast.
    """
    cur = (forecast or {}).get("current_month")
    if not cur or cur.get("forecast_month") != month_key:
        return None
    items = cur["expenses"]["fixed_items"]

    counts = defaultdict(int)
    for it in items:
        counts[_merchant_key(it["name"])] += 1
    same_service = {}
    for label, needles in _SAME_SERVICE:
        hits = [it["name"] for it in items if any(n in it["name"] for n in needles)]
        if len(hits) > 1:
            same_service.update({h: label for h in hits})

    by_cat = {c: g for g in FIXED_GROUPS for c in g[4]}
    other = ("other", "אחר", "moderate", "לבדוק אם עדיין נחוץ", set())
    grouped = defaultdict(list)
    for it in items:
        g = by_cat.get((it.get("category") or "").strip(), other)
        name = " ".join(str(it["name"]).split())
        # Repeats only mean something for reviewable bills — several loans or
        # standing orders sharing a "פרעון"/"הו\"ק" prefix are not duplicates.
        reviewable = g[0] not in ("committed", "installments")
        dup = reviewable and (counts[_merchant_key(it["name"])] > 1 or it["name"] in same_service)
        grouped[g[0]].append({
            "name": name,
            "category": it.get("category"),
            "amount": round(float(it["amount"]), 2),
            "duplicate": dup,
            "duplicate_reason": same_service.get(it["name"]) or ("אותו ספק כמה פעמים" if dup else None),
            "last_charged": _last_charged(it["name"], transactions),
        })

    groups = []
    for key, label, ease, lever, _ in [*FIXED_GROUPS, other]:
        rows = sorted(grouped.get(key, []), key=lambda r: -r["amount"])
        if rows:
            groups.append({"key": key, "label": label, "ease": ease, "lever": lever,
                           "total": round(sum(r["amount"] for r in rows), 2), "items": rows})
    total = round(sum(g["total"] for g in groups), 2)
    cuttable = round(sum(g["total"] for g in groups if g["key"] in ("fees", "subscriptions")), 2)
    return {"month": month_key, "total": total, "cuttable_total": cuttable, "groups": groups}


def _load_optional(path):
    """Forecast is produced separately; the cashflow model still builds without it."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _local_today():
    """Today in Israel (UTC+3, matching ``generated_at``) — the pace cut-off."""
    return datetime.now(timezone(timedelta(hours=3))).date()


def build():
    with open(TRANSACTIONS, encoding="utf-8") as f:
        tx_doc = json.load(f)
    with open(SNAPSHOT, encoding="utf-8") as f:
        snapshot = json.load(f)

    transactions = tx_doc.get("transactions", [])
    months = aggregate_by_month(transactions)
    current = pick_current_month(months)
    if current is None:
        raise SystemExit("no transactions to build a cashflow from")

    forecast = _load_optional(FORECAST)
    metrics = build_metrics(months[current], snapshot)
    charts = build_charts(months, current)

    # Phase 2 — forward-looking net-worth projection
    import projection
    proj = projection.build(snapshot)
    metrics = metrics + proj["metrics"]

    # Day-by-day combined checking balance + safe-to-spend until payday
    import runway
    runway_block = runway.build_runway(
        transactions, snapshot["bank_accounts"], snapshot.get("savings", []),
        _local_today())
    # Mint-style monthly views (PRD 12): bills status, budgets, spending explorer
    import actions, bills, budgets, horizons, spending, validate
    budget_doc = bills.load_budget()
    bills_block = bills.build_bills(budget_doc, transactions, _local_today())
    budgets_block = budgets.build_budgets(budget_doc, _local_today(), budgets.load_overrides())
    spending_block = spending.build_spending(transactions, today=_local_today())
    import months_view
    months_view_block = months_view.build_months_view(
        transactions, forecast, budgets.load_history(), _local_today())

    model = {
        "generated_at": datetime.now(timezone.utc)
            .astimezone(timezone(timedelta(hours=3))).isoformat(timespec="seconds"),
        "currency": "ILS",
        "current_month": current,
        "note": (
            "Cashflow model (Phase 1: today + breakdowns). 'current_month' is the "
            "latest complete calendar month. Savings% is an estimate pending "
            "net-worth history. Forward projections not yet implemented."
        ),
        "metrics": metrics,
        "today": charts["today"],
        "pace": {**build_pace(transactions, current, today=_local_today()),
                 "expected": expected_for_month(forecast, current)},
        "fixed_expenses": fixed_expenses(forecast, transactions, current),
        "charts": {
            **{k: v for k, v in charts.items() if k != "today"},
            "net_worth": proj["chart"],
        },
        "projection": {
            "config": proj["config"],
            "net_worth_today": proj["net_worth_today"],
            "net_worth_at_retirement": proj["net_worth_at_retirement"],
            "total_loan_balance_today": proj["total_loan_balance_today"],
            "loans_modeled": proj["loans_modeled"],
            "focal_points": proj["focal_points"],
        },
        "runway": runway_block,
        "bills": bills_block,
        "budgets": budgets_block,
        "spending": spending_block,
        "horizons": horizons.build_horizons(transactions),
        "months_view": months_view_block,
        "actions": actions.build_actions(
            runway_block, bills_block, budgets_block,
            fixed_expenses(forecast, transactions, current),
            snapshot.get("syncs", []), _local_today(),
            validate.validation_actions(_load_optional(VALIDATION) or {})),
        "months": [
            {"month": k, "income": v["income"], "expense": v["expense"], "net": v["net"],
             "count": v["count"]}
            for k, v in months.items()
        ],
    }

    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)

    _write_md(model)
    _write_html(model)
    return model


def _write_md(model):
    cur = model["current_month"]
    t = model["today"]
    lines = [
        f"# Cashflow — {cur}", "",
        f"*Generated {model['generated_at']} · currency ILS*", "",
        "## This month", "",
        f"| | {CURRENCY} |", "|---|---:|",
        f"| הכנסות | {t['income']:,.0f} |",
        f"| הוצאות | {t['expense']:,.0f} |",
        *( [f"| חיסכון | {t['saved']:,.0f} |"] if t.get('saved') else [] ),
        f"| **תזרים** | **{t['net']:,.0f}** |",
        "", "## Metrics", "",
        "| מדד | ערך | דירוג |", "|---|---:|:---:|",
    ]
    pill = {"good": "🟢", "bad": "🔴", "warning": "🟡", None: "·"}
    for m in model["metrics"]:
        v = m["value"]
        vs = "—" if v is None else (f"{v:,.1f}%" if m["units"] == "%" else f"{v:,.0f} {m['units']}")
        lines.append(f"| {m['name']} | {vs} | {pill.get(m['rank'], '·')} |")
    lines += ["", "## Expense breakdown", ""]
    for d in model["charts"]["expense_breakdown"]["datasets"]:
        lines.append(f"- {d['name']}: {d['value']:,.0f} {CURRENCY}")
    lines += ["", "## Income breakdown", ""]
    for d in model["charts"]["income_breakdown"]["datasets"]:
        lines.append(f"- {d['name']}: {d['value']:,.0f} {CURRENCY}")
    rw = model.get("runway")
    if rw:
        lines += ["", "## Balance runway", "",
                  f"- Start balance: {rw['start_balance']:,.0f} {CURRENCY} (limit {rw['overdraft_limit']:,.0f})"]
        if rw["next_payday"]:
            lines.append(f"- Next payday: {rw['next_payday']['date']} (+{rw['next_payday']['amount']:,.0f})")
        if rw["safe_to_spend"] is not None:
            lines.append(f"- Safe to spend until payday: {rw['safe_to_spend']:,.0f} {CURRENCY}")
        lines.append(f"- Low point: {rw['low_point']['balance']:,.0f} on {rw['low_point']['date']}")
    lines.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _write_html(model):
    """Self-contained RTL dashboard with the model embedded inline (opens via
    file:// — no server, no CORS). Charts via Chart.js CDN; degrades to tables
    offline."""
    payload = json.dumps(model, ensure_ascii=False)
    html = _HTML_TEMPLATE.replace("/*__DATA__*/null", payload)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)


_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>תזרים כספי</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root{ --bg:#f1f0ee; --card:#fff; --ink:#1f2430; --muted:#6b7280;
         --good:#16a34a; --goodbg:#dcfce7; --bad:#dc2626; --badbg:#fee2e2;
         --warn:#b45309; --warnbg:#fef3c7; --accent:#6366f1; }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--ink);
       font-family:-apple-system,"Segoe UI",Rubik,Arial,sans-serif}
  .wrap{max-width:1100px;margin:0 auto;padding:28px 20px 60px}
  header{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:6px}
  h1{font-size:26px;margin:0}
  .sub{color:var(--muted);font-size:13px;margin-bottom:22px}
  .kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:22px}
  .kpi{background:var(--card);border-radius:16px;padding:18px;text-align:center;
       box-shadow:0 1px 3px rgba(0,0,0,.05)}
  .kpi .name{color:var(--muted);font-size:14px;margin-bottom:8px}
  .kpi .val{font-size:30px;font-weight:700;letter-spacing:-.5px}
  .kpi .pill{display:inline-block;margin-top:10px;font-size:12px;font-weight:600;
             padding:3px 12px;border-radius:999px}
  .good{color:var(--good);background:var(--goodbg)}
  .bad{color:var(--bad);background:var(--badbg)}
  .warn{color:var(--warn);background:var(--warnbg)}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}
  @media(max-width:760px){.grid{grid-template-columns:1fr}}
  .panel{background:var(--card);border-radius:16px;padding:20px;box-shadow:0 1px 3px rgba(0,0,0,.05)}
  .panel h2{font-size:16px;margin:0 0 14px}
  .today{display:flex;justify-content:space-around;text-align:center;margin-bottom:6px}
  .today .t{font-size:13px;color:var(--muted)}
  .today .n{font-size:22px;font-weight:700}
  .pos{color:var(--good)} .neg{color:var(--bad)}
  .note{margin-top:26px;font-size:12px;color:var(--muted);line-height:1.6;
        background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;padding:14px}
  canvas{max-height:260px}
  .brand{font-weight:700;color:var(--accent)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>תזרים כספי</h1>
    <span class="brand">Finance</span>
  </header>
  <div class="sub" id="sub"></div>

  <div class="kpis" id="kpis"></div>

  <div class="panel" style="margin-bottom:18px">
    <h2>עו"ש — שווי נקי לאורך זמן</h2>
    <canvas id="netWorthChart" style="max-height:300px"></canvas>
  </div>

  <div class="grid">
    <div class="panel">
      <h2>התזרים — נכון לחודש</h2>
      <div class="today" id="today"></div>
      <canvas id="todayChart"></canvas>
    </div>
    <div class="panel">
      <h2>תזרים לאורך זמן</h2>
      <canvas id="trendChart"></canvas>
    </div>
    <div class="panel">
      <h2>הכנסות</h2>
      <canvas id="incomeChart"></canvas>
    </div>
    <div class="panel">
      <h2>הוצאות</h2>
      <canvas id="expenseChart"></canvas>
    </div>
  </div>

  <div class="note" id="note"></div>
</div>

<script>
const MODEL = /*__DATA__*/null;
const ILS = new Intl.NumberFormat('he-IL',{maximumFractionDigits:0});
const fmt = (v,u)=> v==null ? '—' : (u==='%' ? ILS.format(v)+'%' : ILS.format(v)+' ₪');
const rankClass = r => r==='good'?'good':r==='bad'?'bad':r==='warning'?'warn':'';
const rankLabel = r => r==='good'?'מעולה':r==='bad'?'לא משהו':r==='warning'?'בינוני':'';

document.getElementById('sub').textContent =
  `החודש: ${MODEL.current_month} · נוצר ${MODEL.generated_at}`;

// KPI cards
const kpis = document.getElementById('kpis');
MODEL.metrics.forEach(m=>{
  const pill = m.rank ? `<div class="pill ${rankClass(m.rank)}">${rankLabel(m.rank)}</div>` : '';
  kpis.insertAdjacentHTML('beforeend',
    `<div class="kpi"><div class="name">${m.name}</div>
       <div class="val">${fmt(m.value,m.units)}</div>${pill}</div>`);
});

// Today tiles
const t = MODEL.today;
document.getElementById('today').innerHTML =
  `<div><div class="t">הכנסות</div><div class="n pos">${fmt(t.income,'₪')}</div></div>
   <div><div class="t">הוצאות</div><div class="n neg">${fmt(t.expense,'₪')}</div></div>
   ${t.saved ? `<div><div class="t">חיסכון</div><div class="n" style="color:var(--accent)">${fmt(t.saved,'₪')}</div></div>` : ''}
   <div><div class="t">תזרים</div><div class="n ${t.net>=0?'pos':'neg'}">${fmt(t.net,'₪')}</div></div>`;

if (typeof Chart === 'undefined') {
  document.getElementById('note').textContent =
    'אין חיבור לאינטרנט — הגרפים לא נטענו (Chart.js). הנתונים המספריים מוצגים מעלה.';
} else {
  const PIE = ['#6366f1','#22c55e','#f97316','#eab308','#06b6d4','#ec4899','#94a3b8'];
  new Chart(todayChart,{type:'bar',data:{labels:['הכנסות','הוצאות'],
    datasets:[{data:[t.income,t.expense],backgroundColor:['#22c55e','#f97316']}]},
    options:{plugins:{legend:{display:false}},scales:{y:{beginAtZero:true}}}});

  const tr = MODEL.charts.trend;
  new Chart(trendChart,{type:'line',data:{labels:tr.x_axis,
    datasets:tr.datasets.map(d=>({label:d.name,data:d.ds,borderColor:d.color,
      backgroundColor:d.color+'33',fill:true,tension:.3}))},
    options:{plugins:{legend:{position:'bottom'}}}});

  const nw = MODEL.charts.net_worth;
  if (nw) new Chart(netWorthChart,{type:'line',data:{labels:nw.x_axis,
    datasets:nw.datasets.map(d=>({label:d.name,data:d.ds,borderColor:d.color,
      backgroundColor:d.color+'22',fill:d.name.includes('שווי'),tension:.25,
      pointRadius:0}))},
    options:{plugins:{legend:{position:'bottom'}},
      scales:{y:{ticks:{callback:v=>ILS.format(v)}}}}});

  const pie = (cv,plot)=> new Chart(cv,{type:'doughnut',
    data:{labels:plot.datasets.map(d=>d.name),
      datasets:[{data:plot.datasets.map(d=>d.value),backgroundColor:PIE}]},
    options:{plugins:{legend:{position:'bottom'}}}});
  pie(incomeChart, MODEL.charts.income_breakdown);
  pie(expenseChart, MODEL.charts.expense_breakdown);
}

document.getElementById('note').textContent = (document.getElementById('note').textContent||'')
  + ' ' + (MODEL.note||'');
</script>
</body>
</html>
"""


if __name__ == "__main__":
    m = build()
    print(f"cashflow.json written — current month {m['current_month']}, "
          f"net {m['today']['net']:,.0f} ₪, {len(m['months'])} months")
