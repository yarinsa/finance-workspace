#!/usr/bin/env python3
"""Net-worth projection engine — Cashflow Phase 2.

Simulates net worth forward, month by month, from today to end-of-life, and
returns the series + focal points + retirement metrics that drive the עו"ש
(net-worth-over-time) chart and the forward-looking KPI cards.

Design decisions (see docs/plangram-prd/01-cashflow.md §6):

- **Real terms.** Everything is after-inflation, so rates are *real* and the
  curve reads in today's shekels. No separate inflation line.
- **Monthly cash comes from the forecast, not the ledger.** Phase 1 found the
  ledger's monthly net is polluted by inter-account transfers, so the baseline
  surplus is the forecast's expected month (``forecast.json`` current_month
  income − expenses, the same figure as ``cashflow.json`` pace.expected.net).
  That figure is *after* today's loan installments, so each month the cash pool
  moves by ``surplus + today's loan service − installments actually due``:
  a loan finishing frees its payment, a step-up (re-amortized track) costs more.
- **Real loan amortization.** Every snapshot loan is amortized from its balance,
  rate, payment and payments_remaining, shrinking liabilities each month.
- **Liquid pool can go negative.** A deficit is borrowed (overdraft/credit) at
  ``borrow_rate``; a positive balance is invested at ``real_return``.
- **Long-term savings are assets.** Pension + study funds (snapshot
  ``totals.illiquid_savings``) grow at ``real_return`` and are illiquid until
  retirement, when they merge into the pool that funds the drawdown.
- **Retirement drawdown.** From ``retirement_age`` the salary-based surplus stops
  and the pool pays ``retirement_drawdown`` a month (default: today's forecast
  expenses minus today's loan service — loans are paid off by then).
- **Assumptions live in CONFIG** — one editable block, labeled as *ours* (not
  Plangram's proprietary numbers). ``resolve_config`` fills the data-derived
  ones; known gaps are listed in ``LIMITATIONS`` and shipped in the output.

Reads ``data/digested/snapshot.json`` and ``data/digested/forecast.json``.
Pure/read-only, stdlib only, idempotent.
Importable: ``projection.build(snapshot) -> dict``.
"""

import json
import os
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(HERE, "digested", "snapshot.json")
FORECAST = os.path.join(HERE, "digested", "forecast.json")

# --- Assumptions (OURS — editable) -----------------------------------------
# Birth date is the household's real one (not in scraped data); current_age is
# derived from it (accounting for whether this year's birthday has passed) so the
# horizon stays correct as years pass.
BIRTH_DATE = date(1997, 11, 23)


def _age_on(d):
    """Exact age in whole years on date `d`, accounting for the birthday."""
    return d.year - BIRTH_DATE.year - (
        (d.month, d.day) < (BIRTH_DATE.month, BIRTH_DATE.day))


CONFIG = {
    "current_age": _age_on(date.today()),  # derived from BIRTH_DATE
    "retirement_age": 67,     # matches Plangram scenario / IL standard
    "end_age": 90,            # horizon end
    "real_return": 0.04,      # 4% real annual return on invested cash + savings
    # Real annual cost of a negative liquid balance (overdraft / consumer
    # credit). Israeli overdraft runs ~prime+3-5% nominal; ~8% after inflation.
    "borrow_rate": 0.08,
    # Expected monthly net (income − expenses, after today's loan installments)
    # while working. None -> forecast.json current_month; 0 if no forecast.
    "monthly_surplus": None,
    # Monthly living cost paid from savings after retirement, in today's
    # shekels, net of any pension/state income (none modelled). None ->
    # forecast expenses − today's loan service; else detected salary.
    "retirement_drawdown": None,
    # Ongoing pension/study-fund deposits until retirement. They come out of
    # gross salary (not the forecast net), and we have no reliable figure, so
    # 0 = conservative: savings only grow by return.
    "savings_contribution": 0,
    "_note": f"Real (after-inflation) terms. current_age derived from "
             f"BIRTH_DATE={BIRTH_DATE.isoformat()}.",
}

