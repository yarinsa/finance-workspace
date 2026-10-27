#!/usr/bin/env python3
"""Edit transactions: write the human layer (transaction_overrides).

A transaction is addressed by its ledger key, DATE and AMOUNT (the sign is
ignored, as in the dedup key):

    .venv/bin/python db/edit.py show     2026-01-15 123.45
    .venv/bin/python db/edit.py category 2026-01-15 123.45 "אלקטרוניקה"
    .venv/bin/python db/edit.py note     2026-01-15 123.45 "gift"
    .venv/bin/python db/edit.py horizon  2026-01-15 123.45 future    # current | near | future (who it's for)
    .venv/bin/python db/edit.py kind     2026-01-15 123.45 fixed     # fixed (קבוע) | variable (משתנה)
    .venv/bin/python db/edit.py exclude  2026-01-15 123.45        # hide from the ledger and every total
    .venv/bin/python db/edit.py include  2026-01-15 123.45        # undo exclude
    .venv/bin/python db/edit.py goal     2026-01-15 123.45 phone-2026  # money that went to a goal (db/goal_store.py)
    .venv/bin/python db/edit.py clear    2026-01-15 123.45 [category|note|horizon|kind|goal]   # drop one field, or the whole override
    .venv/bin/python db/edit.py tag      2026-01-15 123.45 "טיול" ["עבודה" ...]   # add tags
    .venv/bin/python db/edit.py untag    2026-01-15 123.45 "טיול" [...]          # remove tags
    .venv/bin/python db/edit.py list [--orphaned]
    .venv/bin/python db/edit.py tags                                         # every tag, with its count
    .venv/bin/python db/edit.py rule "מטרו מוטור שווק (1981)בעמ" category "רכב"   # every transaction of a merchant
    .venv/bin/python db/edit.py rule "MERCHANT" kind fixed|variable|none          # (none clears that field)
    .venv/bin/python db/edit.py rules                                        # every merchant rule
    .venv/bin/python db/edit.py categories                                   # the taxonomy: group -> category (kind)

The merchant is the ledger row's `merchant` key (`show` prints it). Precedence:
override > merchant rule > the digest's default (finance/categories.py).

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
FIELDS = ("category", "note", "horizon", "kind")
ACTOR = "cli"   # the audit actor for edits made from this script


def find(conn, k):
    return conn.execute(
        "SELECT txn_date, amount, description, category, scraped_category, note, overridden, horizon, "
        "category_group, kind, kind_source, record->>'merchant' "
        "FROM transactions WHERE (txn_date, abs_amount) = (%s, %s)", k).fetchone()


def override(conn, k):
    return conn.execute(
        "SELECT c.name, o.note, o.excluded, h.key, g.slug, o.kind FROM transaction_overrides o "
        "LEFT JOIN categories c ON c.id = o.category_id "
        "LEFT JOIN horizons h ON h.id = o.horizon_id LEFT JOIN goals g ON g.id = o.goal_id "
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
        d, amt, desc, cat, scraped, note, _, horizon, group, kind, kind_source, merchant = row
        print(f"{d}  {amt:>10}  {desc}")
        print(f"  merchant: {merchant}")
        print(f"  category: {group + ' / ' if group else ''}{cat}" + (f"   (default: {scraped})" if cat != scraped else ""))
        if kind:
            print(f"  kind:     {kind} ({kind_source})")
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
        print(f"  override: category={o[0]!r} note={o[1]!r} excluded={o[2]} horizon={o[3]!r} goal={o[4]!r} "
              f"kind={o[5]!r}")
    rule = overrides.get_merchant_rule(conn, row[11]) if row and row[11] else None
    if rule:
        print(f"  merchant rule: category={rule['category']!r} kind={rule['kind']!r}")


def list_overrides(conn, orphaned_only):
    view = "orphaned_overrides" if orphaned_only else "transaction_overrides"
    rows = conn.execute(
        f"SELECT o.txn_date, o.abs_amount, s.description, c.name, o.note, o.excluded, h.key "
        f"FROM {view} o LEFT JOIN scraped_transactions s USING (txn_date, abs_amount) "
        f"LEFT JOIN categories c ON c.id = o.category_id LEFT JOIN horizons h ON h.id = o.horizon_id "
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
        if cmd == "categories":
            for g in overrides.category_tree(conn):
                print(g["name"] or "(no group)")
                for c in g["categories"]:
                    print(f"  {c['name']}" + (f"  [{c['kind']}{', usage' if c['usage_based'] else ''}]" if c["kind"] else ""))
            return None
        if cmd == "rules":
            for r in overrides.merchant_rules(conn):
                print(f"{r['transactions']:>5}  {r['merchant']}  category={r['category']} kind={r['kind']}")
            return None
        if cmd == "rule":
            if len(rest) != 3 or rest[1] not in overrides.RULE_FIELDS:
                raise SystemExit('usage: edit.py rule MERCHANT category|kind VALUE ("none" clears)')
            merchant, field, value = rest
            if field == "kind" and value not in (*overrides.KINDS, "none"):
                raise SystemExit(f"kind is one of {overrides.KINDS} or none")
            rule = overrides.set_merchant_rule(conn, merchant, {field: None if value == "none" else value}, ACTOR)
            conn.commit()
            print(f"{merchant}: {rule}")
            if not no_rebuild:
                rebuild()
            return None
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
        if cmd in ("category", "note", "horizon", "kind", "goal", "exclude", "include", "tag") and not exists(conn, k):
            raise SystemExit(f"no transaction on {k[0]} for {k[1]} (try `show`, or check the date)")
        if cmd in FIELDS:
            if len(args) != 1:
                raise SystemExit(f"usage: edit.py {cmd} DATE AMOUNT VALUE")
            if cmd == "horizon" and args[0] not in overrides.HORIZONS:
                raise SystemExit(f"horizon is one of {overrides.HORIZONS}")
            if cmd == "kind" and args[0] not in overrides.KINDS:
                raise SystemExit(f"kind is one of {overrides.KINDS}")
            set_field(conn, k, cmd, args[0])
        elif cmd == "goal":
            if len(args) != 1:
                raise SystemExit("usage: edit.py goal DATE AMOUNT GOAL_SLUG")
            g = conn.execute("SELECT id FROM goals WHERE slug = %s", (args[0],)).fetchone()
            if not g:
                raise SystemExit(f"no goal {args[0]!r} (see `db/goal_store.py list`)")
            set_field(conn, k, "goal_id", g[0])
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
            if args and args[0] == "goal":
                args = ["goal_id"]
            elif args and args[0] not in FIELDS:
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
