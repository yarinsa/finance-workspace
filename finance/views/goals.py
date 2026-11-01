"""Goals digest, pure: the יעדים (Goals) screen's model (docs/plangram-prd/04-goals.md).

`build(store, snapshot, cashflow, today, generated_at)` turns the goals store, the
snapshot and the cashflow block into the goals.json dict: the four general cards
(goal compliance, emergency fund, retirement, inheritance) and one card per personal
goal. A target of 0 in the store means "not set": the matching card is emitted with
status "needs_input" and value None, so the UI degrades honestly rather than showing
a fake 100%/0%. `status` only says whether the card has data; whether the target is
met is the separate `meets_target` flag.

No file, database or clock access: `today` and `generated_at` come from the caller
(data/goals.py).
"""
from datetime import date, datetime

DAYS_PER_MONTH = 365.25 / 12


def pct(part, whole):
    """Coverage % clamped to 0–100, or None if the denominator is unset (0).
    A negative part (overdrawn checking) reads 0%, never a negative coverage."""
    if not whole:
        return None
    return round(max(0.0, min(1.0, part / whole)) * 100, 1)


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except ValueError:
        return None

def emergency_fund_card(buffer, target):
    """Emergency-fund coverage = liquid buffer ÷ target, clamped to 0–100%.

    shortfall is clamped to [0, target]: an overdrawn buffer reads as "nothing
    saved yet" (shortfall = target), not target + overdraft. The overdraft is a
    debt already carried by the snapshot / cashflow overdraft view; folding it in
    here would count it twice and make the fund look bigger than its target.
    `status` = data present; `meets_target` = the fund is actually full.
    """
    coverage = pct(buffer, target)
    return {
        "key": "emergency_fund_coverage",
        "name": "אחוז עמידה בקרן חירום",
        "units": "%",
        "value": coverage,
        "status": "ok" if target else "needs_input",
        "shortfall": round(min(target, max(0.0, target - buffer)), 2) if target else None,
        "meets_target": (buffer >= target) if target else None,
        "target": target or None,
        "description": "כיסוי קרן החירום — היתרה הנזילה חלקי יעד קרן החירום.",
    }


def retirement_card(net_worth_at_retirement, target, target_derived=False):
    """Retirement coverage = projected net worth at retirement ÷ target.

    A target derived from the projection itself is 100% by definition, so in
    that case (or with no target / no projection) the card is "needs_input"
    with value None rather than a fake 100%.
    """
    usable = bool(target) and not target_derived and net_worth_at_retirement is not None
    return {
        "key": "retirement_coverage",
        "name": "אחוז עמידה ביעד פרישה",
        "units": "%",
        "value": pct(net_worth_at_retirement, target) if usable else None,
        "status": "ok" if usable else "needs_input",
        "meets_target": (net_worth_at_retirement >= target) if usable else None,
        "target": target if usable else None,
        "target_derived": target_derived,
        "description": "כיסוי יעד הפרישה — השווי הנקי הצפוי בפרישה חלקי יעד הפרישה.",
    }


def inheritance_card(estate, target):
    # Plangram shows the *modelled* estate (₪), and compares it to the target as
    # a verdict. We emit the modelled figure as the value and the comparison flag.
    return {
        "key": "inheritance_amount",
        "name": "סכום להורשה",
        "units": "₪",
        "value": round(estate, 2) if estate is not None else None,
        "status": "ok" if estate is not None else "needs_input",
        "meets_target": (estate >= target) if (estate is not None and target) else None,
        "target": target or None,
        "description": "העיזבון הצפוי בסוף החיים — מה שהתוכנית מותירה.",
    }


