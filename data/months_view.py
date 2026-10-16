#!/usr/bin/env python3
"""Months view — a month-by-month "expected vs actual" table for the app.

``build_months_view`` is pure: ledger rows + the forecast + RiseUp budget history
docs in, one dict out (the ``months_view`` key of cashflow.json).

Layout, oldest to newest: ``past`` complete months (kind ``actual``), the month of
``as_of`` (``current``) and ``future`` forecast months (``projected``). All money is
positive; ``net = income - expense``.

Actuals follow ``cashflow.aggregate_by_month``: card-bill settlements and internal
transfers are out, savings outflows are kept (they left checking, so ``expense``
includes them under ``debt_savings``), and rows dated after ``as_of`` are dropped
(RiseUp emits card purchases at their future billing date).

Every expense row lands in exactly one group:

* ``debt_savings`` - category ``הלוואה``/``משכנתא`` or a savings-flagged row.
* ``fixed`` - recurring (same normalized description seen in >= 2 of the 3 months
  before that month, the runway recurrence rule) or a category from the fixed
  groups of ``cashflow.FIXED_GROUPS`` (rent, bills, subscriptions, fees, ...).
* ``variable`` - everything else.

``expected`` per group:

* current / projected months - the forecast block of that month: ``income`` =
  ``income.total``; ``debt_savings`` = loan/mortgage ``fixed_items``; ``fixed`` =
  the other fixed items; ``variable`` = ``discretionary_total``.
* past months - the RiseUp budget doc whose ``budgetDate`` is that month: ``fixed``
  envelopes (income flag -> income, loan/mortgage category -> debt_savings, else
  fixed; internal transfers skipped) and ``trackingCategory`` envelopes
  ``originalAmount`` (variable). ``None`` when no doc exists.

``projected_end`` (current month): income = max(actual, expected); fixed and
debt_savings = actual + whatever expected is still unseen (floored at 0); variable =
max(actual, expected). Null when the forecast does not cover the current month.
"""
from collections import defaultdict
from datetime import date

import cashflow
import runway

DEBT_CATEGORIES = {"הלוואה", "משכנתא"}
FIXED_CATEGORIES = {c for g in cashflow.FIXED_GROUPS for c in g[4]} - DEBT_CATEGORIES
LOOKBACK = 3
MIN_SEEN = 2
TOP_CATEGORIES = 12

GROUPS = [
    ("income", "הכנסות"),
    ("fixed", "הוצאות קבועות"),
    ("variable", "הוצאות משתנות"),
    ("debt_savings", "הלוואות וחיסכון"),
]


def _shift(ym, n):
    idx = int(ym[:4]) * 12 + int(ym[5:7]) - 1 + n
    return f"{idx // 12}-{idx % 12 + 1:02d}"


def _r(x):
    return None if x is None else round(float(x), 2)


def _recurrence_index(rows):
    """{description: {months seen}} over expense rows."""
    seen = defaultdict(set)
    for t in rows:
        if float(t.get("amount") or 0) < 0 and not t.get("savings"):
            seen[runway._norm(t.get("description"))].add(t["date"][:7])
    return seen


def classify_expense(t, seen):
    """Group key for one expense row (see module docstring)."""
    if t.get("savings") or (t.get("category") or "").strip() in DEBT_CATEGORIES:
        return "debt_savings"
    ym = t["date"][:7]
    prior = {_shift(ym, -i) for i in range(1, LOOKBACK + 1)}
    if len(seen.get(runway._norm(t.get("description")), set()) & prior) >= MIN_SEEN:
        return "fixed"
    if (t.get("category") or "").strip() in FIXED_CATEGORIES:
        return "fixed"
    return "variable"


def _actuals(transactions, as_of):
    """{month: {"groups": {key: total}, "cats": {name: [amount, count]}}}"""
    cutoff = as_of.isoformat()
    rows = [t for t in transactions
            if not cashflow.is_non_cashflow(t) and len(t.get("date") or "") >= 10
            and t["date"][:10] <= cutoff]
    seen = _recurrence_index(rows)
    out = defaultdict(lambda: {"groups": defaultdict(float), "cats": defaultdict(lambda: [0.0, 0])})
    for t in rows:
        amount = float(t.get("amount") or 0)
        m = out[t["date"][:7]]
        if t.get("savings"):
            m["groups"]["debt_savings"] += -amount
        elif t.get("is_income") or amount > 0:
            m["groups"]["income"] += amount
        else:
            m["groups"][classify_expense(t, seen)] += -amount
            c = m["cats"][(t.get("category") or "").strip() or "אחר"]
            c[0] += -amount
            c[1] += 1
    return out


