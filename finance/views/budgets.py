"""
Budgets — Mint-style "left this month" per category (docs/plangram-prd/12, Phase 2),
and the month's three blocks: fixed, variable and what is left.

Lines are **our categories** (finance/categories.py). The *planned* amount still
comes from RiseUp's budget document (data/riseup/raw/budget_current.json): every
`trackingCategory` envelope is a planned amount for one budget line (weekly lines
such as כלכלה are split into several envelopes sharing a name), its name read
through `categories.tracking_category` (חופשה ✈️ -> תיירות; תחבורה is a whole
group). The *spent* amount is the ledger's: the cycle's expense rows of that
category (or group) whose `kind` is variable — fixed charges are the fixed block,
not a budget line — minus refunds (a positive row in that category). Offsets are
already netted by `offsets.cashflow_view`.

Optional user overrides: the `budget_lines` table `{category: amount}` replaces
RiseUp's planned amount, or adds a line RiseUp does not have (db/budget_store.py).
Old keys holding a RiseUp envelope name still work.

Cycle bounds come from `cashflowStartDay` (not the calendar month): the cycle of
budget month YYYY-MM runs from day N of that month to day N-1 of the next. Every
ledger row dated inside the cycle counts, including card purchases RiseUp dates
at their coming billing day.

`summary` — the month in three blocks (plus debt service), split the way
months_view splits a month (`months_view.classify_expense`):

    fixed         kind=fixed rows (loans and the mortgage excluded), actual so far;
                  expected = actual + the recurring fixed charges of the previous
                  two cycles that have not hit yet (`fixed_items`)
    variable      kind=variable rows, actual so far; estimate = Σ over variable
                  categories of the median spend of the last 3-6 cycles; planned =
                  the budget lines' total; projected = actual + estimate × the share
                  of the cycle still ahead (a daily run-rate, so a trip-heavy
                  median does not swamp the last days of the cycle)
    debt_savings  loans, the mortgage and savings deposits; expected like fixed
    income        actual so far; expected = the forecast's income for this month
    left          free money: income - fixed - debt_savings - the variable PLAN.
                  Not planned for anything; the household aims for ~0 (every
                  shekel assigned). Fixed / debt at expected, income at
                  max(actual, expected).
    projected_end where the cycle is heading: the same, with variable at
                  `projected` instead of the plan

Pure: no file, database or clock access. data/budgets.py loads the inputs and
re-exports these names.
"""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from finance import categories
from finance.categories import FIXED, VARIABLE
from finance.views import months_view

HISTORY_CYCLES = 4
ESTIMATE_CYCLES = 6       # cycles feeding the variable estimate (median)...
MIN_ESTIMATE_CYCLES = 3   # ...and the fewest the ledger must cover to give one
MATCH_TOLERANCE = 0.10    # a fixed charge "already hit" this cycle: same merchant, ±10%


def fold_merges(plan, merges):
    """`plan` ({category: amount}) with each merged category's amount added to its target."""
    out = {}
    for name, amount in plan.items():
        into = (merges or {}).get(name, name)
        out[into] = round(out.get(into, 0.0) + amount, 2)
    return out

def planned_lines(budget):
    """{line name: planned} from the doc's trackingCategory envelopes, named
    through `categories.tracking_category`; hidden envelopes are skipped."""
    lines = defaultdict(float)
    for e in budget.get("envelopes") or []:
        if e.get("type") != "trackingCategory":
            continue
        name = categories.tracking_category(
            ((e.get("details") or {}).get("trackingCategory") or {}).get("name"))
        if name:
            lines[name] += float(e.get("originalAmount") or 0)
    return dict(lines)


def _start_in(year, month, day):
    """`day` of the month, clamped to the month's length (start day 31 in June)."""
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    last = (nxt - timedelta(days=1)).day
    return date(year, month, min(day, last))


