#!/usr/bin/env python3
"""
Goals digest — the יעדים (Goals) screen's model (docs/plangram-prd/04-goals.md).

Goals are *user intent*, not scraped bank data, so this reads a user-owned store
(data/goals/goals.json) and combines it with what the pipeline already produces:

  data/digested/snapshot.json   -> liquid buffer (bank_balances_sum) for the
                                   emergency-fund card
  data/digested/cashflow.json   -> projection.net_worth_at_retirement and the
                                   end-of-life estate (last focal point) for the
                                   retirement / inheritance cards

and writes:

  data/digested/goals.json   the four general cards + per-goal cards
  data/digested/goals.md     human-readable summary

This mirrors the PRD's phased build:
  - Phase 1 (data we have today): אחוז עמידה בקרן חירום + חוסר בקרן חירום, from
    bank_balances_sum vs emergency_fund_target.
  - Phase 2 (reuse projection):   אחוז עמידה ביעד פרישה + סכום להורשה, from the
    projection's retirement / end-of-life net worth vs the user targets.
  - Phase 3 (per-goal):           each personal goal's progress (accrued ÷ amount,
    approximated by liquid buffer share) + a deterministic on-track verdict, and
    overall אחוז עמידה ביעדים / חתיכה חסרה (gap to fund all goals).

A target of 0 in the store means "not set" — the matching card is emitted with
status "needs_input" and value None, so the UI degrades honestly rather than
showing a fake 100%/0%.

Read-only over scraped data; only writes its own digest. Safe to re-run.
Run: python3 data/goals.py
"""
import json
from datetime import date, datetime
from pathlib import Path
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _paths import data_dir

ROOT = data_dir()
STORE = ROOT / "goals" / "goals.json"
SNAPSHOT = ROOT / "digested" / "snapshot.json"
CASHFLOW = ROOT / "digested" / "cashflow.json"
OUT_JSON = ROOT / "digested" / "goals.json"
OUT_MD = ROOT / "digested" / "goals.md"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def pct(part, whole):
    """Coverage % capped at 100, or None if the denominator is unset (0)."""
    if not whole:
        return None
    return round(min(1.0, part / whole) * 100, 1)


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
    coverage = pct(buffer, target)
    return {
        "key": "emergency_fund_coverage",
        "name": "אחוז עמידה בקרן חירום",
        "units": "%",
        "value": coverage,
        "status": "ok" if target else "needs_input",
        "shortfall": round(max(0.0, target - buffer), 2) if target else None,
        "description": "כיסוי קרן החירום — היתרה הנזילה חלקי יעד קרן החירום.",
    }


def retirement_card(net_worth_at_retirement, target):
    coverage = pct(net_worth_at_retirement, target)
    return {
        "key": "retirement_coverage",
        "name": "אחוז עמידה ביעד פרישה",
        "units": "%",
        "value": coverage,
        "status": "ok" if target else "needs_input",
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


def per_goal(goal, buffer):
    """Deterministic per-goal render (PRD §4b). Probability is modelled in
    Plangram; for v1 we ship a transparent on-track verdict instead:
      - progress = accrued ÷ amount (accrued approximated as the liquid buffer,
        shared evenly is out of scope — we attribute the full buffer as the pool);
      - on_track = there is still runway to end_date and progress is plausible.
    """
    amount = goal.get("amount") or 0
    accrued = min(buffer, amount) if amount else 0
    progress = round((accrued / amount) * 100, 1) if amount else None
    end = parse_date(goal.get("end_date"))
    days_left = (end - date.today()).days if end else None
    on_track = None
    if amount:
        if progress is not None and progress >= 100:
            on_track = True
        elif days_left is not None:
            on_track = days_left > 0
    return {
        "id": goal.get("id"),
        "description": goal.get("description", ""),
        "amount": amount,
        "end_date": goal.get("end_date"),
        "days_left": days_left,
        "progress_pct": progress,
        "on_track": on_track,
    }


def main():
    store = load(STORE)
    snapshot = load(SNAPSHOT)
    cashflow = load(CASHFLOW)

    buffer = snapshot.get("totals", {}).get("bank_balances_sum", 0) or 0
    ef_target = store.get("emergency_fund_target", 0) or 0
    inh_target = store.get("inheritance_target", 0) or 0

    proj = cashflow.get("projection", {}) or {}
    nw_retirement = proj.get("net_worth_at_retirement")
    focals = proj.get("focal_points") or []
    estate = focals[-1].get("net_val") if focals else None

    # Retirement target: PRD §8 open question. Until the user enters one, we use
    # the projected retirement net worth as the target so coverage reads 100%
    # *and* flag it as derived, rather than inventing a number.
    retirement_target = store.get("retirement_target", 0) or nw_retirement or 0
    retirement_target_derived = not (store.get("retirement_target", 0) or 0)

    goals = [per_goal(g, buffer) for g in store.get("goals", [])]
    funded = sum(1 for g in goals if g["on_track"])
    overall = round((funded / len(goals)) * 100, 1) if goals else None
    missing_piece = round(
        sum(max(0.0, (g["amount"] or 0) - min(buffer, g["amount"] or 0)) for g in goals), 2
    )

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
        {
            **retirement_card(nw_retirement, retirement_target),
            "target_derived": retirement_target_derived,
        },
        inheritance_card(estate, inh_target),
    ]

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "currency": "ILS",
        "note": "Goals digest — see docs/plangram-prd/04-goals.md. Targets from data/goals/goals.json (user-owned).",
        "general": general,
        "personal_goals": goals,
        "missing_piece": missing_piece,
        "liquid_buffer": round(buffer, 2),
    }
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
            lines.append(f"- {g['description']} — ₪{g['amount']:,.0f} ({prog})")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"wrote {OUT_JSON.relative_to(ROOT.parent)} and {OUT_MD.relative_to(ROOT.parent)}")


def cli(argv=None):
    import argparse

    p = argparse.ArgumentParser(description="Goals store editor + digest. No flags = digest only.")
    p.add_argument("--set-emergency", type=float, metavar="AMOUNT", help="set emergency_fund_target (₪)")
    p.add_argument("--set-inheritance", type=float, metavar="AMOUNT", help="set inheritance_target (₪)")
    p.add_argument("--set-retirement", type=float, metavar="AMOUNT", help="set retirement_target (₪; 0 = derive)")
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
