"""The hand-kept inputs that were side files: offset rules, the mortgage schedule, loan freezes,
and the household's settings (the budget cycle's start day, RiseUp's `cashflowStartDay`).

Each reader returns the shape the pipeline read from the file, so the views do not change:

    offset_rules        [{"payer", "against": [...], "note"}]                       (data/offsets/rules.json)
    mortgage_schedule   [{"from": "YYYY-MM", "to": "YYYY-MM", "payment"}]           (data/mortgage_schedule.json "periods")
    loan_freezes        {loan_id: {"frozen_payment", "resume_month", "resume_payment", "note"}}
                                                                                   (data/freeze.json "tracks")
    cycle_start_day     int | None                                                  (riseup/raw/budget_current.json
                                                                                     "cashflowStartDay")

Every function takes an open, tenant-scoped psycopg connection; writes commit.

    .venv/bin/python db/input_store.py list
    .venv/bin/python db/input_store.py import [rules|schedule|freeze|settings]   # one-time copy of the side files
"""
import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

from sqlmodel import delete, select

from finance.paths import data_root
from finance.tables import LoanFreeze, MortgageSchedulePeriod, OffsetRule
from ledger import orm_session

FILES = {"rules": Path("offsets") / "rules.json", "schedule": Path("mortgage_schedule.json"),
         "freeze": Path("freeze.json"), "settings": Path("riseup") / "raw" / "budget_current.json"}


def _month(d):
    return d.strftime("%Y-%m")


def _first(month):
    return dt.date.fromisoformat(f"{month[:7]}-01")


def offset_rules(conn):
    with orm_session(conn) as s:
        return [{"payer": r.payer, "against": list(r.against), **({"note": r.note} if r.note else {})}
                for r in s.exec(select(OffsetRule).order_by(OffsetRule.id)).all()]


def set_offset_rules(conn, rules):
    """Replace the household's rules with `rules` (the file's list)."""
    with orm_session(conn) as s:
        s.exec(delete(OffsetRule))
        s.add_all(OffsetRule(payer=r["payer"], against=list(r["against"]), note=r.get("note")) for r in rules)
        s.commit()
    return len(rules)


def mortgage_schedule(conn):
    with orm_session(conn) as s:
        return [{"from": _month(p.from_month), "to": _month(p.to_month), "payment": float(p.payment)}
                for p in s.exec(select(MortgageSchedulePeriod).order_by(MortgageSchedulePeriod.from_month)).all()]


def set_mortgage_schedule(conn, periods, source=None):
    """Replace the schedule with `periods` (the file's `periods`), each band tagged with `source`."""
    with orm_session(conn) as s:
        s.exec(delete(MortgageSchedulePeriod))
        s.add_all(MortgageSchedulePeriod(from_month=_first(p["from"]), to_month=_first(p["to"]),
                                         payment=Decimal(str(p["payment"])), source=source) for p in periods)
        s.commit()
    return len(periods)


def loan_freezes(conn):
    with orm_session(conn) as s:
        return {f.loan_id: {"frozen_payment": float(f.frozen_payment), "resume_month": _month(f.resume_month),
                            "resume_payment": float(f.resume_payment), **({"note": f.note} if f.note else {})}
                for f in s.exec(select(LoanFreeze).order_by(LoanFreeze.loan_id)).all()}


def set_loan_freezes(conn, tracks):
    """Replace the recorded freezes with `tracks` ({loan_id: entry}); `{}` clears them (the freeze is over)."""
    with orm_session(conn) as s:
        s.exec(delete(LoanFreeze))
        s.add_all(LoanFreeze(loan_id=k, frozen_payment=Decimal(str(t["frozen_payment"])),
                             resume_month=_first(t["resume_month"]), resume_payment=Decimal(str(t["resume_payment"])),
                             note=t.get("note") or None) for k, t in tracks.items())
        s.commit()
    return len(tracks)


def cycle_start_day(conn):
    """The budget cycle's start day, or None while it was never set (RLS leaves this tenant's row)."""
    with conn.cursor() as cur:
        cur.execute("SELECT cycle_start_day FROM household_settings")
        row = cur.fetchone()
    return row[0] if row else None


def set_cycle_start_day(conn, day):
    """Set (or with None clear) the budget cycle's start day."""
    with conn.cursor() as cur:
        cur.execute("INSERT INTO household_settings (cycle_start_day) VALUES (%s) ON CONFLICT (tenant_id) "
                    "DO UPDATE SET cycle_start_day = EXCLUDED.cycle_start_day, updated_at = now()", (day,))
    conn.commit()
    return 1


def import_file(conn, which, root=None):
    """Copy one side file into its table (replacing what is there). Returns the row count, or None
    when the file does not exist."""
    path = Path(root or data_root()) / FILES[which]
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    if which == "rules":
        return set_offset_rules(conn, doc)
    if which == "settings":
        day = doc.get("cashflowStartDay")
        return set_cycle_start_day(conn, int(day)) if day else 0
    if which == "schedule":
        return set_mortgage_schedule(conn, doc.get("periods", []), doc.get("source"))
    return set_loan_freezes(conn, doc.get("tracks", {}))


def main(argv):
    from finance.tenancy import use_cli_tenant
    from ledger import connect
    use_cli_tenant()
    cmd, *rest = argv or ["list"]
    with connect() as conn:
        if cmd == "list":
            json.dump({"offset_rules": offset_rules(conn), "mortgage_schedule": mortgage_schedule(conn),
                       "loan_freezes": loan_freezes(conn), "cycle_start_day": cycle_start_day(conn)}, sys.stdout, ensure_ascii=False, indent=2)
            print()
        elif cmd == "import":
            for which in rest or list(FILES):
                n = import_file(conn, which)
                print(f"{which}: {'no file' if n is None else f'imported {n} row(s)'} ({FILES[which]})")
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