def _expected_from_forecast(block):
    """Group expectations from one forecast month block (None -> all None)."""
    if not block:
        return None
    exp = block["expenses"]
    debt = sum(float(i["amount"]) for i in exp["fixed_items"]
               if (i.get("category") or "").strip() in DEBT_CATEGORIES)
    return {"income": block["income"]["total"],
            "fixed": float(exp["fixed_total"]) - debt,
            "variable": exp["discretionary_total"],
            "debt_savings": debt}


def _expected_from_budget(doc):
    if not doc:
        return None
    import digest
    out = dict.fromkeys(("income", "fixed", "variable", "debt_savings"), 0.0)
    for e in doc.get("envelopes") or []:
        amt = abs(float(e.get("originalAmount") or 0))
        d = e.get("details") or {}
        if e.get("type") == "fixed":
            if digest.is_internal_transfer({"description": str(d.get("businessName") or d.get("expense") or "")}):
                continue
            if d.get("isIncome"):
                out["income"] += amt
            elif (d.get("expense") or "").strip() in DEBT_CATEGORIES:
                out["debt_savings"] += amt
            else:
                out["fixed"] += amt
        elif e.get("type") == "trackingCategory" and float(e.get("originalAmount") or 0) > 0:
            out["variable"] += amt
    return out


def _groups(actual, expected):
    return [{"key": k, "label": label,
             "expected": _r(expected[k]) if expected else None,
             "actual": _r(actual.get(k, 0.0)) if actual is not None else None}
            for k, label in GROUPS]


def _totals(g):
    income = g.get("income", 0.0)
    expense = sum(g.get(k, 0.0) for k in ("fixed", "variable", "debt_savings"))
    return round(income, 2), round(expense, 2), round(income - expense, 2)


def _categories(cats):
    ranked = sorted(cats.items(), key=lambda kv: -kv[1][0])[:TOP_CATEGORIES]
    return [{"name": k, "amount": round(v[0], 2), "count": v[1]} for k, v in ranked if v[0] > 0]


def _projected_end(actual, expected):
    if not expected:
        return None
    inc = max(actual.get("income", 0.0), expected["income"])
    exp = max(actual.get("variable", 0.0), expected["variable"])
    for k in ("fixed", "debt_savings"):
        a = actual.get(k, 0.0)
        exp += a + max(expected[k] - a, 0.0)
    return {"income": round(inc, 2), "expense": round(exp, 2), "net": round(inc - exp, 2)}


def build_months_view(transactions, forecast, budget_history_docs, as_of: date, past=6, future=3):
    current = as_of.strftime("%Y-%m")
    actuals = _actuals(transactions, as_of)
    docs = {d.get("budgetDate"): d for d in budget_history_docs or []}
    fmonths = {m["forecast_month"]: m for m in (forecast or {}).get("months", [])}
    cur_block = (forecast or {}).get("current_month")
    if cur_block and cur_block.get("forecast_month") == current:
        fmonths[current] = cur_block

    months = []
    for i in range(-past, future + 1):
        key = _shift(current, i)
        if i <= 0:
            a = {k: v for k, v in actuals[key]["groups"].items()} if key in actuals else {}
            cats = actuals[key]["cats"] if key in actuals else {}
            expected = (_expected_from_forecast(fmonths.get(key)) if i == 0
                        else _expected_from_budget(docs.get(key)))
            income, expense, net = _totals(a)
            months.append({
                "month": key, "kind": "current" if i == 0 else "actual",
                "income": income, "expense": expense, "net": net,
                "projected_end": _projected_end(a, expected) if i == 0 else None,
                "groups": _groups(a, expected),
                "categories": _categories(cats),
            })
        else:
            block = fmonths.get(key)
            expected = _expected_from_forecast(block)
            income = _r(block["income"]["total"]) if block else None
            expense = _r(block["expenses"]["total"]) if block else None
            months.append({
                "month": key, "kind": "projected",
                "income": income, "expense": expense,
                "net": round(income - expense, 2) if block else None,
                "projected_end": None,
                "groups": _groups(None, expected),
                "categories": [],
            })
    return {"current": current, "months": months}
