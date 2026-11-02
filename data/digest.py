#!/usr/bin/env python3
"""Combine the normalized layer -> data/digested/snapshot.{json,md}

Pipeline:  raw/  --(each source's normalize.py)-->  normalized/  --(this)-->  digested/

By default this runs every <source>/normalize.py first, then combines all
<source>/normalized/*.json envelopes into one consolidated snapshot.
Run `python3 digest.py --no-normalize` to combine existing normalized output only.
With DATABASE_URL set, the ledger goes through Postgres (db/) to apply your edits;
`--no-db` skips that.
"""
import json, datetime, glob, os, re, subprocess, sys

import stores
from pathlib import Path

import freshness
from finance.views import horizons
from finance import categories, manifest, offsets
from finance.origins import RISEUP_ORIGIN
from finance.transfers import (  # noqa: F401  (re-exported: validate.py and the tests read them here)
    DEPOSIT_WITHDRAWAL_PHRASES, OWN_ACCOUNT_HINTS, OWN_NAMES, OWN_TRANSFER_DESCRIPTIONS,
    ROUND_TRIP_LOAN_IDS, _LOAN_ID_RE, is_internal_transfer,
)
from finance.paths import data_root
from finance.views.snapshot import (  # noqa: F401  (re-exported for the tests)
    build_snapshot, loan_profile, next_card_charges, spending_summary,
)

CODE = Path(__file__).resolve().parent          # .../Finance/data (the scripts)
ROOT = data_root()                              # this tenant's files
OUT = ROOT / "digested"
OUT.mkdir(parents=True, exist_ok=True)


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def database_url(env_file=CODE.parent / ".env"):
    """DATABASE_URL from the environment, else from .env (read literally)."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def apply_overrides(ledger, position=None, dumps=None, run=None):
    """Round-trip the ledger through the transactions database (db/ledger.py).

    It is stored as `scraped_transactions` and comes back as the `transactions`
    view: your category/note edits applied, excluded rows removed. The reconciled
    `position`, the source `dumps` and this `run` are stored in the same transaction.
    A no-op when DATABASE_URL is unset or with --no-db. When the database is configured
    but unreachable we stop rather than publish numbers that silently drop the edits.
    """
    if "--no-db" in sys.argv or not database_url():
        return ledger
    payload = {"ledger": ledger, "position": position, "dumps": dumps, "run": run}
    res = subprocess.run([sys.executable, str(CODE.parent / "db" / "ledger.py"), "sync"],
                         input=json.dumps(payload, ensure_ascii=False),
                         capture_output=True, text=True)
    sys.stderr.write(res.stderr)
    if res.returncode != 0:
        raise SystemExit("db sync failed (is `docker compose up -d` running?); "
                         "rerun with --no-db to digest without the database")
    return json.loads(res.stdout)


def category_merges():
    """{category: the category it was merged into} from the database (`db/ledger.py merges`);
    {} without one. budgets.py folds a merged category's plan into its target with it."""
    if "--no-db" in sys.argv or not database_url():
        return {}
    res = subprocess.run([sys.executable, str(CODE.parent / "db" / "ledger.py"), "merges"],
                         capture_output=True, text=True)
    return json.loads(res.stdout) if res.returncode == 0 and res.stdout.strip() else {}


def run_normalizers():
    for script in sorted(CODE.glob("*/normalize.py")):
        print(f"normalizing {script.parent.name}…")
        subprocess.run([sys.executable, str(script)], check=True)


def load_entities():
    """Group all normalized records by entity across every source."""
    entities = {}
    for fp in sorted(ROOT.glob("*/normalized/*.json")):
        env = json.load(open(fp, encoding="utf-8"))
        for rec in env["records"]:
            rec.setdefault("_source", env["source"])   # stamp origin for dedup/reporting
        entities.setdefault(env["entity"], []).extend(env["records"])
    return entities


