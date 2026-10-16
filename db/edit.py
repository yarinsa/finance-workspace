#!/usr/bin/env python3
"""Edit transactions: write the human layer (transaction_overrides).

A transaction is addressed by its ledger key, DATE and AMOUNT (the sign is
ignored, as in the dedup key):

    .venv/bin/python db/edit.py show     2026-01-15 123.45
    .venv/bin/python db/edit.py category 2026-01-15 123.45 "אלקטרוניקה"
    .venv/bin/python db/edit.py note     2026-01-15 123.45 "gift"
    .venv/bin/python db/edit.py horizon  2026-01-15 123.45 future    # current | near | future (who it's for)
    .venv/bin/python db/edit.py exclude  2026-01-15 123.45        # hide from the ledger and every total
    .venv/bin/python db/edit.py include  2026-01-15 123.45        # undo exclude
    .venv/bin/python db/edit.py clear    2026-01-15 123.45 [category|note|horizon]   # drop one field, or the whole override
    .venv/bin/python db/edit.py tag      2026-01-15 123.45 "טיול" ["עבודה" ...]   # add tags
    .venv/bin/python db/edit.py untag    2026-01-15 123.45 "טיול" [...]          # remove tags
    .venv/bin/python db/edit.py list [--orphaned]
    .venv/bin/python db/edit.py tags                                         # every tag, with its count

After a change it rebuilds the digested outputs (digest --no-normalize ->
validate -> forecast -> cashflow -> goals, as sync/activities.DIGEST_STEPS) so the JSON the app reads picks it up; pass
--no-rebuild to skip. Push to the dashboard afterwards with the sync-data skill.
"""
import subprocess
import sys
from pathlib import Path

import ledger
import overrides
import tags

REPO = Path(__file__).resolve().parent.parent
REBUILD = [["digest.py", "--no-normalize"], ["validate.py"], ["forecast.py"], ["cashflow.py"], ["goals.py"]]
FIELDS = ("category", "note", "horizon")
ACTOR = "cli"   # the audit actor for edits made from this script


def find(conn, k):
    return conn.execute(
        "SELECT txn_date, amount, description, category, scraped_category, note, overridden, horizon "
        "FROM transactions WHERE (txn_date, abs_amount) = (%s, %s)", k).fetchone()


def override(conn, k):
    return conn.execute(
        "SELECT c.name, o.note, o.excluded, o.horizon FROM transaction_overrides o "
        "LEFT JOIN categories c ON c.id = o.category_id "
        "WHERE (o.txn_date, o.abs_amount) = (%s, %s)", k).fetchone()


def exists(conn, k):
    return conn.execute(
        "SELECT 1 FROM scraped_transactions WHERE (txn_date, abs_amount) = (%s, %s)", k).fetchone()


def set_field(conn, k, field, value):
    """Set (or, with None, clear) one override field through the shared override code."""
    overrides.patch(conn, k, {field: value}, ACTOR)


def show(conn, k):
    row = find(conn, k)
    o = override(conn, k)
    if row:
        d, amt, desc, cat, scraped, note, _, horizon = row
        print(f"{d}  {amt:>10}  {desc}")
        print(f"  category: {cat}" + (f"   (scraped: {scraped})" if cat != scraped else ""))
        if horizon:
            print(f"  horizon:  {horizon}")
        if note:
            print(f"  note:     {note}")
    elif o and o[2]:
        print(f"{k[0]}  {k[1]}  excluded")
    else:
        print(f"{k[0]}  {k[1]}  no such transaction")
    names = tags.tags_of(conn, k)
    if names:
        print(f"  tags:     {', '.join(names)}")
    if o:
        print(f"  override: category={o[0]!r} note={o[1]!r} excluded={o[2]} horizon={o[3]!r}")


def list_overrides(conn, orphaned_only):
    view = "orphaned_overrides" if orphaned_only else "transaction_overrides"
    rows = conn.execute(
        f"SELECT o.txn_date, o.abs_amount, s.description, c.name, o.note, o.excluded, o.horizon "
        f"FROM {view} o LEFT JOIN scraped_transactions s USING (txn_date, abs_amount) "
        f"LEFT JOIN categories c ON c.id = o.category_id "
        f"ORDER BY o.txn_date DESC").fetchall()
    for d, amt, desc, cat, note, excl, horizon in rows:
        bits = [f"category={cat}" if cat else "", f"note={note}" if note else "",
                f"horizon={horizon}" if horizon else "",
                "excluded" if excl else "", "" if desc is not None else "ORPHANED"]
        print(f"{d}  {amt:>10}  {desc or '-'}  " + "  ".join(b for b in bits if b))
    print(f"{len(rows)} override(s)")


def rebuild():
    for step, *args in REBUILD:
        subprocess.run([sys.executable, str(REPO / "data" / step), *args], check=True,
                       stdout=subprocess.DEVNULL)
    print("rebuilt data/digested/ (push with the sync-data skill)")


def main(argv):
    no_rebuild = "--no-rebuild" in argv
    argv = [a for a in argv if a != "--no-rebuild"]
    if not argv:
        raise SystemExit(__doc__)
    cmd, rest = argv[0], argv[1:]
    with ledger.connect() as conn:
        if cmd == "list":
            return list_overrides(conn, "--orphaned" in rest)
        if cmd == "tags":
            for t in tags.all_tags(conn):
                print(f"{t['count']:>5}  {t['name']}" + (f"  {t['color']}" if t["color"] else ""))
            return None
        if len(rest) < 2:
            raise SystemExit(__doc__)
        k = ledger.key(rest[0], rest[1])
        args = rest[2:]
        if cmd == "show":
            return show(conn, k)
        if cmd in ("category", "note", "horizon", "exclude", "include", "tag") and not exists(conn, k):
            raise SystemExit(f"no transaction on {k[0]} for {k[1]} (try `show`, or check the date)")
        if cmd in FIELDS:
            if len(args) != 1:
                raise SystemExit(f"usage: edit.py {cmd} DATE AMOUNT VALUE")
            if cmd == "horizon" and args[0] not in overrides.HORIZONS:
                raise SystemExit(f"horizon is one of {overrides.HORIZONS}")
            set_field(conn, k, cmd, args[0])
        elif cmd == "exclude":
            set_field(conn, k, "excluded", True)
        elif cmd == "include":
            set_field(conn, k, "excluded", False)
        elif cmd in ("tag", "untag"):
            if not args:
                raise SystemExit(f"usage: edit.py {cmd} DATE AMOUNT TAG [TAG ...]")
            have = set(tags.tags_of(conn, k))
            tags.set_tags(conn, k, have | set(args) if cmd == "tag" else have - set(args), ACTOR)
        elif cmd == "clear":
            if args and args[0] not in FIELDS:
                raise SystemExit(f"clear takes one of {FIELDS}, or nothing for the whole override")
            if args:
                set_field(conn, k, args[0], None)
            else:
                overrides.reset(conn, k, ACTOR)
        else:
            raise SystemExit(__doc__)
        conn.commit()
        show(conn, k)
    if not no_rebuild:
        rebuild()


if __name__ == "__main__":
    main(sys.argv[1:])
