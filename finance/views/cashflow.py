"""The cashflow model's month aggregates, pace, metrics, charts and fixed-expense review.

Pure functions over ledger rows (finance/views/household.py feeds them); the cashflow.json
assembly and its writers stay in data/cashflow.py. See docs/plangram-prd/01-cashflow.md.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from finance import categories
from finance.merchants import merchant_name

CURRENCY = "₪"

# --- Category bucketing -----------------------------------------------------
# The ledger's category (finance/categories.py) folded into the cashflow buckets
# the dashboard charts and KPIs agree on. Everyday spend is "running"; income is
# "work" only when it is pay (salary, reserve duty).

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

TAX_CATEGORIES = {"מס הכנסה", "ביטוח לאומי", "עמלות"}
WORK_INCOME = {"משכורת", "מילואים"}
BENEFIT_INCOME = {"ביטוח לאומי"}


def _expense_bucket(category):
    category = (category or "").strip()
    if category in categories.DEBT_CATEGORIES:
        return "loans"
    if category in TAX_CATEGORIES:
        return "taxes"
    if categories.CATEGORY_GROUP.get(category) == "income_savings":
        return "investments"     # a deposit to a savings product, e.g. הראל פנסיה
    return "running"


def _income_bucket(category):
    category = (category or "").strip()
    if category in WORK_INCOME:
        return "work"
    if category in BENEFIT_INCOME:
        return "benefits"
    return "other"


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


def pick_current_month(months, today):
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
    this_month = today.strftime("%Y-%m")
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
# The month's fixed expenses (ledger rows of kind "fixed", budgets.fixed_items)
# grouped by how realistically they can be cut — the "easy recurring cuts" lever in
# CLAUDE.md. Groups and their order are categories.LEVERS: cheapest wins first,
# committed debt last.

# International-call plans are the same service from different carriers.
_SAME_SERVICE = [("שיחות לחו״ל", ("018", "019", "טלזר", "אקספון"))]


def _last_charged(merchant, transactions):
    """Latest ledger date this merchant charged."""
    dates = [t["date"][:10] for t in transactions
             if t.get("date") and float(t.get("amount") or 0) < 0
             and (t.get("merchant") or merchant_name(t.get("description"))) == merchant]
    return max(dates) if dates else None


def fixed_expenses(transactions, month_key, start_day=1):
    """Group this month's fixed expenses for a "what can I cut?" review.

    Items are the month's kind=fixed ledger rows plus the recurring ones still
    expected (``budgets.fixed_items``), named by their cleaned description and
    grouped by ``categories.lever``. Each group carries an ``ease`` (trivial →
    committed) and a one-line lever. Reviewable items (not loans/installments)
    flag ``duplicate`` when the same merchant bills more than once or two items
    are the same service (e.g. two international-call plans), and carry
    ``last_charged`` so a cancelled service shows as stale. ``cuttable_total``
    sums the fees + subscriptions groups — the low-effort ceiling, not a promise.
    Returns None when the month has no fixed expense.
    """
    from finance.views import bills, budgets
    rows = budgets.fixed_items(transactions, month_key, start_day)
    if not rows:
        return None
    items = []
    for t in rows:
        name = bills.clean_name(t.get("description"))
        merchant = t.get("merchant") or merchant_name(t.get("description"))
        items.append((t, name, merchant))

    counts = defaultdict(int)
    for _, _, merchant in items:
        counts[merchant] += 1
    same_service = {}
    for label, needles in _SAME_SERVICE:
        hits = [name for _, name, _ in items if any(n in name for n in needles)]
        if len(hits) > 1:
            same_service.update({h: label for h in hits})

    grouped = defaultdict(list)
    for t, name, merchant in items:
        key = categories.lever(t.get("category"), t.get("source_category"))[0]
        # Repeats only mean something for reviewable bills — several loans or
        # standing orders sharing a "פרעון"/"הו\"ק" prefix are not duplicates.
        reviewable = key not in ("committed", "installments")
        dup = reviewable and (counts[merchant] > 1 or name in same_service)
        grouped[key].append({
            "name": name,
            "category": t.get("category"),
            "group": t.get("category_group") or categories.group_of(t.get("category")),
            "block": "debt_savings" if t.get("category") in categories.DEBT_CATEGORIES else "fixed",
            "amount": round(abs(float(t["amount"])), 2),
            "expected": t["expected"],
            "duplicate": dup,
            "duplicate_reason": same_service.get(name) or ("אותו ספק כמה פעמים" if dup else None),
            "last_charged": _last_charged(merchant, transactions),
        })

    groups = []
    for key, label, ease, lever in categories.LEVERS:
        rows = sorted(grouped.get(key, []), key=lambda r: -r["amount"])
        if rows:
            groups.append({"key": key, "label": label, "ease": ease, "lever": lever,
                           "total": round(sum(r["amount"] for r in rows), 2), "items": rows})
    total = round(sum(g["total"] for g in groups), 2)
    cuttable = round(sum(g["total"] for g in groups if g["key"] in ("fees", "subscriptions")), 2)
    return {"month": month_key, "total": total, "cuttable_total": cuttable, "groups": groups}