# --- Credit-card bill settlement -------------------------------------------
# A card BILL payment (bank account → card issuer) is not spend: the underlying
# purchases are already in the ledger as individual card transactions, so
# counting the monthly settlement too double-counts. These rows are bank-side
# debits whose description is the issuer's clearing name + "חיוב". Tagged
# `card_bill_payment: true` and excluded from cashflow/summary.
#
# Scoped to bank origins so we never catch an actual purchase. Phrase list is the
# clearing names seen in the dumps (CAL/Diners, Amex, Isracard/Mastercard, Max).
CARD_BILL_PHRASES = [
    "דיינרס", "אמריקן אקס", "מאסטרקרד", "מסטרקארד", "ל.מאסטרקרד",
    "ויזה כ.א.ל", "כרטיסי אשראי", "מקס איט", "max", "ישראכרט", "כאל",
]
BANK_ORIGINS = {"discount", "discount-business", "leumi"}


def _mentions_card_issuer(desc, low):
    if any(p in desc for p in CARD_BILL_PHRASES if p.isascii() is False):
        return True
    # ascii issuer names (max) — match on the lowercased description
    if any(p in low for p in CARD_BILL_PHRASES if p.isascii()):
        return True
    return False


def is_card_bill_payment(rec):
    """True if this is a bank-side move against a card-issuer settlement — the
    monthly debit, or a reversal/re-charge credit of one — not real spend or income.

    Keyed on the counterparty being one of our known card issuers on a BANK
    origin, not on the "חיוב" suffix alone: a settlement reversal (issuer credits
    the bank back, e.g. a charge reversed then re-billed days later) carries a
    POSITIVE amount and often lacks "חיוב" in its description, but it is still
    our own money moving between our bank and our card issuer — never counted as
    income. Ordinary debit settlements (negative, "...,חיוב") keep matching as
    before. Scoped to BANK_ORIGINS so a genuine merchant refund on the CARD side
    (origin cal/amex, a specific merchant name) is never caught here.
    """
    if rec.get("origin") not in BANK_ORIGINS:
        return False
    desc = (rec.get("description") or "")
    low = desc.lower()
    amount = float(rec.get("amount") or 0)
    if amount < 0:                                 # ordinary debit settlement
        return "חיוב" in desc and _mentions_card_issuer(desc, low)
    # positive amount: only a settlement reversal/credit from a known issuer
    # counterparty qualifies — never match on amount alone.
    return _mentions_card_issuer(desc, low)


# --- Savings / investment deposits -----------------------------------------
# Money routed into the household's OWN savings or investment vehicles (a liquid
# deposit, an asset-management standing order). It leaves the checking account
# (so it's a real outflow) but it is *saved*, not *spent* — Plangram models it as
# its own bucket. Tagged `savings: true`; cashflow routes it to a "savings"
# bucket and keeps it out of the spending breakdown.
# NOTE: "ניהול נכסי" (property management) is deliberately NOT here — the
# "עיין ניהול נכסי" standing order is RENT, a real living expense, not savings.
# "ניהול השק" (investment management, e.g. Excellence) stays.
SAVINGS_PHRASES = [
    "פיקדון", "פקדון", "ניהול השק", "קרן השתלמות",
    "אקסלנס", "הראל", "גמל", "השקעות",
]


def is_savings_deposit(rec):
    """True if this is a deposit into our own savings/investment vehicle."""
    if float(rec.get("amount") or 0) >= 0:        # a deposit is an outflow
        return False
    desc = rec.get("description") or ""
    # "הפקדה ל..." / standing order to an investment manager
    if "הפקדה" in desc and ("פיקדון" in desc or "פקדון" in desc):
        return True
    if any(p in desc for p in SAVINGS_PHRASES) and ("הפקדה" in desc or 'הו"ק' in desc or "העברה ל" in desc):
        return True
    return False


