#!/usr/bin/env python3
"""Net-worth projection engine — Cashflow Phase 2.

Simulates net worth forward, month by month, from today to end-of-life, and
returns the series + focal points + retirement metrics that drive the עו"ש
(net-worth-over-time) chart and the forward-looking KPI cards.

Design decisions (see docs/plangram-prd/01-cashflow.md §6):

- **Real terms.** Everything is after-inflation, so rates are *real* and the
  curve reads in today's shekels. No separate inflation line.
- **Surplus comes from loan payoff, not the ledger.** Phase 1 found the ledger's
  monthly net is polluted by inter-account transfers. Instead we model the *real*
  amortization of every snapshot loan: each month we pay scheduled installments
  (shrinking liabilities); when a loan finishes, its freed monthly payment becomes
  recurring investable surplus compounding at ``REAL_RETURN``. This is fully
  backed by real loan data — balance, rate, payment, payments_remaining.
- **Assumptions live in CONFIG** — one editable block, labeled as *ours* (not
  Plangram's proprietary numbers).

Reads ``data/digested/snapshot.json``. Pure/read-only, stdlib only, idempotent.
Importable: ``projection.build(snapshot) -> dict``.
"""

import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(HERE, "digested", "snapshot.json")

# --- Assumptions (OURS — editable) -----------------------------------------
CONFIG = {
    "current_age": 35,        # not in source data; edit to your real age
    "retirement_age": 67,     # matches Plangram scenario / IL standard
    "end_age": 90,            # horizon end
    "real_return": 0.04,      # 4% real annual return on invested surplus
    "_note": "Real (after-inflation) terms. current_age is a placeholder — "
             "not present in scraped data; set it to get an accurate horizon.",
}


def _months_between_ages(a, b):
    return int(round((b - a) * 12))


def amortize_loans(loans):
    """Per-loan monthly schedule. Returns a list of active loans with a
    ``schedule`` function and a ``payoff_month`` (months from now), plus the
    monthly payment that frees up at payoff.

    Each loan is treated as a fixed-payment amortizing balance at its real-ish
    nominal rate. Loans without a rate/payment (e.g. the Leumi aggregate) are
    amortized straight-line over a default term so they still pay down.
    """
    out = []
    for ln in loans:
        bal = float(ln.get("balance") or 0)
        if bal <= 0:
            continue
        pay = float(ln.get("monthly_payment") or 0)
        rem = int(ln.get("payments_remaining") or 0)
        rate_m = float(ln.get("rate_pct") or 0) / 100.0 / 12.0

        if pay <= 0 or rem <= 0:
            # No schedule on this loan (e.g. Leumi aggregate): straight-line it
            # over a default 60-month term so the liability still retires.
            rem = rem or 60
            pay = bal / rem
            rate_m = 0.0

        out.append({
            "name": ln.get("name") or ln.get("loan_id"),
            "category": ln.get("category"),
            "balance": bal,
            "payment": pay,
            "rate_m": rate_m,
            "payments_remaining": rem,
        })
    return out


def simulate(snapshot, cfg=CONFIG):
    """March month-by-month from today to end_age. Returns timeline + focal points."""
    totals = snapshot.get("totals", {})
    # Starting position: tracked net worth (assets - liabilities), real shekels.
    # Liabilities are carried inside the loan schedules so we don't double-count;
    # start "assets side" from the non-loan net (bank balances + card debt).
    bank = float(totals.get("bank_balances_sum") or 0)
    card_debt = float(totals.get("credit_card_debt") or 0)
    liquid = bank - card_debt        # liquid assets net of card debt (can be neg)

    loans = amortize_loans(snapshot.get("loans", []))
    total_loan_balance = sum(l["balance"] for l in loans)

    invested = 0.0                   # surplus invested so far (real)
    freed_monthly = 0.0              # recurring freed cashflow from finished loans
    r_m = cfg["real_return"] / 12.0

    months = _months_between_ages(cfg["current_age"], cfg["end_age"])
    start = date.today()

    timeline = []
    focal = []
    payoff_events = []

    def net_worth():
        remaining = sum(l["balance"] for l in loans)
        return liquid + invested - remaining

    # focal: today
    focal.append({
        "month": 0, "age": cfg["current_age"], "date": start.isoformat(),
        "name": "היום", "net_val": round(net_worth()),
        "loan_val": round(total_loan_balance), "asset_val": round(liquid + invested),
    })

    retire_month = _months_between_ages(cfg["current_age"], cfg["retirement_age"])

    for m in range(1, months + 1):
        # 1) service loans
        for l in loans:
            if l["balance"] <= 0:
                continue
            interest = l["balance"] * l["rate_m"]
            principal = l["payment"] - interest
            l["balance"] = max(0.0, l["balance"] - principal)
            if l["balance"] <= 0 and not l.get("_freed"):
                l["_freed"] = True
                freed_monthly += l["payment"]
                yr = (start.year * 12 + start.month - 1 + m)
                payoff_events.append({
                    "month": m, "age": round(cfg["current_age"] + m / 12, 1),
                    "name": f"סיום הלוואה: {l['name']}", "freed_monthly": round(l["payment"]),
                })

        # 2) invest the freed cashflow + grow the portfolio
        invested = invested * (1 + r_m) + freed_monthly

        # 3) record yearly points (keeps timeline light) + retirement month
        if m % 12 == 0 or m == retire_month:
            d = date(start.year + (start.month - 1 + m) // 12,
                     (start.month - 1 + m) % 12 + 1, 1)
            timeline.append({
                "date": d.isoformat(),
                "age": round(cfg["current_age"] + m / 12, 1),
                "net_val": round(net_worth()),
                "loan_val": round(sum(l["balance"] for l in loans)),
                "invested": round(invested),
            })

    # focal: each payoff + retirement + end
    focal.extend(payoff_events)
    nw_at_retirement = next((p["net_val"] for p in timeline
                             if abs(p["age"] - cfg["retirement_age"]) < 0.5), None)
    if nw_at_retirement is not None:
        focal.append({"month": retire_month, "age": cfg["retirement_age"],
                      "name": "פרישה", "net_val": nw_at_retirement})
    if timeline:
        focal.append({"age": cfg["end_age"], "name": "סוף תחזית",
                      "net_val": timeline[-1]["net_val"]})

    return {
        "timeline": timeline,
        "focal_points": focal,
        "net_worth_today": round(net_worth() if not timeline else focal[0]["net_val"]),
        "net_worth_at_retirement": nw_at_retirement,
        "total_loan_balance_today": round(total_loan_balance),
        "loans_modeled": len(loans),
    }