def cycle_bounds(budget_date, start_day):
    """(start, end) inclusive for budget month 'YYYY-MM' with a cashflow start day."""
    y, m = int(budget_date[:4]), int(budget_date[5:7])
    start = _start_in(y, m, start_day)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, _start_in(ny, nm, start_day) - timedelta(days=1)


def shift_month(ym, n):
    idx = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + n
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def _cycle_rows(rows, month, start_day):
    start, end = cycle_bounds(month, start_day)
    lo, hi = start.isoformat(), end.isoformat()
    return [t for t in rows if lo <= (t.get("date") or "")[:10] <= hi]


def _cashflow(t):
    return not (t.get("internal_transfer") or t.get("card_bill_payment"))


def _line_of(t, name, scope):
    """Does ledger row `t` belong to budget line `name`?"""
    return (t.get("category_group") if scope == "group" else t.get("category")) == name


def line_spent(rows, name, scope="category"):
    """Variable spend of one budget line in `rows` (one cycle), refunds subtracted,
    never below 0 (a refund of a fixed charge — the ₪1,512 הפול ביטוח חובה refund
    in group תחבורה — must not turn a line negative). A line on a fixed-by-default
    category (an override on ביטוח) counts every kind."""
    kinds = {VARIABLE} if scope == "group" or categories.CATEGORY_KIND.get(name, VARIABLE) == VARIABLE \
        else {FIXED, VARIABLE}
    total = 0.0
    for t in rows:
        if not _cashflow(t) or t.get("savings") or not _line_of(t, name, scope):
            continue
        amount = float(t.get("amount") or 0)
        if amount < 0 and t.get("kind") in kinds:
            total += -amount
        elif amount > 0:
            total -= amount
    return max(total, 0.0)


def _covered_months(rows, month, n):
    """The `n` budget months before `month` that the ledger has any row in."""
    have = {(t.get("date") or "")[:7] for t in rows}
    return [m for m in (shift_month(month, -i) for i in range(n, 0, -1)) if m in have]


def _stem(merchant):
    """'SpotifyIL' and 'SPOTIFY P47D8D' -> 'SPOTIF': a service that moved card
    keeps its name's start, not its merchant key."""
    return "".join(ch for ch in (merchant or "").upper() if ch.isalnum())[:6]


def _same_charge(a, b):
    amount = abs(float(a["amount"]))
    return (_stem(a.get("merchant")) == _stem(b.get("merchant"))
            and abs(abs(float(b["amount"])) - amount) <= max(amount * MATCH_TOLERANCE, 2))


def fixed_items(ledger, month, start_day=1):
    """This cycle's fixed expenses, for the "what can I cut?" review and the fixed block.

    Every kind=fixed expense row in the cycle, plus — flagged ``expected`` — each
    ``recurring`` fixed charge of the previous cycle that also hit the cycle before
    it and has not hit in this one yet (same merchant, amount ±10%). Two cycles keep
    a bi-monthly bill from being expected in its off month. Rows are the ledger's
    own dicts (real money, not netted) plus ``expected``."""
    fixed = [t for t in ledger if t.get("kind") == FIXED and categories.is_expense(t)]
    cur = _cycle_rows(fixed, month, start_day)
    prev = _cycle_rows(fixed, shift_month(month, -1), start_day)
    prev2 = _cycle_rows(fixed, shift_month(month, -2), start_day)
    out = [{**t, "expected": False} for t in cur]
    for t in prev:
        if (t.get("recurring") and any(_same_charge(t, o) for o in prev2)
                and not any(_same_charge(t, o) for o in cur)):
            out.append({**t, "expected": True})
    return out