def _canon_tx(r):
    """Map a per-source transaction record to one common shape.

    Sources differ: cal/amex carry card_last4/card_name; riseup carries
    origin/category/is_income; discount/leumi carry account_id. We keep a common
    core plus whatever identifying extras the source provided.
    """
    src = r.get("_source")
    origin = src
    if src == "riseup":
        origin = RISEUP_ORIGIN.get(r.get("origin"), r.get("origin") or "riseup")
    t = {
        "date": r.get("date", ""),
        "amount": round(r.get("amount", 0), 2),
        "description": r.get("description", ""),
        "category": r.get("category"),
        "origin": origin,                         # institution the money actually moved at
        "is_income": r.get("is_income", r.get("amount", 0) > 0),
        "sources": [src],                         # which of our scrapers saw it
        "card_last4": r.get("card_last4"),
        "account_id": r.get("account_id"),
        "budget_type": r.get("budget_type"),
        "budget_category": r.get("budget_category"),
        "_riseup": src == "riseup",
    }
    if is_internal_transfer(t):
        t["internal_transfer"] = True            # excluded from cashflow/summary
    elif is_card_bill_payment(t):
        t["card_bill_payment"] = True            # excluded — purchases already in ledger
    elif is_savings_deposit(t):
        t["savings"] = True                      # real outflow, but saved not spent
    return t


def _is_cross_bank_pair(legs):
    """True if the merged legs include a debit at one of our banks and a credit at
    a DIFFERENT one — the two sides of a move between our own accounts.

    Same-institution opposite signs (a card charge + refund) don't count, and a
    lone leg never does, so a forward whose source side we never scraped stays
    income.
    """
    out = {o for o, sign in legs if sign < 0 and o in BANK_ORIGINS}
    inc = {o for o, sign in legs if sign > 0 and o in BANK_ORIGINS}
    return any(a != b for a in out for b in inc)


def consolidate_transactions(txns):
    """Merge every source's transactions into one deduped ledger.

    Two records are the same purchase when (date, abs(amount)) match. RiseUp is the
    higher-priority copy (it carries the spending category), so on a match the RiseUp
    record's fields win and the direct source is recorded in `sources`.
    Output is sorted newest-first and ready to query.
    """
    buckets = {}                                  # (date, abs_amount) -> merged record
    for raw in txns:
        t = _canon_tx(raw)
        t["_legs"] = {(t["origin"], (t["amount"] > 0) - (t["amount"] < 0))}
        key = (t["date"], round(abs(t["amount"]), 2))
        cur = buckets.get(key)
        if cur is None:
            buckets[key] = t
            continue
        # merge: union the sources, let RiseUp win the descriptive fields
        merged_sources = sorted(set(cur["sources"]) | set(t["sources"]))
        winner = t if (t["_riseup"] and not cur["_riseup"]) else cur
        other = cur if winner is t else t
        winner["sources"] = merged_sources
        winner["_legs"] = cur["_legs"] | t["_legs"]
        # backfill anything the winner is missing from the other copy
        for f in ("category", "card_last4", "account_id", "origin", "budget_type", "budget_category"):
            if not winner.get(f) and other.get(f):
                winner[f] = other[f]
        # Re-evaluate the exclusion flags on the MERGED row rather than OR-ing the
        # legs. Two unrelated charges can collide on (date, abs amount) — a real
        # purchase vs a self-transfer of the same value on the same day — and we
        # must not let one leg's flag taint the other. Trust only the description
        # that actually survives onto the merged row.
        for flag, test in (("internal_transfer", is_internal_transfer),
                           ("card_bill_payment", is_card_bill_payment),
                           ("savings", is_savings_deposit)):
            if test(winner) or (flag == "internal_transfer"
                                and _is_cross_bank_pair(winner["_legs"])):
                winner[flag] = True
            else:
                winner.pop(flag, None)
        if not winner.get("description"):
            winner["description"] = other.get("description", "")
        buckets[key] = winner

    out = []
    for t in buckets.values():
        t.pop("_riseup", None)
        t.pop("_legs", None)
        t["horizon"] = horizons.default_horizon(t)   # a manual override replaces it in the view
        out.append({k: v for k, v in t.items() if v is not None})
    out = merge_shifted_copies(out)
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