def metrics(sim, cfg=CONFIG):
    """Forward-looking KPI cards derived from the simulation."""
    tl = sim["timeline"]
    out = []

    nw_ret = sim.get("net_worth_at_retirement")
    out.append({
        "key": "net_worth_at_retirement", "name": "שווי נקי בפרישה",
        "value": nw_ret, "units": "₪",
        "rank": "good" if (nw_ret or 0) > 0 else "bad", "higher_is_better": True,
        "description": f"שווי נקי צפוי בגיל {cfg['retirement_age']} (במונחים ריאליים)",
    })

    # growth metric: near-term net-worth slope (% per year over next 5y)
    growth = None
    if len(tl) >= 6:
        base = tl[0]["net_val"]
        future = tl[5]["net_val"]
        if base:
            growth = round((future - base) / abs(base) / 5 * 100, 1)
    out.append({
        "key": "growth", "name": "מדד הצמיחה", "value": growth, "units": "%",
        "rank": "good" if (growth or 0) > 0 else "warning" if growth is not None else None,
        "higher_is_better": True,
        "description": "קצב הגידול הריאלי הממוצע בשווי הנקי בחמש השנים הקרובות",
    })

    # transparent 0-100 balance score (OURS, not Plangram's proprietary one)
    score = _balance_score(sim, cfg)
    out.append({
        "key": "balance_score", "name": "מדד איזון", "value": score, "units": "",
        "rank": "good" if score >= 70 else "warning" if score >= 40 else "bad",
        "higher_is_better": True,
        "description": "מדד איזון פיננסי (0–100) — נוסחה שקופה משלנו, לא של פלנגרם",
        "ours": True,
    })
    return out


def _balance_score(sim, cfg):
    """Our own transparent 0-100 score: rewards a positive & growing net worth
    that ends retirement above zero. Not Plangram's number."""
    nw_today = sim.get("net_worth_today") or 0
    nw_ret = sim.get("net_worth_at_retirement") or 0
    s = 50
    if nw_ret > 0:
        s += 30
    if nw_ret > abs(nw_today):  # net worth recovers past today's debt load
        s += 10
    if sim["timeline"] and sim["timeline"][-1]["loan_val"] == 0:
        s += 10                 # all debt retired within horizon
    if nw_today < 0:
        s -= 10
    return max(0, min(100, s))


def to_chart(sim):
    """netval_plot envelope for the dashboard."""
    tl = sim["timeline"]
    return {
        "graph_type": "area", "graph_title": "עו\"ש — שווי נקי לאורך זמן",
        "xlabel": "שנה", "ylabel": "₪",
        "x_axis": [p["date"][:4] for p in tl],
        "datasets": [
            {"name": "שווי נקי", "ds": [p["net_val"] for p in tl], "color": "#6366f1"},
            {"name": "יתרת הלוואות", "ds": [p["loan_val"] for p in tl], "color": "#f97316"},
            {"name": "תיק מושקע", "ds": [p["invested"] for p in tl], "color": "#22c55e"},
        ],
        "unique_name": "netval_plot",
    }


def build(snapshot=None, cfg=CONFIG):
    if snapshot is None:
        with open(SNAPSHOT, encoding="utf-8") as f:
            snapshot = json.load(f)
    sim = simulate(snapshot, cfg)
    return {
        "config": cfg,
        "net_worth_today": sim["net_worth_today"],
        "net_worth_at_retirement": sim["net_worth_at_retirement"],
        "total_loan_balance_today": sim["total_loan_balance_today"],
        "loans_modeled": sim["loans_modeled"],
        "focal_points": sim["focal_points"],
        "chart": to_chart(sim),
        "metrics": metrics(sim, cfg),
    }


if __name__ == "__main__":
    p = build()
    print(f"net worth today: {p['net_worth_today']:,} ₪")
    print(f"net worth at retirement (age {p['config']['retirement_age']}): "
          f"{p['net_worth_at_retirement']:,} ₪")
    print(f"loans modeled: {p['loans_modeled']}, "
          f"total balance today: {p['total_loan_balance_today']:,} ₪")
    print("focal points:")
    for fp in p["focal_points"]:
        nv = fp.get("net_val")
        nv_s = f"{nv:,} ₪" if nv is not None else "—"
        print(f"  age {fp.get('age')}: {fp['name']} — net {nv_s}"
              + (f" (frees {fp['freed_monthly']:,}/mo)" if fp.get("freed_monthly") else ""))