def _median_estimates(rows, month, start_day):
    """{category: median variable spend} over the last ESTIMATE_CYCLES covered
    cycles (a cycle without the category counts 0); {} with fewer than
    MIN_ESTIMATE_CYCLES."""
    months = _covered_months(rows, month, ESTIMATE_CYCLES)
    if len(months) < MIN_ESTIMATE_CYCLES:
        return {}
    per = []
    for m in months:
        spent = defaultdict(float)
        for t in _cycle_rows(rows, m, start_day):
            if _cashflow(t) and t.get("kind") == VARIABLE:
                spent[t.get("category") or "אחר"] += -float(t.get("amount") or 0)
        per.append(spent)
    names = {n for p in per for n in p}
    return {n: median(p.get(n, 0.0) for p in per) for n in names}


def build_summary(rows, ledger, month, start_day, expected_income=None, planned_variable=None, as_of=None):
    """The `summary` block (see the module docstring). `rows` is the offset-netted
    ledger (`offsets.cashflow_view`), `ledger` the real money (fixed matching)."""
    actual = defaultdict(float)
    var_actual = defaultdict(float)
    for t in _cycle_rows(rows, month, start_day):
        if not _cashflow(t):
            continue
        amount = float(t.get("amount") or 0)
        if t.get("savings"):
            actual["debt_savings"] += -amount
        elif t.get("is_income") or amount > 0:
            actual["income"] += amount
        else:
            key = months_view.classify_expense(t)
            actual[key] += -amount
            if key == VARIABLE:
                var_actual[t.get("category") or "אחר"] += -amount
    pending = defaultdict(float)
    for t in fixed_items(ledger, month, start_day):
        if t["expected"]:
            pending[months_view.classify_expense(t)] += -float(t["amount"])
    estimates = _median_estimates(rows, month, start_day)

    r = lambda x: None if x is None else round(x, 2)
    income = {"actual": r(actual["income"]), "expected": r(expected_income)}
    income["value"] = r(max(actual["income"], expected_income or 0.0))
    blocks = {"income": income}
    for key in (FIXED, "debt_savings"):
        a = actual[key]
        blocks[key] = {"actual": r(a), "expected": r(a + pending[key]), "value": r(a + pending[key])}
    est = sum(estimates.values()) if estimates else None
    by_cat = [{"name": n, "actual": r(var_actual.get(n, 0.0)), "estimate": r(estimates.get(n))}
              for n in set(var_actual) | set(estimates)]
    by_cat.sort(key=lambda c: -max(c["actual"], c["estimate"] or 0))
    start, end = cycle_bounds(month, start_day)
    cycle_days = (end - start).days + 1
    days_left = cycle_days if as_of is None else min(max((end - as_of).days + 1, 0), cycle_days)
    projected = actual[VARIABLE] + (est or 0.0) * days_left / cycle_days
    blocks[VARIABLE] = {"actual": r(actual[VARIABLE]), "estimate": r(est), "planned": r(planned_variable),
                        "projected": r(projected), "value": r(projected), "days_left": days_left,
                        "categories": by_cat}
    committed = blocks["income"]["value"] - blocks[FIXED]["value"] - blocks["debt_savings"]["value"]
    plan = planned_variable if planned_variable is not None else (est or 0.0)
    blocks["left"] = r(committed - plan)
    blocks["projected_end"] = r(committed - projected)
    blocks["estimate_cycles"] = len(_covered_months(rows, month, ESTIMATE_CYCLES))
    return blocks