# Known gaps, shipped with every projection so the chart isn't over-read.
LIMITATIONS = [
    "The property behind the mortgage is not modelled (no value is scraped): "
    "the mortgage counts as a liability with no matching asset, so net worth "
    "is understated by the property's equity.",
    "No pension/state-pension income is modelled after retirement; the "
    "drawdown is the full living cost.",
    "Ongoing pension/study-fund contributions are not modelled unless "
    "savings_contribution is set.",
    "The working-years surplus is today's forecast month held flat in real "
    "terms (no raises, no lifestyle changes, rent assumed to continue).",
]


def _forecast_month(forecast):
    """Income/expense totals of the forecast's current month, or None."""
    cur = (forecast or {}).get("current_month") or {}
    try:
        return float(cur["income"]["total"]), float(cur["expenses"]["total"])
    except (KeyError, TypeError, ValueError):
        return None


def resolve_config(cfg, snapshot, forecast=None):
    """Return a copy of ``cfg`` with the data-derived assumptions filled in.

    - ``monthly_surplus``: forecast income − expenses (the forecast already pays
      today's loan installments), else 0.
    - ``retirement_drawdown``: forecast expenses − today's loan service (loans
      are retired by then), else the detected monthly salary (a household that
      spends what it earns), else 0.
    Explicit (non-None) values in ``cfg`` always win; ``*_source`` records where
    each figure came from.
    """
    out = dict(cfg)
    totals = snapshot.get("totals", {}) or {}
    fm = _forecast_month(forecast)
    service = float(totals.get("monthly_loan_service") or 0) or sum(
        float(ln.get("monthly_payment") or 0) for ln in snapshot.get("loans", []))

    if out.get("monthly_surplus") is None:
        if fm:
            out["monthly_surplus"] = round(fm[0] - fm[1], 2)
            out["monthly_surplus_source"] = "forecast.json current_month income − expenses"
        else:
            out["monthly_surplus"] = 0.0
            out["monthly_surplus_source"] = "no forecast — assumed 0"
    else:
        out.setdefault("monthly_surplus_source", "config")

    if out.get("retirement_drawdown") is None:
        if fm:
            out["retirement_drawdown"] = round(max(0.0, fm[1] - service), 2)
            out["retirement_drawdown_source"] = "forecast expenses − today's loan service"
        else:
            out["retirement_drawdown"] = float(totals.get("detected_monthly_salary") or 0)
            out["retirement_drawdown_source"] = "detected monthly salary (no forecast)"
    else:
        out.setdefault("retirement_drawdown_source", "config")

    if out.get("mortgage_schedule") is None:
        import forecast as _fc          # same dir; shares the schedule loader
        out["mortgage_schedule"] = _fc.load_mortgage_schedule()
    out.setdefault("start_month", date.today().strftime("%Y-%m"))
    out.setdefault("borrow_rate", out["real_return"])
    out.setdefault("savings_contribution", 0)
    out["limitations"] = list(LIMITATIONS)
    return out


def _months_between_ages(a, b):
    return int(round((b - a) * 12))


def annuity_payment(balance, rate_m, n):
    """Fixed (Schpitzer) monthly payment that retires `balance` in `n` months."""
    if rate_m <= 0:
        return balance / n
    return balance * rate_m / (1 - (1 + rate_m) ** -n)


def amortize_loans(loans):
    """Per-loan monthly schedule: balance, payment, monthly rate and the number
    of payments left. The payment frees up as surplus once the loan retires.

    Each loan is treated as a fixed-payment amortizing balance at its real-ish
    nominal rate. The scraped ``monthly_payment`` is today's installment, which
    may be temporarily reduced (the Discount mortgage tracks are ≈interest-only
    right now); if it can't retire the balance within ``payments_remaining`` we
    use the annuity payment that does, so every loan ends on its final_date.
    ``base_payment`` keeps today's installment: the forecast surplus is measured
    after it, so the simulation charges only the difference.
    Loans without a rate/payment (e.g. the Leumi aggregate) are amortized
    straight-line over a default term so they still pay down.
    """
    out = []
    for ln in loans:
        bal = float(ln.get("balance") or 0)
        if bal <= 0:
            continue
        pay = float(ln.get("monthly_payment") or 0)
        rem = int(ln.get("payments_remaining") or 0)
        rate_m = float(ln.get("rate_pct") or 0) / 100.0 / 12.0

        # Today's installment as the forecast sees it (what the bank charges now).
        base_pay = pay
        if pay <= 0 or rem <= 0:
            # No schedule on this loan (e.g. Leumi aggregate): straight-line it
            # over a default 60-month term so the liability still retires.
            rem = rem or 60
            pay = bal / rem
            rate_m = 0.0
            base_pay = base_pay if base_pay > 0 else pay
        else:
            pay = max(pay, annuity_payment(bal, rate_m, rem))

        out.append({
            "name": ln.get("name") or ln.get("loan_id"),
            "category": ln.get("category"),
            "balance": bal,
            "payment": pay,
            "base_payment": base_pay,
            "rate_m": rate_m,
            "payments_remaining": rem,
        })
    return out