def merge_shifted_copies(ledger):
    """Merge a RiseUp-only row into the direct source's copy dated one day apart.

    RiseUp occasionally dates a card charge a day after the card does (APPLE.COM/BILL
    ₪59.50: Max 2026-10-14, RiseUp 2026-10-15), so the (date, amount) key misses it.
    Only an unmatched RiseUp row and an unmatched direct row with the same origin,
    sign, amount and merchant, exactly one day apart, merge — two same-price charges
    at different institutions or merchants stay apart. Each row merges at most once.
    The direct source's date is kept (the institution's own record); RiseUp's
    descriptive fields win as in `consolidate_transactions`."""
    from finance.merchants import merchant_name
    direct = {}
    for t in ledger:
        if "riseup" not in t["sources"]:
            k = (t.get("origin"), round(t["amount"], 2), merchant_name(t.get("description")))
            direct.setdefault(k, []).append(t)
    used, dropped = set(), set()
    for r in ledger:
        if r["sources"] != ["riseup"]:
            continue
        k = (r.get("origin"), round(r["amount"], 2), merchant_name(r.get("description")))
        rd = datetime.date.fromisoformat(r["date"][:10])
        for o in direct.get(k, []):
            if id(o) in used or abs((datetime.date.fromisoformat(o["date"][:10]) - rd).days) != 1:
                continue
            for f, v in r.items():
                if f not in ("date", "sources") and v is not None and (f != "description" or v):
                    o[f] = v
            o["sources"] = sorted(set(o["sources"]) | {"riseup"})
            o["horizon"] = horizons.default_horizon(o)
            used.add(id(o))
            dropped.add(id(r))
            break
    return [t for t in ledger if id(t) not in dropped]


# --- PayBox round trips -------------------------------------------------------
# Loading PayBox from a card and cashing it out to a bank account is our own money
# going around: the card leg (`PAYBOX`, −₪1,000 on amex) and the bank leg
# (`מפייבוקס ש…`, +₪1,000 at Discount/Leumi a day or two later) are both
# internal transfers, not a ₪1,000 expense plus ₪1,000 income.
ROUND_TRIP_LEGS = [("PAYBOX", "פייבוקס")]       # (card-side merchant, bank-side credit)
ROUND_TRIP_DAYS = 3


def mark_round_trips(ledger):
    """Flag each card-side load and its same-amount bank-side cash-out (0..3 days
    later, nearest first) as `internal_transfer` + `round_trip`. A load with no
    cash-out (paying someone through PayBox) stays spend. Mutates `ledger`."""
    def day(t):
        return datetime.date.fromisoformat(t["date"][:10])
    used = set()
    for card_pat, bank_pat in ROUND_TRIP_LEGS:
        loads = sorted((t for t in ledger if t["amount"] < 0 and t.get("origin") in offsets.CARD_ORIGINS
                        and card_pat in (t.get("description") or "").upper()), key=lambda t: t["date"])
        outs = [t for t in ledger if t["amount"] > 0 and t.get("origin") in BANK_ORIGINS
                and bank_pat in (t.get("description") or "")]
        for load in loads:
            match = [o for o in outs if id(o) not in used and abs(o["amount"] + load["amount"]) < 0.005
                     and 0 <= (day(o) - day(load)).days <= ROUND_TRIP_DAYS]
            if not match:
                continue
            o = min(match, key=lambda o: (day(o) - day(load)).days)
            used.add(id(o))
            for t in (load, o):
                t["internal_transfer"] = True
                t["round_trip"] = True
    return ledger


def load_offset_rules():
    """The household's קיזוז rules from `offset_rules` (db/input_store.py): a payer whose transfers
    pay back a known expense, e.g. [{"payer": "<roommate>", "against": ["<landlord>"]}]
    (finance/offsets.py). [] without a database."""
    return stores.from_db("input_store", lambda m, conn: m.offset_rules(conn), "offset rules") or []