def build_budgets(budget, transactions, as_of, overrides=None, ledger=None, expected_income=None,
                  merges=None):
    """Budget block for the app, or None when there is no budget doc.

    `transactions` is the offset-netted ledger (`offsets.cashflow_view`); `ledger`
    the real money for matching fixed charges (defaults to `transactions`). `as_of`
    is a date. Lines are sorted by planned desc; each carries its spend in the
    last HISTORY_CYCLES cycles (`history`) and the median of the last
    ESTIMATE_CYCLES (`estimate`). `expected_income` (the forecast's) feeds `summary`.
    `merges` ({category: into}, from the database) adds a merged category's plan to its
    target's: the ledger already counts its rows there.
    """
    if not budget:
        return None
    overrides = fold_merges({categories.tracking_category(k) or k: v for k, v in (overrides or {}).items()},
                            merges)
    ledger = transactions if ledger is None else ledger
    month = budget.get("budgetDate") or as_of.strftime("%Y-%m")
    start_day = int(budget.get("cashflowStartDay") or 1)
    start, end = cycle_bounds(month, start_day)
    # Once seeded (`budgets.py seed`), the household's store is the whole plan: a line
    # removed from it is gone, not back to RiseUp's (e.g. its ₪1 placeholders).
    planned_by = {} if overrides else fold_merges(planned_lines(budget), merges)
    cur = _cycle_rows(transactions, month, start_day)
    history_months = _covered_months(transactions, month, HISTORY_CYCLES)
    estimate_months = _covered_months(transactions, month, ESTIMATE_CYCLES)
    by_month = {m: _cycle_rows(transactions, m, start_day) for m in set(history_months) | set(estimate_months)}

    names = {**planned_by, **overrides}
    covered = set(names) | {c for n in names if n in categories.GROUP_KEY and n not in categories.CATEGORY_GROUP
                            for c, g in categories.CATEGORY_GROUP.items() if categories.GROUP_NAME[g] == n}
    # A variable category the household spends on but has no line for shows at ₪0
    # with its usual month, so the editor can decide what to plan.
    unplanned = {t.get("category") for m in estimate_months for t in by_month[m]
                 if t.get("kind") == VARIABLE and _cashflow(t)
                 and categories.CATEGORY_KIND.get(t.get("category")) == VARIABLE} - covered
    rows = []
    for name in [*names, *sorted(unplanned)]:
        if name in unplanned and not any(line_spent(by_month[m], name) for m in estimate_months):
            continue
        if name in unplanned and not line_spent(cur, name) \
                and not median(line_spent(by_month[m], name) for m in estimate_months):
            continue   # nothing this month and a ₪0 usual month: not worth a line
        scope = "group" if name in categories.GROUP_KEY and name not in categories.CATEGORY_GROUP else "category"
        source = "override" if name in overrides else "riseup" if name in planned_by else "unplanned"
        planned = overrides[name] if source == "override" else planned_by.get(name, 0.0)
        spent = line_spent(cur, name, scope)
        past = [line_spent(by_month[m], name, scope) for m in estimate_months]
        rows.append({
            "name": name,
            "scope": scope,
            "group": name if scope == "group" else categories.group_of(name),
            "planned": round(planned, 2),
            "spent": round(spent, 2),
            "left": round(planned - spent, 2),
            "pct": round(spent / planned * 100, 1) if planned > 0 else None,
            "over": spent > planned and source != "unplanned",
            "source": source,
            "estimate": round(median(past), 2) if len(past) >= MIN_ESTIMATE_CYCLES else None,
            "history": [{"cycle": m, "spent": round(line_spent(by_month[m], name, scope), 2)}
                        for m in history_months],
        })
    rows.sort(key=lambda r: (-r["planned"], r["name"]))

    planned = round(sum(r["planned"] for r in rows), 2)
    spent = round(sum(r["spent"] for r in rows), 2)
    left = round(planned - spent, 2)
    days_left = max((end - as_of).days + 1, 0)
    return {
        "cycle_start": start.isoformat(),
        "cycle_end": end.isoformat(),
        "days_left": days_left,
        "total_planned": planned,
        "total_spent": spent,
        "left": left,
        "per_day": round(left / days_left, 2) if left > 0 and days_left else None,
        "categories": rows,
        "summary": build_summary(transactions, ledger, month, start_day, expected_income,
                                 planned_variable=planned, as_of=as_of),
    }

def set_override(overrides, category, amount):
    """New overrides dict with `category` planned at `amount` (pure)."""
    return {**overrides, category: float(amount)}


def unset_override(overrides, category):
    """New overrides dict without `category` (pure)."""
    return {k: v for k, v in overrides.items() if k != category}
