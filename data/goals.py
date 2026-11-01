#!/usr/bin/env python3
"""
Goals digest — the יעדים (Goals) screen's model (docs/plangram-prd/04-goals.md).

Goals are *user intent*, not scraped bank data, so this reads a user-owned store
(data/goals/goals.json) and combines it with what the pipeline already produces:

  data/digested/snapshot.json   -> liquid buffer (bank_balances_sum) for the
                                   emergency-fund card
  data/digested/cashflow.json   -> projection.net_worth_at_retirement and the
                                   end-of-life estate (last focal point) for the
                                   retirement / inheritance cards, and the
                                   forecast month net (pace.expected.net, else
                                   today.net) as the monthly surplus that funds
                                   personal goals

and writes:

  data/digested/goals.json   the four general cards + per-goal cards
  data/digested/goals.md     human-readable summary

This mirrors the PRD's phased build:
  - Phase 1 (data we have today): אחוז עמידה בקרן חירום + חוסר בקרן חירום, from
    bank_balances_sum vs emergency_fund_target.
  - Phase 2 (reuse projection):   אחוז עמידה ביעד פרישה + סכום להורשה, from the
    projection's retirement / end-of-life net worth vs the user targets.
  - Phase 3 (per-goal):           each personal goal's progress (accrued ÷ amount,
    approximated by liquid buffer share) + a deterministic on-track verdict
    (see per_goal), and overall אחוז עמידה ביעדים / חתיכה חסרה (gap to fund all
    goals).

A target of 0 in the store means "not set" — the matching card is emitted with
status "needs_input" and value None, so the UI degrades honestly rather than
showing a fake 100%/0%. `status` only says whether the card has data; whether
the target is actually met is the separate `meets_target` flag.

Read-only over scraped data; only writes its own digest. Safe to re-run.
Run: python3 data/goals.py
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path
from finance.paths import data_root

CODE = Path(__file__).resolve().parent
ROOT = data_root()
STORE = ROOT / "goals" / "goals.json"
SNAPSHOT = ROOT / "digested" / "snapshot.json"
CASHFLOW = ROOT / "digested" / "cashflow.json"
OUT_JSON = ROOT / "digested" / "goals.json"
OUT_MD = ROOT / "digested" / "goals.md"


DAYS_PER_MONTH = 365.25 / 12


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


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


def load_store():
    return load(STORE)


def save_store(store):
    """Atomic write with a single .bak — so a bad edit never corrupts the store."""
    if STORE.exists():
        STORE.with_suffix(".json.bak").write_text(
            STORE.read_text(encoding="utf-8"), encoding="utf-8"
        )
    tmp = STORE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(STORE)


def slug_id(description):
    """Short random-suffixed id derived from the description + this year, so a
    rename can't collide with an existing goal's id."""
    import re
    import secrets

    base = re.sub(r"[^\w]+", "-", description.strip(), flags=re.UNICODE).strip("-").lower()
    base = base or "goal"
    return f"{base}-{date.today().year}-{secrets.token_hex(2)}"


def add_goal(store, description, amount, end_date, *, interval=None,
             repetitions=1, rise=0.0, start_date=None, goal_id=None):
    if not description or not description.strip():
        raise ValueError("description is required")
    if not amount or amount <= 0:
        raise ValueError("amount must be > 0")
    if parse_date(end_date) is None:
        raise ValueError(f"end_date must be YYYY-MM-DD, got {end_date!r}")
    ids = {g.get("id") for g in store["goals"]}
    goal_id = goal_id or slug_id(description)
    if goal_id in ids:
        raise ValueError(f"goal id {goal_id!r} already exists")
    goal = {
        "id": goal_id,
        "description": description.strip(),
        "amount": amount,
        "start_date": start_date or date.today().isoformat(),
        "end_date": end_date,
        "interval": interval,
        "repetitions": repetitions,
        "rise": rise,
        "from_asset_id": None,
    }
    store["goals"].append(goal)
    return goal


def edit_goal(store, goal_id, **fields):
    for g in store["goals"]:
        if g.get("id") == goal_id:
            if "amount" in fields and fields["amount"] is not None and fields["amount"] <= 0:
                raise ValueError("amount must be > 0")
            if "end_date" in fields and fields["end_date"] and parse_date(fields["end_date"]) is None:
                raise ValueError(f"end_date must be YYYY-MM-DD, got {fields['end_date']!r}")
            g.update({k: v for k, v in fields.items() if v is not None})
            return g
    raise ValueError(f"no goal with id {goal_id!r}")


def remove_goal(store, goal_id):
    before = len(store["goals"])
    store["goals"] = [g for g in store["goals"] if g.get("id") != goal_id]
    if len(store["goals"]) == before:
        raise ValueError(f"no goal with id {goal_id!r}")


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


def per_goal(goal, buffer, monthly_surplus=None):
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
    days_left = (end - date.today()).days if end else None

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


def build(store, snapshot, cashflow):
    """Pure goals digest: store + snapshot + cashflow -> the goals.json dict."""
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
        g = per_goal(raw[i], buffer, available)
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
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "currency": "ILS",
        "note": "Goals digest — see docs/plangram-prd/04-goals.md. Targets from data/goals/goals.json (user-owned).",
        "general": general,
        "personal_goals": goals,
        "missing_piece": missing_piece,
        "liquid_buffer": round(buffer, 2),
        "monthly_surplus": round(surplus, 2) if surplus is not None else None,
    }


def database_url():
    """DATABASE_URL from the environment, else from .env (as data/digest.py reads it)."""
    import digest
    return digest.database_url()


def _from_db(read):
    """`read(goal_store, conn)` against the database (db/goal_store.py); None when no
    database is configured or it is unreachable (callers then fall back to their defaults)."""
    url = database_url()
    if not url:
        return None
    db = str(CODE.parent / "db")
    sys.path.insert(0, db)
    try:
        import goal_store
        from ledger import connect
        with connect(url) as conn:
            return read(goal_store, conn)
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the digest
        print(f"goals: database unavailable ({e})", file=sys.stderr)
        return None
    finally:
        sys.path.remove(db)


def goals_from_db():
    """The personal goals from the `goals` table, shaped like the JSON store's list, or None."""
    rows = _from_db(lambda m, conn: m.all_goals(conn))
    return None if rows is None else [{**g, "id": g["slug"], "goal_id": g["id"]} for g in rows]