def _fc_schedule_adjusted(*a):
    import forecast as _fc
    return _fc.schedule_adjusted(*a)


def simulate(snapshot, cfg=CONFIG, forecast=None):
    """March month-by-month from today to end_age. Returns timeline + focal points.

    State: ``liquid`` (bank − card debt + liquid deposits + invested surplus; may
    go negative = borrowed), ``savings`` (illiquid pension/study funds) and the
    amortizing loans. Net worth = liquid + savings − remaining loan balances.

    Each month, while working::

        liquid += monthly_surplus + today's loan service − installments due

    so a finished loan frees its payment and a re-amortized (stepped-up) track
    costs its extra. From retirement the surplus stops, savings merge into
    ``liquid`` and ``retirement_drawdown`` is paid out instead. ``liquid`` earns
    ``real_return`` when positive and costs ``borrow_rate`` when negative.
    """
    cfg = resolve_config(cfg, snapshot, forecast)
    totals = snapshot.get("totals", {})
    # Liabilities are carried inside the loan schedules so we don't double-count;
    # the asset side starts from bank balances net of card debt, plus savings.
    bank = float(totals.get("bank_balances_sum") or 0)
    card_debt = float(totals.get("credit_card_debt") or 0)
    lt_total = float(totals.get("long_term_savings") or 0)
    liquid_dep = float(totals.get("liquid_savings") or 0)
    illiquid = totals.get("illiquid_savings")
    savings = float(illiquid) if illiquid is not None else max(0.0, lt_total - liquid_dep)
    liquid = bank - card_debt + liquid_dep

    loans = amortize_loans(snapshot.get("loans", []))
    total_loan_balance = sum(l["balance"] for l in loans)
    base_service = sum(l["base_payment"] for l in loans)
    # Mortgage cash follows the bank's schedule (Jan-2027 step-up etc.) when we
    # have it; the per-track amortization still drives the balances.
    schedule = cfg.get("mortgage_schedule") or []
    base_mortgage = sum(l["base_payment"] for l in loans if l["category"] == "mortgage")
    sy, sm = (int(x) for x in cfg["start_month"].split("-"))
    mortgage_cash = []

    surplus = float(cfg["monthly_surplus"] or 0)
    drawdown = float(cfg["retirement_drawdown"] or 0)
    contribution = float(cfg.get("savings_contribution") or 0)
    r_m = cfg["real_return"] / 12.0
    b_m = cfg["borrow_rate"] / 12.0

    months = _months_between_ages(cfg["current_age"], cfg["end_age"])
    retire_month = _months_between_ages(cfg["current_age"], cfg["retirement_age"])
    start = date.today()

    timeline = []
    focal = []
    payoff_events = []
    runout = None
    min_liquid_5y = liquid

    def net_worth():
        return liquid + savings - sum(l["balance"] for l in loans)

    def month_date(m):
        return date(start.year + (start.month - 1 + m) // 12,
                    (start.month - 1 + m) % 12 + 1, 1)

    # focal: today
    nw_today = net_worth()
    focal.append({
        "month": 0, "age": cfg["current_age"], "date": start.isoformat(),
        "name": "היום", "net_val": round(nw_today),
        "loan_val": round(total_loan_balance), "asset_val": round(liquid + savings),
    })

    for m in range(1, months + 1):
        retired = m > retire_month

        # 1) service loans
        paid = 0.0
        paid_mortgage = 0.0
        for l in loans:
            if l["balance"] <= 0:
                continue
            interest = l["balance"] * l["rate_m"]
            principal = l["payment"] - interest
            paid += l["payment"]
            if l["category"] == "mortgage":
                paid_mortgage += l["payment"]
            l["balance"] = max(0.0, l["balance"] - principal)
            l["payments_remaining"] -= 1
            if l["payments_remaining"] <= 0:
                l["balance"] = 0.0   # last installment clears float residue
            if l["balance"] <= 0 and not l.get("_freed"):
                l["_freed"] = True
                payoff_events.append({
                    "month": m, "age": round(cfg["current_age"] + m / 12, 1),
                    "name": f"סיום הלוואה: {l['name']}", "freed_monthly": round(l["payment"]),
                })

        if schedule and base_mortgage:
            ym = f"{sy + (sm - 1 + m) // 12}-{(sm - 1 + m) % 12 + 1:02d}"
            sched = _fc_schedule_adjusted(base_mortgage, cfg["start_month"], ym, schedule)
            paid += sched - paid_mortgage
            paid_mortgage = sched
        if m <= 60:
            mortgage_cash.append({"month": m, "mortgage_paid": round(paid_mortgage, 2)})

        # 2) grow / charge the pools, then add this month's cashflow
        liquid *= (1 + r_m) if liquid >= 0 else (1 + b_m)
        savings *= (1 + r_m)
        if retired:
            liquid -= drawdown + paid
        else:
            liquid += surplus + base_service - paid
            savings += contribution
        if m == retire_month:
            liquid += savings        # pension/study funds become accessible
            savings = 0.0

        if m <= 60:
            min_liquid_5y = min(min_liquid_5y, liquid)
        if retired and runout is None and liquid < 0:
            runout = {"month": m, "age": round(cfg["current_age"] + m / 12, 1),
                      "date": month_date(m).isoformat(), "name": "החסכונות אוזלים",
                      "net_val": round(net_worth())}

        # 3) record yearly points (keeps timeline light) + retirement month
        if m % 12 == 0 or m == retire_month:
            timeline.append({
                "month": m,
                "date": month_date(m).isoformat(),
                "age": round(cfg["current_age"] + m / 12, 1),
                "net_val": round(net_worth()),
                "loan_val": round(sum(l["balance"] for l in loans)),
                "invested": round(liquid),
                "savings": round(savings),
            })

    # focal: each payoff + retirement + run-out + end (end stays last: goals.py
    # reads focal_points[-1] as the estate)
    focal.extend(payoff_events)
    nw_at_retirement = next((p["net_val"] for p in timeline
                             if p["month"] == retire_month), None)
    if nw_at_retirement is not None:
        focal.append({"month": retire_month, "age": cfg["retirement_age"],
                      "name": "פרישה", "net_val": nw_at_retirement})
    if runout:
        focal.append(runout)
    if timeline:
        focal.append({"month": months, "age": cfg["end_age"], "name": "סוף תחזית",
                      "net_val": timeline[-1]["net_val"]})

    return {
        "config": cfg,
        "timeline": timeline,
        "focal_points": focal,
        "net_worth_today": round(nw_today),
        "net_worth_at_retirement": nw_at_retirement,
        "estate": timeline[-1]["net_val"] if timeline else None,
        "runs_out_age": runout["age"] if runout else None,
        "min_liquid_5y": round(min_liquid_5y),
        "monthly_surplus": surplus,
        "total_loan_balance_today": round(total_loan_balance),
        "loans_modeled": len(loans),
        "mortgage_cash": mortgage_cash,
    }