def per_goal(goal, buffer, monthly_surplus=None, *, today):
    """Deterministic per-goal render (PRD §4b). Probability is modelled in
    Plangram; for v1 we ship a transparent on-track verdict instead.

    - accrued = liquid buffer clamped to [0, amount] (the full buffer is the pool;
      splitting it between goals is out of scope). An overdrawn buffer accrues 0,
      so progress_pct is always 0–100.
    - remaining = amount − accrued; required_monthly = remaining ÷ months left to
      end_date (months = days ÷ 365.25/12).
    - on_track rule:
        True  if the goal is already fully accrued (regardless of date);
        False if end_date has passed (or is today) and it is not funded;
        None  if the monthly surplus is unknown (we can't tell — never "on track");
        else  required_monthly ≤ monthly_surplus, i.e. a *positive* surplus covers
              the saving needed. A zero/negative surplus funds nothing.
      Runway alone never makes a goal on track. `build` passes each goal only the
      surplus left after earlier-dated goals, so one surplus isn't spent twice.
    """
    amount = goal.get("amount") or 0
    accrued = max(0.0, min(buffer, amount)) if amount else 0.0
    remaining = round(amount - accrued, 2) if amount else 0.0
    progress = round((accrued / amount) * 100, 1) if amount else None
    end = parse_date(goal.get("end_date"))
    days_left = (end - today).days if end else None

    required_monthly = None
    if amount and remaining <= 0:
        required_monthly = 0.0
    elif amount and days_left is not None and days_left > 0:
        required_monthly = round(remaining / (days_left / DAYS_PER_MONTH), 2)

    on_track = None
    if amount:
        if remaining <= 0:
            on_track = True
        elif days_left is not None and days_left <= 0:
            on_track = False
        elif required_monthly is not None and monthly_surplus is not None:
            on_track = monthly_surplus > 0 and required_monthly <= monthly_surplus
    return {
        "id": goal.get("id"),
        "description": goal.get("description", ""),
        "amount": amount,
        "end_date": goal.get("end_date"),
        "days_left": days_left,
        "progress_pct": progress,
        "remaining": remaining,
        "required_monthly": required_monthly,
        "on_track": on_track,
        "goal_id": goal.get("goal_id"),     # the `goals` table id when read from the database
        "horizon": goal.get("horizon"),     # current | near | future, from the `horizons` table
    }


def monthly_surplus_from(cashflow):
    """The month's forecast net (pace.expected.net), falling back to the
    month-to-date net (today.net). None if neither is present."""
    expected = ((cashflow.get("pace") or {}).get("expected") or {}).get("net")
    if expected is not None:
        return expected
    return (cashflow.get("today") or {}).get("net")


def build(store, snapshot, cashflow, today, generated_at):
    """Pure goals digest: store + snapshot + cashflow -> the goals.json dict. `today` is a
    date; `generated_at` the ISO timestamp the caller stamps on it."""
    buffer = snapshot.get("totals", {}).get("bank_balances_sum", 0) or 0
    ef_target = store.get("emergency_fund_target", 0) or 0
    inh_target = store.get("inheritance_target", 0) or 0

    proj = cashflow.get("projection", {}) or {}
    nw_retirement = proj.get("net_worth_at_retirement")
    focals = proj.get("focal_points") or []
    estate = focals[-1].get("net_val") if focals else None

    # Retirement target: PRD §8 open question. Until the user enters one, the
    # card is "needs_input" (falling back to the projection would read 100% by
    # definition).
    retirement_target = store.get("retirement_target", 0) or 0
    retirement_target_derived = not retirement_target

    # Fund goals earliest end_date first out of one shared monthly surplus.
    surplus = monthly_surplus_from(cashflow)
    available = None if surplus is None else max(0.0, surplus)
    raw = store.get("goals", [])
    order = sorted(range(len(raw)), key=lambda i: parse_date(raw[i].get("end_date")) or date.max)
    rendered = {}
    for i in order:
        g = per_goal(raw[i], buffer, available, today=today)
        if g["on_track"] and available is not None and g["required_monthly"]:
            available = max(0.0, available - g["required_monthly"])
        rendered[i] = g
    goals = [rendered[i] for i in range(len(raw))]

    funded = sum(1 for g in goals if g["on_track"] is True)
    overall = round((funded / len(goals)) * 100, 1) if goals else None
    missing_piece = round(sum(g["remaining"] or 0 for g in goals), 2)

    general = [
        {
            "key": "goal_compliance",
            "name": "אחוז עמידה ביעדים",
            "units": "%",
            "value": overall,
            "status": "ok" if goals else "needs_input",
            "description": "עמידה כללית ביעדים — שיעור היעדים שהתוכנית מממנת.",
        },
        emergency_fund_card(buffer, ef_target),
        retirement_card(nw_retirement, retirement_target, retirement_target_derived),
        inheritance_card(estate, inh_target),
    ]

    return {
        "generated_at": generated_at,
        "currency": "ILS",
        "note": "Goals digest — see docs/plangram-prd/04-goals.md. Targets from data/goals/goals.json (user-owned).",
        "general": general,
        "personal_goals": goals,
        "missing_piece": missing_piece,
        "liquid_buffer": round(buffer, 2),
        "monthly_surplus": round(surplus, 2) if surplus is not None else None,
    }