def horizons_from_db():
    """The `horizons` table (key, name, target_pct, ...) in order, or None."""
    return _from_db(lambda m, conn: m.horizons(conn))


def targets_from_db():
    """The targets that have a default-goal row ({key: amount}, 0 = unset), or None without a database."""
    return _from_db(lambda m, conn: m.stored_targets(conn))


def main():
    from finance.tenancy import use_cli_tenant
    use_cli_tenant()
    store = load(STORE)
    targets = targets_from_db()
    if targets is not None:   # a stored row wins over the JSON store; keys with no row keep the JSON value
        store.update(targets)
    from_db = goals_from_db()
    if from_db is not None:
        store["goals"] = from_db
    out = build(store, load(SNAPSHOT), load(CASHFLOW))
    general, goals = out["general"], out["personal_goals"]
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# יעדים — Goals digest", ""]
    for c in general:
        v = c["value"]
        if v is None:
            shown = "— (חסר קלט)" if c["status"] == "needs_input" else "—"
        elif c["units"] == "%":
            shown = f"{v}%"
        else:
            shown = f"₪{v:,.0f}"
        lines.append(f"- **{c['name']}**: {shown}")
    if goals:
        lines += ["", "## יעדים אישיים"]
        for g in goals:
            prog = f"{g['progress_pct']}%" if g["progress_pct"] is not None else "—"
            track = {True: "בכיוון", False: "לא בכיוון"}.get(g["on_track"], "—")
            lines.append(f"- {g['description']} — ₪{g['amount']:,.0f} ({prog}, {track})")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")


def cli(argv=None):
    import argparse

    p = argparse.ArgumentParser(description="Goals store editor + digest. No flags = digest only.")
    p.add_argument("--set-emergency", type=float, metavar="AMOUNT", help="set emergency_fund_target (₪)")
    p.add_argument("--set-inheritance", type=float, metavar="AMOUNT", help="set inheritance_target (₪)")
    p.add_argument("--set-retirement", type=float, metavar="AMOUNT", help="set retirement_target (₪; 0 = not set)")
    p.add_argument("--add", metavar="DESCRIPTION", help="add a personal goal (needs --amount --by)")
    p.add_argument("--amount", type=float, help="goal target amount (₪)")
    p.add_argument("--by", metavar="YYYY-MM-DD", help="goal end date")
    p.add_argument("--interval", help="recurring period, e.g. yearly")
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--rise", type=float, default=0.0, help="per-occurrence growth")
    p.add_argument("--edit", metavar="ID", help="edit goal by id (with --amount/--by/…)")
    p.add_argument("--remove", metavar="ID", help="delete goal by id")
    p.add_argument("--list", action="store_true", help="print targets + goals and exit")
    args = p.parse_args(argv)

    try:
        return _apply(args)
    except ValueError as e:
        p.error(str(e))  # prints usage + message to stderr, exits 2 (no partial write)


def _apply(args):
    mutated = False
    if args.list:
        store = load_store()
        print(f"emergency_fund_target: {store.get('emergency_fund_target', 0):,}")
        print(f"inheritance_target:    {store.get('inheritance_target', 0):,}")
        print(f"retirement_target:     {store.get('retirement_target', 0):,}")
        for g in store["goals"]:
            print(f"  [{g['id']}] {g['description']} — ₪{g['amount']:,.0f} by {g.get('end_date')}")
        return

    store = load_store()
    if args.set_emergency is not None:
        store["emergency_fund_target"] = args.set_emergency; mutated = True
    if args.set_inheritance is not None:
        store["inheritance_target"] = args.set_inheritance; mutated = True
    if args.set_retirement is not None:
        store["retirement_target"] = args.set_retirement; mutated = True
    if args.add:
        g = add_goal(store, args.add, args.amount, args.by, interval=args.interval,
                     repetitions=args.repetitions, rise=args.rise)
        print(f"added [{g['id']}] {g['description']}"); mutated = True
    if args.edit:
        g = edit_goal(store, args.edit, amount=args.amount, end_date=args.by,
                      interval=args.interval)
        print(f"edited [{g['id']}]"); mutated = True
    if args.remove:
        remove_goal(store, args.remove); print(f"removed {args.remove}"); mutated = True

    if mutated:
        save_store(store)
    main()  # always re-digest so goals.json reflects the store


if __name__ == "__main__":
    cli()