def _growth(sim):
    """5-year net-worth slope in % per year, measured from *today*:

        growth = (NW[month 60] − NW[today]) / |NW[today]| / 5 × 100

    The sign is the direction of travel even when net worth is negative (the
    ``abs`` keeps a falling negative figure negative). None if the horizon is
    shorter than 5 years or today's net worth is 0.
    """
    base = sim.get("net_worth_today")
    future = next((p["net_val"] for p in sim["timeline"] if p.get("month") == 60), None)
    if future is None or not base:
        return None
    return round((future - base) / abs(base) / 5 * 100, 1)


def metrics(sim, cfg=CONFIG):
    """Forward-looking KPI cards derived from the simulation."""
    out = []

    nw_ret = sim.get("net_worth_at_retirement")
    out.append({
        "key": "net_worth_at_retirement", "name": "שווי נקי בפרישה",
        "value": nw_ret, "units": "₪",
        "rank": "good" if (nw_ret or 0) > 0 else "bad", "higher_is_better": True,
        "description": f"שווי נקי צפוי בגיל {cfg['retirement_age']} (במונחים ריאליים)",
    })

    growth = _growth(sim)
    out.append({
        "key": "growth", "name": "מדד הצמיחה", "value": growth, "units": "%",
        "rank": None if growth is None else
                "good" if growth > 0 else "bad" if growth < 0 else "warning",
        "higher_is_better": True,
        "description": "קצב השינוי הריאלי הממוצע בשווי הנקי בחמש השנים הקרובות, מהיום",
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
    """Our own transparent 0-100 score (not Plangram's number). Start at 50:

    ====================================================  =====  =====
    signal                                                 yes    no
    ====================================================  =====  =====
    net worth at retirement > 0                            +20    −20
    5-year growth (``_growth``) > 0                        +10    −15
    monthly surplus ≥ 0 (not spending more than earned)     +5    −10
    liquid pool stays ≥ 0 over the next 5 years             +5    −10
    savings last to end_age (estate ≥ 0, no run-out)       +10    −20
    net worth today ≥ 0                                      0    −10
    ====================================================  =====  =====

    Caps: if net worth is trending down or the money runs out before end_age,
    the score is capped at 55, so a declining plan can never rank "good" (≥70).
    Clamped to 0..100.
    """
    nw_today = sim.get("net_worth_today") or 0
    nw_ret = sim.get("net_worth_at_retirement") or 0
    growth = _growth(sim)
    estate = sim.get("estate")
    runs_out = sim.get("runs_out_age") is not None or (estate is not None and estate < 0)
    declining = growth is not None and growth < 0

    s = 50
    s += 20 if nw_ret > 0 else -20
    if growth is not None:
        s += 10 if growth > 0 else -15
    s += 5 if (sim.get("monthly_surplus") or 0) >= 0 else -10
    s += 5 if (sim.get("min_liquid_5y") or 0) >= 0 else -10
    s += -20 if runs_out else 10
    if nw_today < 0:
        s -= 10
    if declining or runs_out:
        s = min(s, 55)
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
            {"name": "חיסכון ארוך טווח", "ds": [p["savings"] for p in tl], "color": "#0ea5e9"},
        ],
        "unique_name": "netval_plot",
    }