def load_assets():
    """The hand-typed assets from Postgres (db/asset_store.py), or None with no database.

    Best-effort: an unreachable database prints to stderr and the digest carries on."""
    url = database_url()
    if not url or "--no-db" in sys.argv:
        return None
    db = str(CODE.parent / "db")
    sys.path.insert(0, db)
    try:
        import asset_store
        from ledger import connect
        with connect(url) as conn:
            return asset_store.all_assets(conn)
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the digest
        print(f"assets: database unavailable ({e})", file=sys.stderr)
        return None
    finally:
        sys.path.remove(db)


def load_holding_assignments():
    """Where the user placed savings holdings by hand (db/holding_store.py): `{holding_id: {horizon, goal_id}}`,
    or None with no database. The ids are the app's (`institution:topic_id`), so this only passes them through."""
    url = database_url()
    if not url or "--no-db" in sys.argv:
        return None
    db = str(CODE.parent / "db")
    sys.path.insert(0, db)
    try:
        import holding_store
        from ledger import connect
        with connect(url) as conn:
            return holding_store.all_assignments(conn)
    except Exception as e:   # noqa: BLE001 — a dead DB must not stop the digest
        print(f"holding assignments: database unavailable ({e})", file=sys.stderr)
        return None
    finally:
        sys.path.remove(db)


def write_markdown(s):
    def ils(x): return f"₪{x:,.0f}"
    t = s["totals"]
    mortgage = [l for l in s["loans"] if l["category"] == "mortgage"]
    consumer = [l for l in s["loans"] if l["category"] == "consumer"]
    md = [f"# Financial snapshot — {s['generated_at'][:10]}\n",
          "*Auto-generated: `python3 digest.py` (runs every source's normalize.py, then combines).*\n",
          "## Headlines\n",
          f"- **Total debt:** {ils(t['total_debt'])} "
          f"(mortgage {ils(t['mortgage_balance'])} · consumer loans {ils(t['consumer_loan_balance'])} · cards {ils(t['credit_card_debt'])}).",
          f"- **Monthly loan service:** {ils(t['monthly_loan_service'])}.",
          f"- **Bank balances:** {ils(t['bank_balances_sum'])}.",
          f"- **Transactions normalized:** {s['transactions_count']}."]
    if t.get("long_term_savings"):
        md.append(f"- **Total savings:** {ils(t['long_term_savings'])} "
                  f"(liquid {ils(t.get('liquid_savings', 0))} — deposits you can exit "
                  f"same-day · illiquid {ils(t.get('illiquid_savings', 0))} — pension / "
                  f"study funds) → net with savings {ils(t['net_position_with_savings'])}.")
    md.append("\n## Loans\n")
    md.append("| Loan | Cat. | Balance | Rate | Type | Linked | Left | ₪/mo |")
    md.append("|---|---|--:|--:|---|:--:|--:|--:|")
    for l in mortgage + consumer:
        md.append(f"| {l['name']} | {l['category']} | {ils(l['balance'])} | {l['rate_pct']}% | "
                  f"{l['rate_type']} | {'yes' if l['index_linked'] else 'no'} | "
                  f"{l['payments_remaining']} | {ils(l['monthly_payment'])} |")
    md.append("\n## Credit cards\n")
    md.append("| Card | Next charge | Owed |")
    md.append("|---|---|--:|")
    for c in s["credit_cards"]:
        md.append(f"| {c['issuer']} ····{c['last4']} | {c.get('next_charge_date') or '—'} | {ils(c['owed'])} |")
    if s.get("savings"):
        md.append("\n## Long-term savings\n")
        md.append("| Fund | Kind | Policies | Balance |")
        md.append("|---|---|--:|--:|")
        for v in s["savings"]:
            md.append(f"| {v['label']} | {v['kind']} | {v.get('policies_count') or '—'} | "
                      f"{ils(v['balance'])} |")
    md.append(f"\n> {s['note']}\n")
    (OUT / "snapshot.md").write_text("\n".join(md) + "\n")


def _manifest_fields(name):
    """The source's self-declared label, account types and capabilities (empty if it has no manifest)."""
    try:
        m = manifest.load(name)
    except OSError:
        return {}
    return {"label": m.label, "account_types": list(m.account_types), "capabilities": list(m.capabilities)}


