#!/usr/bin/env python3
"""
Goals digest — the יעדים (Goals) screen's model (docs/plangram-prd/04-goals.md).

Goals are *user intent*, not scraped bank data, so this reads the household's goals and
targets from Postgres (`goals`, db/goal_store.py) and combines them with what the pipeline
already produces:

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

A target of 0 (or no stored target) means "not set" — the matching card is emitted with
status "needs_input" and value None, so the UI degrades honestly rather than
showing a fake 100%/0%. `status` only says whether the card has data; whether
the target is actually met is the separate `meets_target` flag.

Read-only over scraped data; only writes its own digest. Safe to re-run.
Run: python3 data/goals.py   (edit goals and targets in the app, or with db/goal_store.py)
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path
import stores
from finance.paths import data_root
from finance.views.goals import (  # noqa: F401 — re-exported: the compute lives in finance.views
    DAYS_PER_MONTH, build, emergency_fund_card, inheritance_card, monthly_surplus_from,
    parse_date, pct, per_goal, retirement_card,
)

CODE = Path(__file__).resolve().parent
ROOT = data_root()
SNAPSHOT = ROOT / "digested" / "snapshot.json"
CASHFLOW = ROOT / "digested" / "cashflow.json"
OUT_JSON = ROOT / "digested" / "goals.json"
OUT_MD = ROOT / "digested" / "goals.md"

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def database_url():
    """DATABASE_URL from the environment, else from .env (as data/digest.py reads it)."""
    import digest
    return digest.database_url()


def _from_db(read):
    """`read(goal_store, conn)` against the database (db/goal_store.py); None without one."""
    return stores.from_db("goal_store", read, "goals")


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
    store = {"goals": goals_from_db() or []}
    store.update(targets_from_db() or {})
    out = build(store, load(SNAPSHOT), load(CASHFLOW), date.today(),
                datetime.now().isoformat(timespec="seconds"))
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


if __name__ == "__main__":
    main()