def _load_forecast():
    """forecast.py output, or None — the projection still builds without it."""
    try:
        with open(FORECAST, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


_DISK = object()


def build(snapshot=None, cfg=CONFIG, forecast=_DISK):
    """Projection payload for cashflow.py. ``snapshot``/``forecast`` default to
    the digested files on disk; pass ``forecast=None`` to run without one."""
    if snapshot is None:
        with open(SNAPSHOT, encoding="utf-8") as f:
            snapshot = json.load(f)
    if forecast is _DISK:
        forecast = _load_forecast()
    sim = simulate(snapshot, cfg, forecast)
    cfg = sim["config"]
    return {
        "config": cfg,
        "net_worth_today": sim["net_worth_today"],
        "net_worth_at_retirement": sim["net_worth_at_retirement"],
        "total_loan_balance_today": sim["total_loan_balance_today"],
        "loans_modeled": sim["loans_modeled"],
        "focal_points": sim["focal_points"],
        "limitations": cfg["limitations"],
        "chart": to_chart(sim),
        "metrics": metrics(sim, cfg),
    }


if __name__ == "__main__":
    p = build()
    c = p["config"]
    print(f"net worth today: {p['net_worth_today']:,} ₪")
    print(f"monthly surplus: {c['monthly_surplus']:,} ₪ ({c['monthly_surplus_source']}); "
          f"retirement drawdown: {c['retirement_drawdown']:,} ₪/mo")
    print(f"net worth at retirement (age {c['retirement_age']}): "
          f"{p['net_worth_at_retirement']:,} ₪")
    print(f"loans modeled: {p['loans_modeled']}, "
          f"total balance today: {p['total_loan_balance_today']:,} ₪")
    print("focal points:")
    for fp in p["focal_points"]:
        nv = fp.get("net_val")
        nv_s = f"{nv:,} ₪" if nv is not None else "—"
        print(f"  age {fp.get('age')}: {fp['name']} — net {nv_s}"
              + (f" (frees {fp['freed_monthly']:,}/mo)" if fp.get("freed_monthly") else ""))
    for m in p["metrics"]:
        print(f"  {m['key']}: {m['value']} ({m['rank']})")