def source_syncs(root=ROOT):
    """Per-source data freshness for the dashboard's Syncs page.

    `last_synced` is the newest raw-dump mtime — when the scraper last wrote, not
    when normalize/digest re-ran (those touch every source on each run and would
    make a week-old dump look fresh). `latest_txn_date` is the newest transaction
    the source actually carries, which can lag the scrape (e.g. a card that
    posts with delay).
    """
    out = []
    for raw in sorted(root.glob("*/raw")):
        files = [f for f in raw.rglob("*") if f.is_file() and not f.name.startswith(".")]
        newest = freshness.raw_mtime(raw)
        if newest is None:
            continue
        entities, latest_txn = {}, None
        for fp in sorted((raw.parent / "normalized").glob("*.json")):
            env = json.load(open(fp, encoding="utf-8"))
            entities[env["entity"]] = len(env["records"])
            if env["entity"] == "transactions":
                dates = [r["date"][:10] for r in env["records"] if r.get("date")]
                if dates:
                    latest_txn = max([latest_txn or "", *dates])
        out.append({
            "source": raw.parent.name,
            **_manifest_fields(raw.parent.name),
            "last_synced": datetime.datetime.fromtimestamp(newest).astimezone().isoformat(timespec="seconds"),
            "raw_files": len(files),
            "entities": entities,
            "latest_txn_date": latest_txn,
        })
    return out


def main():
    from finance.tenancy import use_cli_tenant
    use_cli_tenant()
    run = {"started_at": _now_iso(), "normalized": "--no-normalize" not in sys.argv}
    if run["normalized"]:
        run_normalizers()
    entities = load_entities()

    # one deduped, queryable transaction ledger across every source
    ledger = consolidate_transactions(entities.get("transactions", []))
    mark_round_trips(ledger)
    unmapped = categories.stamp(ledger)           # category + kind defaults; the DB layers edits on top
    if unmapped:
        print(f"categories: source labels not in finance/categories.py: {sorted(unmapped)}", file=sys.stderr)
    offsets.suggest(ledger, load_offset_rules())  # auto קיזוז, stored with the scraped row
    snapshot = build_snapshot(entities, datetime.date.today(), _now_iso(), load_assets())
    syncs = source_syncs()
    position = {k: snapshot[k] for k in ("bank_accounts", "credit_cards", "loans", "savings")}
    position["balance_days"] = entities.get("balance_days", [])   # -> account_balance_days, not snapshot.json
    ledger = apply_overrides(ledger, position, syncs, run)   # human edits from Postgres, if configured
    offsets.resolve(ledger)                       # manual links (from the DB) win over auto
    summary = spending_summary(offsets.cashflow_view(ledger))
    (OUT / "transactions.json").write_text(json.dumps(
        {"generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
         "currency": "ILS",
         "note": "Deduped across all sources on (date, abs amount); RiseUp's copy wins on "
                 "conflict and carries the spending category. `sources` lists every scraper "
                 "that saw the transaction.",
         "summary": summary,
         "category_merges": category_merges(),
         "transactions": ledger},
        ensure_ascii=False, indent=2))

    snapshot["holding_assignments"] = load_holding_assignments() or {}
    snapshot["spending"] = summary
    snapshot["syncs"] = syncs
    snapshot["source_manifests"] = {n: m.model_dump(mode="json") for n, m in manifest.load_all().items()}
    snapshot["freshness"] = freshness.status()
    (OUT / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
    write_markdown(snapshot)
    print(f"wrote {OUT / 'transactions.json'} ({len(ledger)} deduped txns)")
    print("wrote", OUT / "snapshot.json")
    print("wrote", OUT / "snapshot.md")

    # cashflow dashboard model (reads the two files just written)
    import cashflow
    cf = cashflow.build()
    print(f"wrote {OUT / 'cashflow.json'} (current month {cf['current_month']})")
    print("wrote", OUT / "cashflow.md")
    print("wrote", OUT / "cashflow.html")


if __name__ == "__main__":
    main()
