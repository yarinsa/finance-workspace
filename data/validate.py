#!/usr/bin/env python3
"""Validate that the scraped data is complete and consistent.

Reads ONLY the direct bank and card sources (discount, discount-business,
discount-mortgage, leumi, cal, amex, plus the savings sources for dump sanity) —
never RiseUp — and cross-checks them against each other, organized by
transaction type:

  dump          every source: error stubs, missing files, record-count drops,
                stale latest transaction                     (also the `dump` CLI)
  card_bill     card statement total  <->  bank-side debit (CAL / AMEX)
  card_statement  a card cycle's transactions  <->  its statement total
  balance       checking balance continuity: opening + transactions = closing
  internal_transfer  both legs of a move between our own accounts
  loan_payment  mortgage / loan NextPayment  <->  the actual bank debit
  salary        payday income arrived in its window in each recent month

Usage:
    python3 data/validate.py                    all checks -> digested/validation.{json,md}
    python3 data/validate.py dump <source>      exit 0 = ok, 1 = reject (run before
                                                trusting a fresh scrape)
    python3 data/validate.py --data-dir D --out-dir O --as-of YYYY-MM-DD

Each check returns {id, type, status: pass|warn|fail|skip, summary, details[]};
details name the concrete transactions behind any warn/fail. Money out is
negative, as everywhere else in the pipeline. Stdlib only; read-only over the
data directory (a dump check normalizes into a throwaway temp dir).
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import digest
import runway

CODE_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = Path(os.environ.get("FINANCE_DATA_DIR") or CODE_ROOT)
DEFAULT_OUT_DIR = Path(os.environ.get("VALIDATE_OUT_DIR") or CODE_ROOT / "digested")

BANK_SOURCES = tuple(sorted(digest.BANK_ORIGINS))   # discount, discount-business, leumi
STATUSES = ("pass", "warn", "fail", "skip")

AMOUNT_TOL = 0.011            # two ₪ amounts "match" within a rounding cent
STATEMENT_TOL = 1.0           # card-cycle sums vs statement total
BILL_BDAYS = 3                # statement billing date -> bank debit, banking days
TRANSFER_BDAYS = 2            # one leg of an own-account transfer -> the other
COUNT_DROP = 0.20             # a >20% record-count drop vs the previous normalized output
MIN_REQUIRED_BYTES = 200      # a required dump smaller than this is an error stub
MAX_DETAILS = 40              # cap per check so one root cause cannot flood the report

# --- Per-source dump expectations ------------------------------------------
# `required`: raw files that must exist and hold real data. `max_txn_age_days`:
# the newest transaction should be no older than this (None = source has no
# transactions). Business checking is quiet, so it gets a much longer leash.
SOURCE_SPECS = {
    "discount": {"required": ["infoAndBalance.json", "transactions.json"], "max_txn_age_days": 7},
    "discount-business": {"required": ["infoAndBalance.json", "transactions.json"], "max_txn_age_days": 45},
    "discount-mortgage": {"required": ["mortgage_details.json"], "max_txn_age_days": None},
    "leumi": {"required": ["accounts.json", "summary.json", "transactions.json", "loans.json"],
              "max_txn_age_days": 14},
    "cal": {"required": ["account_init.json", "monthlyDebitsSummary.json"], "max_txn_age_days": 14},
    "amex": {"required": ["cardList.json"], "max_txn_age_days": 14},
    "harel": {"required": ["customer-products.json"], "max_txn_age_days": None},
    "more": {"required": ["dashboard-accounts.json"], "max_txn_age_days": None},
    "analyst": {"required": ["sum-financial-data.json"], "max_txn_age_days": None},
}

# A checking account with no transaction for this long has a hole in its history
# (the Discount dump is a rolling window; a missed scrape loses days for good).
GAP_DAYS = {"discount": 14, "leumi": 30, "discount-business": 45}

# Card issuers as named on the bank side. `max` is a card we do not scrape, so
# its bank debits are expected to have no statement here.
ISSUER_PHRASES = {
    "cal": ["דיינרס", "כאל", "כ.א.ל"],
    "amex": ["אמריקן אקס", "מאסטרקארד", "מסטרקארד", "מאסטרקרד", "ישראכרט"],
    "max": ["מקס איט", "max"],
}
TRACKED_ISSUERS = ("cal", "amex")

# digest.py recognises the Leumi->Discount salary forward only by pairing the two
# legs at consolidation time. Validating that each leg HAS its partner needs them
# named up front.
SALARY_FORWARD_PHRASES = ["משכורת_י", "בנק לאומי משכורת"]
# Where the other leg of a transfer lives when the description cannot say.
UNTRACKED_HINTS = ["הפועלים", "ביט"]          # Bank Hapoalim / Bit wallet
BANK_CODE_SOURCES = {"10": ("leumi",), "11": ("discount", "discount-business")}
_BANK_BRANCH_RE = re.compile(r"\b(1[01])-\d{3}")


# --- Small shared helpers ---------------------------------------------------

def result(id_, type_, status, summary, details=None):
    """One check outcome in the shape the report (and the app) consumes."""
    return {"id": id_, "type": type_, "status": status, "summary": summary,
            "details": details or []}


def _d(s):
    return date.fromisoformat(str(s)[:10])


def _ymd(s):
    """'20261013' -> date, tolerating '2026-10-13'."""
    s = str(s or "")
    if len(s) >= 8 and s[:8].isdigit():
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    return _d(s)


def _dmy(s):
    """'10/10/2026' -> date (CAL/AMEX statement dates are dd/mm/yyyy)."""
    dd, mm, yy = str(s).split("/")[:3]
    return date(int(yy), int(mm), int(dd))


def _money(x):
    return round(float(x or 0), 2)


def business_days_between(a, b):
    """Banking days (Sun-Thu) separating two dates, after Fri/Sat roll to Sunday."""
    a, b = runway.posting_date(a), runway.posting_date(b)
    if a > b:
        a, b = b, a
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() not in (4, 5):
            n += 1
    return n


def add_months(d, n):
    idx = d.year * 12 + d.month - 1 + n
    y, m = idx // 12, idx % 12 + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def find_gaps(dates, min_days):
    """[(prev, next)] where consecutive transaction dates are > min_days apart."""
    ds = sorted({d for d in dates})
    return [(a, b) for a, b in zip(ds, ds[1:]) if (b - a).days > min_days]


def in_gap(gaps, d):
    return any(a < d < b for a, b in gaps)


def date_status(d, sources, coverage, gaps):
    """Can `sources` vouch for date `d`? The weakest source decides, because the
    thing being looked for may live in whichever one is blind there.

    'out_of_coverage' - some source does not span d at all (nothing to prove);
    'in_gap'          - d falls inside a hole in a source that otherwise spans it;
    'covered'         - every source should contain it.
    """
    states = []
    for s in sources:
        if s not in coverage or not (coverage[s][0] <= d <= coverage[s][1]):
            states.append("out_of_coverage")
        elif in_gap(gaps.get(s, []), d):
            states.append("in_gap")
        else:
            states.append("covered")
    for worst in ("out_of_coverage", "in_gap"):
        if worst in states:
            return worst
    return "covered"


def coverage_of(rows_by_source):
    return {s: (min(r["_date"] for r in rows), max(r["_date"] for r in rows))
            for s, rows in rows_by_source.items() if rows}


def issuer_of(description):
    """cal / amex / max when the bank-side description names that card issuer."""
    desc = description or ""
    low = desc.lower()
    for issuer, phrases in ISSUER_PHRASES.items():
        for p in phrases:
            if (p in low) if p.isascii() else (p in desc):
                return issuer
    return None


def _tx(row, reason=None, **extra):
    """A detail row naming one concrete transaction."""
    out = {"date": str(row.get("date") or "")[:10], "description": row.get("description"),
           "amount": row.get("amount"), "source": row.get("origin") or row.get("source")}
    if reason:
        out["reason"] = reason
    out.update(extra)
    return out


LEVEL_ORDER = {"fail": 0, "warn": 1}


def _cap(details):
    """Cap a check's details at MAX_DETAILS, failures before warnings."""
    if all("level" in d for d in details):
        details = sorted(details, key=lambda d: LEVEL_ORDER.get(d["level"], 2))
    if len(details) <= MAX_DETAILS:
        return details
    return details[:MAX_DETAILS] + [{"reason": f"... and {len(details) - MAX_DETAILS} more"}]


def _status(has_fail, has_warn):
    return "fail" if has_fail else "warn" if has_warn else "pass"


# --- Data access ------------------------------------------------------------

class Dataset:
    """Read-only view over a data directory (raw dumps + normalized output)."""

    def __init__(self, root):
        self.root = Path(root)

    def raw_dir(self, source):
        return self.root / source / "raw"

    def raw(self, source, name):
        try:
            return json.loads((self.raw_dir(source) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def scrape_date(self, source):
        """Date the newest raw file of `source` was written (None if there is none)."""
        files = [f for f in self.raw_dir(source).glob("*") if f.is_file() and not f.name.startswith(".")]
        if not files:
            return None
        return datetime.datetime.fromtimestamp(max(f.stat().st_mtime for f in files)).date()

    def raw_files(self, source, pattern):
        return sorted(self.raw_dir(source).glob(pattern))

    def normalized(self, source, entity):
        try:
            env = json.loads((self.root / source / "normalized" / f"{entity}.json")
                             .read_text(encoding="utf-8"))
            return env.get("records", [])
        except (OSError, ValueError):
            return None

    def bank_rows(self):
        """Every bank-side transaction, stamped with its source and parsed date."""
        rows = []
        for src in BANK_SOURCES:
            for r in self.normalized(src, "transactions") or []:
                try:
                    d = _d(r["date"])
                except (KeyError, TypeError, ValueError):
                    continue
                rows.append({**r, "origin": src, "source": src, "_source": src, "_date": d})
        return rows


def group_by_source(rows):
    out = defaultdict(list)
    for r in rows:
        out[r["origin"]].append(r)
    return out


def bank_context(rows, scraped=None):
    """(coverage, gaps) per bank source, from the transactions each one holds.

    `scraped` ({source: date the dump was taken}) extends a source's coverage past
    its last transaction: a quiet account scraped on the 9th still vouches for the
    8th even though nothing posted since the 2nd.
    """
    by_src = group_by_source(rows)
    coverage = coverage_of(by_src)
    for s, (first, last) in list(coverage.items()):
        coverage[s] = (first, max(last, (scraped or {}).get(s, last)))
    gaps = {s: find_gaps([r["_date"] for r in rs], GAP_DAYS.get(s, 30)) for s, rs in by_src.items()}
    return coverage, gaps


# ============================================================================
# 1. Dump sanity
# ============================================================================

def error_reason(obj):
    """Why a parsed dump body is an error stub rather than data, else None.

    A half-authenticated scrape returns HTTP 200 with a few hundred bytes of error
    JSON; each institution words it differently, so we know the shapes: telebank
    `Error`, Isracard/AMEX `isSuccess: false`, CAL `statusCode != 1`, Leumi
    `ProcessRequestResult != 0` / empty `jsonResp`, plus generic 401/403 bodies.
    """
    if not isinstance(obj, dict):
        return None
    if obj.get("Error"):
        return f"Error envelope {json.dumps(obj['Error'], ensure_ascii=False)[:80]}"
    if obj.get("isSuccess") is False or obj.get("isError") is True:
        return f"unsuccessful response (errorCode {obj.get('errorCode')})"
    code = obj.get("statusCode")
    if code is not None and code != 1:
        return f"statusCode {code} {obj.get('statusTitle') or obj.get('statusDescription') or ''}".strip()
    if obj.get("ProcessRequestResult") not in (None, 0):
        return f"ProcessRequestResult {obj['ProcessRequestResult']}"
    if "jsonResp" in obj and not obj["jsonResp"]:
        return "empty jsonResp"
    if obj.get("status") in (401, 403, 500, 502, 503) or obj.get("errors"):
        return f"HTTP-style error {obj.get('status') or obj.get('errors')}"
    return None


def check_raw_file(path, min_bytes=MIN_REQUIRED_BYTES):
    """None if the dump file is healthy, else the reason it must not be trusted."""
    path = Path(path)
    if not path.exists():
        return "missing"
    size = path.stat().st_size
    if size == 0:
        return "empty file"
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        return f"not valid JSON ({e})"
    reason = error_reason(obj)
    if reason:
        return f"error stub: {reason}"
    if size < min_bytes:
        return f"suspiciously small ({size} bytes)"
    return None


def raw_findings(source, raw_dir, as_of):
    """[(level, reason)] about the raw files themselves."""
    raw_dir = Path(raw_dir)
    out = []
    if not raw_dir.is_dir():
        return [("fail", f"no raw directory for {source}")]
    for name in SOURCE_SPECS[source]["required"]:
        why = check_raw_file(raw_dir / name)
        if why:
            out.append(("fail", f"{name}: {why}"))

    def load(name):
        try:
            return json.loads((raw_dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    if source == "cal":
        # Every live card needs its own pull; blocked/cancelled cards legitimately
        # return a ~1 KB empty cycle, so only error markers matter here.
        for c in (load("account_init.json").get("result") or {}).get("cards", []):
            if c.get("statusForDisplay"):                    # blocked / cancelled
                continue
            files = sorted(raw_dir.glob(f"cardTransactions_{c['last4Digits']}_*.json"))
            if not files:
                out.append(("fail", f"no cardTransactions file for live card {c['last4Digits']}"))
            for f in files:
                why = check_raw_file(f, min_bytes=0)
                if why:
                    out.append(("fail", f"{f.name}: {why}"))
    elif source == "amex":
        # Inactive cards answer errorCode 22 ("no data") for every month - normal.
        # An ACTIVE card must have a good pull for this or last month's statement.
        wanted = {f"{as_of.month:02d}-{as_of.year}",
                  f"{add_months(as_of.replace(day=1), -1).month:02d}-{add_months(as_of.replace(day=1), -1).year}"}
        for c in (load("cardList.json").get("data") or {}).get("cardsList", []):
            if not c.get("isActive") or c.get("isBlock"):
                continue
            suffix = c["cardSuffix"]
            good = [m for m in wanted
                    if (raw_dir / f"transactions_{suffix}_{m}.json").exists()
                    and not check_raw_file(raw_dir / f"transactions_{suffix}_{m}.json", min_bytes=0)]
            if not good:
                out.append(("fail", f"active card {suffix}: no good statement pull for {sorted(wanted)}"))
    return out


def load_normalized_dir(directory):
    """{entity: records} from a normalized/ directory."""
    out = {}
    for fp in sorted(Path(directory).glob("*.json")):
        try:
            env = json.loads(fp.read_text(encoding="utf-8"))
            out[env.get("entity") or fp.stem] = env.get("records", [])
        except (OSError, ValueError):
            continue
    return out


def dry_run_normalize(source, data_dir):
    """Normalize the raw dump into a throwaway directory -> ({entity: records}, error).

    normalize.py writes next to itself, so it is copied into a temp dir with raw/
    symlinked in; the real normalized/ output (the 'previous' baseline) and the raw
    dump stay untouched.
    """
    script = Path(data_dir) / source / "normalize.py"
    if not script.exists():
        script = CODE_ROOT / source / "normalize.py"
    if not script.exists():
        return None, "no normalize.py"
    with tempfile.TemporaryDirectory() as tmp:
        sdir = Path(tmp) / source
        sdir.mkdir()
        shutil.copy(script, sdir / "normalize.py")
        (sdir / "raw").symlink_to((Path(data_dir) / source / "raw").resolve())
        try:
            proc = subprocess.run([sys.executable, str(sdir / "normalize.py")], cwd=tmp,
                                  capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            return None, "normalize.py timed out"
        if proc.returncode:
            tail = (proc.stderr.strip().splitlines() or ["exit " + str(proc.returncode)])[-1]
            return None, f"normalize.py crashed: {tail}"
        return load_normalized_dir(sdir / "normalized"), None


def count_drops(prev, new, threshold=COUNT_DROP, min_prev=3):
    """[(entity, prev_n, new_n)] where an entity lost more than `threshold` of its records."""
    out = []
    for entity, prev_records in prev.items():
        p, n = len(prev_records), len(new.get(entity, []))
        if p >= min_prev and n < p * (1 - threshold):
            out.append((entity, p, n))
    return out


def is_cycle_rollover(prev_records, new_records):
    """True when a card dump moved on to a newer billing cycle.

    CAL pulls ONE cycle per card, so the day after a statement closes the record
    count legitimately collapses to a few days of purchases.
    """
    top = lambda rs: max((r.get("billing_date") or "" for r in rs), default="")
    return bool(top(prev_records)) and top(new_records) > top(prev_records)


def latest_txn_date(records):
    ds = [str(r["date"])[:10] for r in records or [] if r.get("date")]
    return max(ds) if ds else None


def check_dump(source, data_dir=DEFAULT_DATA_DIR, as_of=None, dry_run=True, new=None):
    """Sanity-check one source's fresh dump before trusting it.

    `new` ({entity: records}) injects the normalized result instead of running
    normalize.py - used by tests. Status 'fail' means REJECT the scrape.
    """
    as_of = as_of or date.today()
    cid = f"dump.{source}"
    if source not in SOURCE_SPECS:
        return result(cid, "dump", "fail", f"unknown source {source!r}")
    ds = Dataset(data_dir)
    spec = SOURCE_SPECS[source]
    findings = [{"level": lvl, "reason": why} for lvl, why in raw_findings(source, ds.raw_dir(source), as_of)]

    prev = load_normalized_dir(Path(data_dir) / source / "normalized")
    if new is None and dry_run and not findings:
        new, err = dry_run_normalize(source, data_dir)
        if err:
            findings.append({"level": "fail", "reason": err})
    new = new if new is not None else prev

    for entity, p, n in count_drops(prev, new):
        rollover = entity == "transactions" and is_cycle_rollover(prev.get(entity, []), new.get(entity, []))
        findings.append({
            "level": "warn" if rollover else "fail",
            "reason": f"{entity}: {p} -> {n} records ({(n - p) / p:+.0%})"
                      + (" - new billing cycle, expected" if rollover else " - more than "
                         f"{COUNT_DROP:.0%} drop vs previous normalized output")})

    latest = latest_txn_date(new.get("transactions"))
    max_age = spec["max_txn_age_days"]
    if max_age is not None and not any(f["level"] == "fail" for f in findings):
        if latest is None:
            findings.append({"level": "fail", "reason": "no transactions at all"})
        elif (as_of - _d(latest)).days > max_age:
            findings.append({"level": "fail", "reason":
                             f"latest transaction {latest} is {(as_of - _d(latest)).days} days old "
                             f"(limit {max_age})"})

    status = _status(any(f["level"] == "fail" for f in findings),
                     any(f["level"] == "warn" for f in findings))
    counts = {e: len(rs) for e, rs in new.items()}
    reasons = "; ".join(f["reason"] for f in findings if f["level"] in ("fail", "warn"))
    summary = (f"{source}: " + (reasons or "ok")
               + f" (records {counts}, latest txn {latest or 'n/a'})")
    for f in findings:
        f["source"] = source
    return result(cid, "dump", status, summary, findings)


# ============================================================================
# 2. Card bills: statement total <-> bank debit
# ============================================================================

def cal_statements(summary, as_of):
    """CAL debit events (cycle + immediate) from monthlyDebitsSummary, in ₪.

    The summary lists every debit day per card for a year back AND the scheduled
    ones ahead; only the ones already due matter.
    """
    out = []
    for ba in (summary or {}).get("result", {}).get("bankAccounts", []) or []:
        for m in ba.get("months", []):
            for day in m.get("debitDays", []):
                total = sum(dd.get("dailyDebit", 0) for c in day.get("cards", [])
                            for dd in c.get("dailyDebits", []) if dd.get("currencySymbol") == "₪")
                if total <= 0:
                    continue
                kinds = {c.get("debitDateInd") for c in day.get("cards", [])}
                out.append({"issuer": "cal", "card": "all", "billing_date": _d(day["debitDay"]),
                            "amount": round(total, 2),
                            "kind": "immediate" if kinds == {2} else "cycle"})
    return [s for s in out if s["billing_date"] <= as_of]


def amex_card_billing_days(card_list):
    """suffix -> day of month the card is billed (dd/mm/yyyy in cardChargeLast/Next)."""
    days = {}
    for c in ((card_list or {}).get("data") or {}).get("cardsList", []):
        for k in ("cardChargeLast", "cardChargeNext"):
            bd = (c.get(k) or {}).get("billingDate")
            if bd:
                try:
                    days[c["cardSuffix"]] = _dmy(bd).day
                    break
                except ValueError:
                    continue
    return days


_AMEX_FILE = re.compile(r"transactions_(\d+)_(\d{2})-(\d{4})\.json$")


def amex_months(files, billing_days):
    """Parse AMEX per-card monthly pulls -> [{card, billing_date, statement_total,
    vouchers: [...], immediate: [...]}] (errored / empty pulls are dropped)."""
    out = []
    for fp, body in files:
        m = _AMEX_FILE.search(str(fp))
        data = (body or {}).get("data")
        if not m or not data:
            continue
        suffix, mm, yy = m.group(1), int(m.group(2)), int(m.group(3))
        block = data.get("israelAbroadVouchers") or {}
        total = ((block.get("vouchers") or {}).get("totalForStatement") or {}).get("totalIlsBillingDate")
        vouchers = ((block.get("vouchers") or {}).get("israelAbroadVouchersList")) or []
        day = billing_days.get(suffix)
        bdate = date(yy, mm, 1)
        if day:
            bdate = date(yy, mm, min(day, (add_months(date(yy, mm, 1), 1) - timedelta(days=1)).day))
        immediate = []
        for grp in block.get("outOfStatementChargeDateVouchers") or []:
            tot = grp.get("totalVouchersCurrencyDate") or {}
            if not tot.get("dateImmediateVouchers"):
                continue
            immediate.append({"billing_date": _dmy(tot["dateImmediateVouchers"]),
                              "amount": _money(tot.get("totalImmediateVouchers")),
                              "vouchers": grp.get("immediateVouchersCurrencyDate") or []})
        out.append({"card": suffix, "billing_date": bdate, "statement_total": _money(total),
                    "vouchers": vouchers, "immediate": immediate})
    return out


def amex_statements(months, as_of):
    """Statement + immediate-charge events for check 2 (deduped across pulls)."""
    out, seen = [], set()
    for m in months:
        if m["statement_total"] > 0 and m["billing_date"] <= as_of:
            out.append({"issuer": "amex", "card": m["card"], "billing_date": m["billing_date"],
                        "amount": m["statement_total"], "kind": "cycle"})
        for im in m["immediate"]:
            key = (m["card"], im["billing_date"], im["amount"])
            if key in seen or im["amount"] <= 0 or im["billing_date"] > as_of:
                continue
            seen.add(key)
            out.append({"issuer": "amex", "card": m["card"], "billing_date": im["billing_date"],
                        "amount": im["amount"], "kind": "immediate"})
    return out


def _match_debit(st, debits, used):
    """Index of the unused bank debit that settles statement `st`, else None."""
    due = runway.posting_date(st["billing_date"])
    best = None
    for i, r in enumerate(debits):
        if i in used or issuer_of(r.get("description")) != st["issuer"]:
            continue
        if abs(abs(r["amount"]) - st["amount"]) > AMOUNT_TOL:
            continue
        gap = business_days_between(due, r["_date"])
        if gap <= BILL_BDAYS and (best is None or gap < best[0]):
            best = (gap, i)
    return best[1] if best else None


def check_card_bills(statements, bank_rows, as_of, coverage, gaps):
    """Every card statement should be settled by one bank debit, and vice versa.

    Banks do not post Fri/Sat, so a Saturday billing date settles on Sunday; a
    debit within BILL_BDAYS banking days of that counts. Statements the bank
    ledger cannot speak to (before it starts, or inside a hole in it) are
    reported separately from genuine mismatches.
    """
    cid = "card_bills"
    if not statements:
        return result(cid, "card_bill", "skip", "no card statements in the dumps")
    debits = [r for r in bank_rows if r["amount"] < 0 and r["_date"] <= as_of]
    used, matched, details = set(), [], []
    classifier_gaps = []
    unmatched = []
    payers = defaultdict(set)            # (issuer, card) -> bank sources that actually paid it
    for st in sorted(statements, key=lambda s: (s["billing_date"], s["card"])):
        i = _match_debit(st, debits, used)
        if i is not None:
            used.add(i)
            matched.append((st, i))
            payers[(st["issuer"], st["card"])].add(debits[i]["origin"])
            if not digest.is_card_bill_payment(debits[i]):
                classifier_gaps.append((st, debits[i]))
        else:
            unmatched.append(st)
    # Two cards of one issuer billed to the same account the same day arrive as ONE
    # bank debit - retry unmatched statements as a per-(issuer, date) sum.
    groups = defaultdict(list)
    for st in unmatched:
        groups[(st["issuer"], st["billing_date"])].append(st)
    for (issuer, bdate), sts in groups.items():
        if len(sts) < 2:
            continue
        combo = {"issuer": issuer, "billing_date": bdate, "card": "+".join(s["card"] for s in sts),
                 "amount": round(sum(s["amount"] for s in sts), 2), "kind": "cycle"}
        i = _match_debit(combo, debits, used)
        if i is not None:
            used.add(i)
            matched.append((combo, i))
            unmatched = [s for s in unmatched if s not in sts]

    n_gap = n_out = n_fail = 0
    for st in unmatched:
        due = runway.posting_date(st["billing_date"])
        # A card is paid from one account; once any of its statements matched we
        # know which, so a hole in some OTHER bank's history cannot explain this one.
        payer = payers.get((st["issuer"], st["card"])) or BANK_SOURCES
        where = date_status(due, sorted(payer), coverage, gaps)
        row ={"date": due.isoformat(), "description": f"{st['issuer']} {st['kind']} statement ····{st['card']}",
               "amount": -st["amount"], "source": st["issuer"]}
        if where == "out_of_coverage":
            n_out += 1
        elif where == "in_gap":
            n_gap += 1
            details.append({**row, "level": "warn", "reason":
                            "no bank debit - the bank ledger has a hole around this date (see balance checks)"})
        else:
            n_fail += 1
            details.append({**row, "level": "fail", "reason":
                            f"statement total has no matching bank debit within {BILL_BDAYS} banking days"})

    # Bank side: card-bill debits of an issuer whose statements we hold, with none.
    first_stmt = {}
    for st in statements:
        first_stmt[st["issuer"]] = min(first_stmt.get(st["issuer"], st["billing_date"]), st["billing_date"])
    n_untracked = n_credit = 0
    for i, r in enumerate(debits):
        if i in used or not digest.is_card_bill_payment(r):
            continue
        issuer = issuer_of(r.get("description"))
        if issuer not in TRACKED_ISSUERS:
            n_untracked += 1                    # e.g. Max: no statement source to compare
            continue
        if r["_date"] < first_stmt.get(issuer, as_of) - timedelta(days=BILL_BDAYS + 2):
            continue                            # predates the statements we hold
        n_fail += 1
        details.append(_tx(r, "card-bill debit with no matching statement total", level="fail"))
    n_credit = sum(1 for r in bank_rows if r["amount"] > 0 and digest.is_card_bill_payment(r))
    for st, r in classifier_gaps:
        details.append(_tx(r, "matches a card statement but digest.is_card_bill_payment() "
                              "does not recognise it, so the ledger would count it as spending",
                           level="warn"))

    status = _status(n_fail, n_gap or classifier_gaps)
    summary = (f"{len(matched)} of {len(statements)} statements matched a bank debit; "
               f"{n_fail} unmatched, {n_gap} in bank-ledger gaps, {n_out} before bank coverage; "
               f"{len(classifier_gaps)} unclassified by digest; {n_untracked} debits of unscraped issuers, "
               f"{n_credit} reversal credits ignored")
    return result(cid, "card_bill", status, summary, _cap(details))


# ============================================================================
# 3. Card transactions <-> statement total
# ============================================================================

def cal_cycles(files):
    """[(last4, cardTransactions body)] -> one summary per card cycle.

    `billed` is Σ amtBeforeConvAndIndex: the ₪ actually charged this cycle
    (refunds are already negative there). `trnAmt` is NOT that for foreign-currency
    purchases (it is in the foreign unit) nor for installments (it is the whole
    deal), which is what the statement total exposes. `txns` keeps each raw row's
    billed amount so a mismatch can be pinned on the rows behind it.
    """
    cycles = []
    for last4, body in files:
        for ba in ((body or {}).get("result") or {}).get("bankAccounts", []) or []:
            for dd in ba.get("debitDates", []) or []:
                total = sum(t.get("amount", 0) for t in dd.get("totalDebits", []) or []
                            if t.get("currencySymbol") == "₪")
                raw = dd.get("transactions") or []
                cycles.append({
                    "card": last4, "billing_date": _d(dd["date"]), "statement": round(total, 2),
                    "billed": round(sum(t.get("amtBeforeConvAndIndex", 0) for t in raw), 2),
                    "count": len(raw),
                    "txns": [{"date": (t.get("trnPurchaseDate") or "")[:10],
                              "description": (t.get("merchantName") or "").strip(),
                              "billed": -round(t.get("amtBeforeConvAndIndex", 0), 2),
                              "trn_amt": t.get("trnAmt"), "type": t.get("trnType"),
                              "currency": t.get("trnCurrencySymbol"),
                              "installment": (f"{t.get('curPaymentNum')}/{t.get('numOfPayments')}"
                                              if t.get("numOfPayments") else None)}
                             for t in raw]})
    return cycles


def _cal_offenders(cycle, ledger_rows):
    """Raw rows whose ledger amount differs from what CAL billed (ledger sign: out < 0)."""
    held = defaultdict(list)
    for r in ledger_rows:
        held[(str(r.get("date"))[:10], (r.get("description") or "").strip())].append(round(r.get("amount", 0), 2))
    out = []
    for t in cycle["txns"]:
        amounts = held.get((t["date"], t["description"]), [])
        if t["billed"] in amounts:
            amounts.remove(t["billed"])
            continue
        if not t["billed"] and not amounts:
            continue                    # billed 0 and (rightly) not in the ledger
        ours = amounts.pop(0) if amounts else None
        why = (f"ledger carries {ours:+,.2f}" if ours is not None else "not in the ledger")
        kind = t["type"] + (f" {t['installment']}" if t["installment"] else "") + (
            f", {t['currency']}" if t["currency"] not in (None, "₪") else "")
        out.append({"date": t["date"], "description": t["description"], "amount": ours,
                    "source": "cal", "reason": f"{why}; CAL billed {t['billed']:+,.2f} ({kind})"})
    return out


def check_cal_statements(cycles, normalized_txns):
    """Σ the ledger's CAL transactions per card cycle == the cycle's statement total."""
    cid = "card_statements.cal"
    live = [c for c in cycles if c["statement"] or c["count"]]
    if not live:
        return result(cid, "card_statement", "skip", "CAL dump has no card cycles")
    by_cycle = defaultdict(list)
    for t in normalized_txns or []:
        by_cycle[(t.get("card_last4"), str(t.get("billing_date"))[:10])].append(t)
    details, bad = [], 0
    for c in live:
        rows = by_cycle.get((c["card"], c["billing_date"].isoformat()), [])
        ledger = round(-sum(r.get("amount", 0) for r in rows), 2)
        diff = round(ledger - c["statement"], 2)
        if abs(diff) <= STATEMENT_TOL:
            continue
        bad += 1
        if abs(c["billed"] - c["statement"]) <= STATEMENT_TOL:
            why = ("the dump is complete (Σ ₪ billed equals the statement) but the ledger carries "
                   "different amounts for the rows below")
        else:
            why = (f"even the raw billed ₪ (Σ {c['billed']:,.2f}) differs from the statement - "
                   "the dump itself is incomplete or paginated")
        details.append({"date": c["billing_date"].isoformat(),
                        "description": f"CAL card ····{c['card']} cycle, {c['count']} transactions",
                        "amount": -diff, "source": "cal", "level": "fail",
                        "reason": f"ledger {ledger:,.2f} vs statement {c['statement']:,.2f} "
                                  f"(off by {diff:+,.2f}); {why}"})
        worst = sorted(_cal_offenders(c, rows), key=lambda o: abs(o["amount"] or 0), reverse=True)
        details.extend({**o, "level": "info"} for o in worst[:8])
    summary = (f"{len(live) - bad} of {len(live)} CAL card cycles reconcile to their statement total"
               if not bad else f"{bad} of {len(live)} CAL card cycles do not reconcile to the statement total")
    return result(cid, "card_statement", "fail" if bad else "pass", summary, _cap(details))


def check_amex_statements(months, normalized_txns):
    """AMEX: Σ vouchers == statement total, and every voucher reached the ledger.

    The second half catches the normalizer silently dropping rows, e.g. the
    immediate-charge vouchers (cash withdrawals) AMEX lists outside the statement.
    """
    cid = "card_statements.amex"
    if not months:
        return result(cid, "card_statement", "skip", "AMEX dump has no statement pulls")
    held = Counter((t.get("card_last4"), str(t.get("date"))[:10], round(t.get("amount", 0), 2))
                   for t in normalized_txns or [])
    details, bad_totals, missing = [], 0, 0
    seen_imm = set()
    for m in months:
        def voucher_amount(v):
            a = v.get("billingAmount")
            return _money(v.get("ilsAmount") if a is None else a)
        total = round(sum(voucher_amount(v) for v in m["vouchers"]), 2)
        if abs(total - m["statement_total"]) > AMOUNT_TOL:
            bad_totals += 1
            details.append({"date": m["billing_date"].isoformat(),
                            "description": f"AMEX card ····{m['card']} statement, {len(m['vouchers'])} vouchers",
                            "amount": round(m["statement_total"] - total, 2), "source": "amex", "level": "fail",
                            "reason": f"Σ vouchers {total:,.2f} vs statement {m['statement_total']:,.2f}"})
        groups = [("statement", m["vouchers"])] + [
            ("immediate", im["vouchers"]) for im in m["immediate"]]
        for kind, vs in groups:
            for v in vs:
                if kind == "immediate":
                    key = (m["card"], v.get("seqVoucherNumber"))
                    if key in seen_imm:
                        continue
                    seen_imm.add(key)
                d = _dmy(v["purchaseDate"]).isoformat()
                k = (m["card"], d, round(-voucher_amount(v), 2))
                if held[k] > 0:
                    held[k] -= 1
                    continue
                missing += 1
                details.append({"date": d, "description": (v.get("businessName") or "").strip(),
                                "amount": -voucher_amount(v), "source": "amex", "level": "fail",
                                "reason": f"{kind} voucher on card ····{m['card']} is in the raw dump "
                                          "but not in the normalized transactions"})
    n_m = len(months)
    status = "fail" if bad_totals or missing else "pass"
    summary = (f"{n_m - bad_totals} of {n_m} AMEX statements sum to their total; "
               f"{missing} raw vouchers missing from the normalized ledger")
    return result(cid, "card_statement", status, summary, _cap(details))


# ============================================================================
# 4. Checking balance continuity
# ============================================================================

def _chain_breaks(ops):
    """Indexes i where ops[i-1].balance_after + ops[i].amount != ops[i].balance_after."""
    return [i for i in range(1, len(ops))
            if abs(ops[i - 1]["balance_after"] + ops[i]["amount"] - ops[i]["balance_after"]) > AMOUNT_TOL]


def orient_ops(ops):
    """Return `ops` oldest-first. Dumps say DESC but arrive either way, so pick the
    orientation whose running balances actually chain (date order breaks ties)."""
    fwd, rev = list(ops), list(reversed(ops))
    bf, br = len(_chain_breaks(fwd)), len(_chain_breaks(rev))
    if bf == br:
        return fwd if fwd[0]["date"] <= fwd[-1]["date"] else rev
    return fwd if bf < br else rev


def telebank_ops(tx_body):
    """Discount / Discount-business CurrentAccountLastTransactions -> ops."""
    block = (tx_body or {}).get("CurrentAccountLastTransactions") or {}
    return [{"date": _ymd(o["OperationDate"]), "amount": _money(o["OperationAmount"]),
             "balance_after": _money(o["BalanceAfterOperation"]),
             "description": o.get("OperationDescriptionToDisplay") or o.get("OperationDescription")}
            for o in block.get("OperationEntry") or []
            if o.get("BalanceAfterOperation") is not None]


def leumi_ops(tx_body):
    """Leumi HistoryTransactionsItems (jsonResp-wrapped) -> ops."""
    body = (tx_body or {}).get("jsonResp", tx_body) or {}
    return [{"date": _dmy(t["DateSO"]), "amount": _money(t["Amount"]),
             "balance_after": _money(t["RunningBalance"]), "description": t.get("Description")}
            for t in body.get("HistoryTransactionsItems") or []]


def check_balance(source, ops, closing, rows, gap_days=None):
    """opening balance + transactions = closing balance, and no holes in history.

    `ops` is the raw dump's running-balance chain, `closing` the account's current
    balance, `rows` the normalized ledger rows of this account. Four independent
    tests: the chain links (no skipped operation), the last link equals the
    current balance, the normalized ledger sums to the same movement over the
    chain's window (dedup/normalizer dropped nothing), and the ledger has no
    multi-week silence.
    """
    cid = f"balance.{source}"
    gap_days = gap_days or GAP_DAYS.get(source, 30)
    details, fail = [], False

    gaps = find_gaps([r["_date"] for r in rows], gap_days)
    for a, b in gaps:
        fail = True
        details.append({"date": a.isoformat(), "source": source, "level": "fail",
                        "description": f"no {source} transactions between {a} and {b}",
                        "amount": None,
                        "reason": f"{(b - a).days}-day hole (limit {gap_days}); history in "
                                  "this range was never captured"})
    if not ops:
        status = "fail" if fail else "skip"
        return result(cid, "balance", status,
                      f"{source}: no running-balance chain in the dump"
                      + (f"; {len(gaps)} history gap(s)" if gaps else ""), details)

    ops = orient_ops(ops)
    breaks = _chain_breaks(ops)
    problems = [f"{len(gaps)} history gap(s)"] if gaps else []
    if breaks:
        problems.append(f"{len(breaks)} chain break(s)")
    for i in breaks:
        fail = True
        prev, cur = ops[i - 1], ops[i]
        details.append({"date": cur["date"].isoformat(), "source": source, "level": "fail",
                        "description": cur.get("description"), "amount": cur["amount"],
                        "reason": f"balance chain breaks between {prev['date']} and {cur['date']}: "
                                  f"{prev['balance_after']:,.2f} {cur['amount']:+,.2f} should be "
                                  f"{prev['balance_after'] + cur['amount']:,.2f}, dump says "
                                  f"{cur['balance_after']:,.2f} - an operation is missing in between"})
    if closing is not None and abs(ops[-1]["balance_after"] - closing) > AMOUNT_TOL:
        fail = True
        problems.append("closing balance differs from the last operation")
        details.append({"date": ops[-1]["date"].isoformat(), "source": source, "level": "fail",
                        "description": "closing balance", "amount": round(closing - ops[-1]["balance_after"], 2),
                        "reason": f"last operation leaves {ops[-1]['balance_after']:,.2f} but the account "
                                  f"balance is {closing:,.2f}"})

    first, last = ops[0], ops[-1]
    opening = round(first["balance_after"] - first["amount"], 2)
    expected = round(last["balance_after"] - opening, 2)
    window = [r for r in rows if first["date"] <= r["_date"] <= last["date"]]
    got = round(sum(r["amount"] for r in window), 2)
    if abs(got - expected) > AMOUNT_TOL:
        fail = True
        problems.append(f"normalized ledger is off by {got - expected:+,.2f} vs the balance movement")
        held = Counter((r["_date"], round(r["amount"], 2)) for r in window)
        lost = []
        for o in ops:
            k = (o["date"], o["amount"])
            if held[k] > 0:
                held[k] -= 1
            else:
                lost.append(o)
        details.append({"date": first["date"].isoformat(), "source": source, "level": "fail",
                        "description": f"ledger movement {first['date']}..{last['date']}", "amount": round(got - expected, 2),
                        "reason": f"opening {opening:,.2f} -> closing {last['balance_after']:,.2f} is "
                                  f"{expected:+,.2f}, but the normalized ledger sums to {got:+,.2f}"})
        details.extend({"date": o["date"].isoformat(), "description": o.get("description"),
                        "amount": o["amount"], "source": source, "level": "fail",
                        "reason": "in the raw balance chain but missing from the normalized ledger"}
                       for o in lost)
    summary = (f"{source}: {len(ops)} chained operations {first['date']}..{last['date']} "
               f"({opening:,.2f} -> {last['balance_after']:,.2f}); "
               + ("consistent" if not fail else "; ".join(problems)))
    return result(cid, "balance", "fail" if fail else "pass", summary, _cap(details))


# ============================================================================
# 5. Internal transfers
# ============================================================================

def is_transfer_leg(row):
    desc = row.get("description") or ""
    return digest.is_internal_transfer(row) or any(p in desc for p in SALARY_FORWARD_PHRASES)


def transfer_hint(row, origin):
    """('untracked', why) when the other leg is outside our data by design, else
    ('expect', [sources]) naming where the opposite leg should be."""
    desc = row.get("description") or ""
    if any(p in desc for p in digest.DEPOSIT_WITHDRAWAL_PHRASES):
        return "untracked", "liquid deposit (savings entity, no transactions)"
    if digest._LOAN_ID_RE.search(desc):
        return "untracked", "loan round-trip"
    if any(h in desc for h in UNTRACKED_HINTS):
        return "untracked", "Bank Hapoalim / Bit (not scraped)"
    m = _BANK_BRANCH_RE.search(desc)
    sources = BANK_CODE_SOURCES.get(m.group(1)[:2]) if m else None
    sources = tuple(s for s in (sources or BANK_SOURCES) if s != origin)
    return "expect", list(sources)


def check_internal_transfers(rows, as_of, coverage, gaps):
    """Each own-account transfer needs its opposite leg within TRANSFER_BDAYS banking days."""
    cid = "internal_transfers"
    legs = [r for r in rows if is_transfer_leg(r) and r["_date"] <= as_of]
    if not legs:
        return result(cid, "internal_transfer", "skip", "no internal transfers in the bank ledgers")
    used, matched, untracked, out_cov = set(), 0, 0, 0
    details, n_fail, n_gap = [], 0, 0
    for r in sorted(legs, key=lambda r: (r["_date"], r["origin"])):
        kind, info = transfer_hint(r, r["origin"])
        if kind == "untracked":
            untracked += 1
            continue
        if id(r) in used:
            continue
        cands = [(business_days_between(r["_date"], o["_date"]), j) for j, o in enumerate(rows)
                 if id(o) not in used and o["origin"] in info and o is not r
                 and o["amount"] * r["amount"] < 0
                 and abs(abs(o["amount"]) - abs(r["amount"])) <= AMOUNT_TOL]
        cands = [c for c in cands if c[0] <= TRANSFER_BDAYS]
        if cands:
            j = min(cands)[1]
            used.update((id(r), id(rows[j])))
            matched += 1
            continue
        where = date_status(r["_date"], info, coverage, gaps)
        if where == "out_of_coverage":
            out_cov += 1
        elif where == "in_gap":
            n_gap += 1
            details.append(_tx(r, f"opposite leg expected in {'/'.join(info)}, which has a hole in its "
                                  "history here (see balance checks)", level="warn"))
        else:
            n_fail += 1
            details.append(_tx(r, f"no opposite leg of {abs(r['amount']):,.2f} in {'/'.join(info)} "
                                  f"within {TRANSFER_BDAYS} banking days", level="fail"))
    summary = (f"{matched} transfers paired; {n_fail} orphaned, {n_gap} orphaned inside history gaps, "
               f"{out_cov} outside the other account's coverage, {untracked} to/from untracked accounts")
    return result(cid, "internal_transfer", _status(n_fail, n_gap), summary, _cap(details))


# ============================================================================
# 6. Loan payments
# ============================================================================

LOAN_AMOUNT_TOL = 5.0         # ₪ - a variable-rate installment drifts by a few shekels
LOAN_AMOUNT_WARN = 0.05       # relative: beyond this the dump and the debit disagree
LOAN_MONTHS = 3               # installments back to look for a debit at all


def _loan_window(due):
    return due - timedelta(days=3), due + timedelta(days=6)


def check_loan(name, expected, next_due, rows, match, origin, as_of, coverage, gaps, months=LOAN_MONTHS):
    """Detail rows + (fail, warn, verified) for one loan.

    The dump only knows the NEXT installment, so the one just paid is one month
    earlier: look for a matching debit there (its amount should equal the dump's
    figure), and for existence in the `months - 1` before it.
    """
    details, fail, warn, verified = [], False, False, 0
    for k in range(months):
        due = add_months(next_due, -(k + 1))
        if due > as_of:
            continue
        lo, hi = _loan_window(due)
        status = date_status(runway.posting_date(due), [origin], coverage, gaps)
        if status == "out_of_coverage":
            continue
        cands = [r for r in rows if r["origin"] == origin and lo <= r["_date"] <= hi
                 and r["amount"] < 0 and match(r)]
        if not cands:
            level = "warn" if status == "in_gap" else "fail"
            fail, warn = fail or level == "fail", warn or level == "warn"
            details.append({"date": due.isoformat(), "description": name, "amount": -expected,
                            "source": origin, "level": level,
                            "reason": f"no matching debit between {lo} and {hi}"
                                      + (" (bank ledger has a hole here)" if status == "in_gap" else "")})
            continue
        verified += 1
        if k:
            continue                    # older installments: existence is enough
        r = min(cands, key=lambda r: abs(abs(r["amount"]) - expected))
        diff = abs(r["amount"]) - expected
        if abs(diff) <= max(LOAN_AMOUNT_TOL, 0.01 * expected):
            continue
        level = "warn" if abs(diff) <= LOAN_AMOUNT_WARN * expected else "fail"
        fail, warn = fail or level == "fail", warn or level == "warn"
        details.append(_tx(r, f"{name}: dump says next installment {expected:,.2f}, "
                              f"actual debit {abs(r['amount']):,.2f} ({diff:+,.2f})", level=level))
    return details, fail, warn, verified


def mortgage_expectations(body):
    """(name, Σ NextPayment, next due date) for the mortgage dump."""
    loans = []
    for entry in (((body or {}).get("MortgagesDetails") or {}).get("MortgagesBlock") or {}).get("MortgageEntry", []):
        loans += (entry.get("MortgageDetailsBlock") or {}).get("LoanEntry", [])
    if not loans:
        return None
    due = next((l["NextPaymentDate"] for l in loans if l.get("NextPaymentDate")), None)
    if not due:
        return None
    return ("Discount mortgage (Σ NextPayment of %d tracks)" % len(loans),
            round(sum(l.get("NextPayment", 0) for l in loans), 2), _ymd(due))


def discount_loan_expectations(body):
    """[(name, NextPayment, due, loan account)] for the Discount consumer loans."""
    out = []
    for ln in (((body or {}).get("LoansQuery") or {}).get("LoanDetailsBlock") or {}).get("LoanEntry", []):
        if ln.get("NextPayment") and ln.get("NextPaymentDate"):
            out.append((ln.get("LoanName"), round(ln["NextPayment"], 2), _ymd(ln["NextPaymentDate"]),
                        str(ln.get("LoanAccount"))))
    return out


def leumi_loan_expectations(loans_body):
    """[(name, next installment, due)] from the scraped Leumi loan pages."""
    out = []
    for ln in (loans_body or {}).get("loans", []):
        try:
            amount = float(str(ln["balances"]["סכום התשלום הבא"]).replace(",", ""))
            dd, mm, yy = ln["dates"]["תאריך התשלום הבא"].split("/")
            due = date(int("20" + yy if len(yy) == 2 else yy), int(mm), int(dd))
        except (KeyError, ValueError, AttributeError):
            continue
        out.append(((ln.get("loanLabel") or "").strip() + f" #{ln.get('generalInfo', {}).get('מספר הלוואה')}",
                    round(amount, 2), due))
    return out


def check_loan_group(cid, label, expectations, rows, origin, as_of, coverage, gaps):
    """expectations: [(name, amount, due, match_fn)]. One check for one lender."""
    if not expectations:
        return result(cid, "loan_payment", "skip", f"no {label} installments in the dump")
    details, fail, warn, verified = [], False, False, 0
    for name, amount, due, match in expectations:
        d, f, w, v = check_loan(name, amount, due, rows, match, origin, as_of, coverage, gaps)
        details += d
        fail, warn, verified = fail or f, warn or w, verified + v
    if not (fail or warn or verified):
        return result(cid, "loan_payment", "skip",
                      f"no {label} installment falls inside the bank ledger's coverage")
    summary = (f"{len(expectations)} {label} loan(s), {verified} installment(s) found as bank debits"
               + ("" if not (fail or warn)
                  else f"; {sum(1 for d in details if d.get('level') == 'fail')} missing/mismatched, "
                       f"{sum(1 for d in details if d.get('level') == 'warn')} warned"))
    return result(cid, "loan_payment", _status(fail, warn), summary, _cap(details))


# ============================================================================
# 7. Salary arrival
# ============================================================================

SALARY_BEFORE_DAYS = 2
SALARY_AFTER_DAYS = 4
SALARY_TOLERANCE = 0.25


def check_salary(ledger, as_of, coverage, gaps, months=4):
    """The salary runway.py expects as payday arrived in its window, month by month."""
    cid = "salary"
    items = runway.infer_recurring(ledger, as_of)
    salaries = [(k, it) for k, it in items.items() if it["kind"] == "income" and runway._is_salary(it)]
    if not salaries:
        return result(cid, "salary", "warn", "no recurring salary detected in the last 3 months of bank ledger")
    details, checked, missing = [], 0, 0
    top = max(salaries, key=lambda s: s[1]["amount"])
    for (origin, name), it in [top]:
        for k in range(months):
            first = add_months(as_of.replace(day=1), -k)
            last_day = (add_months(first, 1) - timedelta(days=1)).day
            expected = runway.posting_date(first.replace(day=min(it["day"], last_day)))
            lo, hi = expected - timedelta(days=SALARY_BEFORE_DAYS), expected + timedelta(days=SALARY_AFTER_DAYS)
            if hi > as_of:
                continue                    # payday window not over yet
            where = date_status(expected, [origin], coverage, gaps)
            if where == "out_of_coverage":
                continue
            hit = [r for r in ledger if r["origin"] == origin and lo <= _d(r["date"]) <= hi
                   and runway._norm(r["description"]) == name and r["amount"] >= runway.MIN_PAYDAY
                   and abs(r["amount"] - it["amount"]) <= SALARY_TOLERANCE * it["amount"]]
            checked += 1
            if hit:
                continue
            missing += 1
            details.append({"date": expected.isoformat(), "description": name, "amount": it["amount"],
                            "source": origin, "level": "warn" if where == "in_gap" else "fail",
                            "reason": f"no {name} of about {it['amount']:,.0f} between {lo} and {hi}"
                                      + (" (bank ledger has a hole here)" if where == "in_gap" else "")})
    n_fail = sum(1 for d in details if d["level"] == "fail")
    summary = (f"salary '{top[0][1]}' (about {top[1]['amount']:,.0f} around day {top[1]['day']}) "
               f"arrived in {checked - missing} of {checked} recent month(s)")
    return result(cid, "salary", _status(n_fail, missing - n_fail), summary, details)


# ============================================================================
# Orchestration
# ============================================================================

def _safe(id_, type_, fn):
    """A crashing check must not hide the others: report it as a failure."""
    try:
        return fn()
    except Exception as e:                                   # noqa: BLE001 - report, don't die
        return result(id_, type_, "fail", f"check crashed: {type(e).__name__}: {e}")


def run_all(data_dir=DEFAULT_DATA_DIR, as_of=None, dry_run=True):
    """Run every check against `data_dir` -> the validation report."""
    as_of = as_of or date.today()
    ds = Dataset(data_dir)
    rows = ds.bank_rows()
    scraped = {s: ds.scrape_date(s) for s in BANK_SOURCES}
    coverage, gaps = bank_context(rows, {s: d for s, d in scraped.items() if d})
    by_src = group_by_source(rows)
    checks = []

    for src in SOURCE_SPECS:
        if (Path(data_dir) / src).is_dir():
            checks.append(_safe(f"dump.{src}", "dump",
                                lambda src=src: check_dump(src, data_dir, as_of, dry_run=dry_run)))

    # 2. card bills
    def card_bills():
        statements = cal_statements(ds.raw("cal", "monthlyDebitsSummary.json"), as_of)
        files = [(fp, json.loads(fp.read_text(encoding="utf-8")))
                 for fp in ds.raw_files("amex", "transactions_*.json")]
        months = amex_months(files, amex_card_billing_days(ds.raw("amex", "cardList.json")))
        return check_card_bills(statements + amex_statements(months, as_of), rows, as_of, coverage, gaps), months
    try:
        bills, amex_m = card_bills()
        checks.append(bills)
    except Exception as e:                                   # noqa: BLE001
        checks.append(result("card_bills", "card_bill", "fail", f"check crashed: {type(e).__name__}: {e}"))
        amex_m = []

    # 3. card transactions vs statement totals
    def cal_stmt():
        files = [(fp.name.split("_")[1], json.loads(fp.read_text(encoding="utf-8")))
                 for fp in ds.raw_files("cal", "cardTransactions_*.json")]
        return check_cal_statements(cal_cycles(files), ds.normalized("cal", "transactions"))
    checks.append(_safe("card_statements.cal", "card_statement", cal_stmt))
    checks.append(_safe("card_statements.amex", "card_statement",
                        lambda: check_amex_statements(amex_m, ds.normalized("amex", "transactions"))))

    # 4. balance continuity
    def balance(src, ops_fn, raw_name, closing_fn):
        body = ds.raw(src, raw_name)
        return check_balance(src, ops_fn(body) if body else [], closing_fn(), by_src.get(src, []))
    for src in BANK_SOURCES:
        if src not in by_src:
            continue
        if src == "leumi":
            def closing():
                tot = {t["accountType"]: t["totalPerAccountType"] for t in
                       ((ds.raw("leumi", "summary.json") or {}).get("TotalPerTypeItems") or [])}
                return tot.get("CHECKING")
            fn = (lambda: balance("leumi", leumi_ops, "transactions.json", closing))
        else:
            def closing(src=src):
                return ((ds.raw(src, "infoAndBalance.json") or {}).get("AccountInfoAndBalance") or {}).get("AccountBalance")
            fn = (lambda src=src, closing=closing: balance(src, telebank_ops, "transactions.json", closing))
        checks.append(_safe(f"balance.{src}", "balance", fn))

    # 5. internal transfers
    checks.append(_safe("internal_transfers", "internal_transfer",
                        lambda: check_internal_transfers(rows, as_of, coverage, gaps)))

    # 6. loan payments
    def mortgage():
        exp = mortgage_expectations(ds.raw("discount-mortgage", "mortgage_details.json"))
        exps = [(exp[0], exp[1], exp[2], lambda r: "משכנתא" in (r.get("description") or ""))] if exp else []
        return check_loan_group("loans.mortgage", "mortgage", exps, rows, "discount", as_of, coverage, gaps)
    checks.append(_safe("loans.mortgage", "loan_payment", mortgage))

    def discount_loans():
        exps = [(n, a, d, (lambda r, acct=acct: acct[-11:] in (r.get("description") or "")))
                for n, a, d, acct in discount_loan_expectations(ds.raw("discount-mortgage", "onlineLoans_loansQuery.json"))]
        return check_loan_group("loans.discount", "Discount consumer", exps, rows, "discount", as_of, coverage, gaps)
    checks.append(_safe("loans.discount", "loan_payment", discount_loans))

    def leumi_loans():
        exps = []
        for n, a, d in leumi_loan_expectations(ds.raw("leumi", "loans.json")):
            exps.append((n, a, d, lambda r, a=a: any(p in (r.get("description") or "") for p in ("פרעון", "פירעון"))
                         and abs(abs(r["amount"]) - a) <= max(LOAN_AMOUNT_TOL, LOAN_AMOUNT_WARN * a)))
        return check_loan_group("loans.leumi", "Leumi", exps, rows, "leumi", as_of, coverage, gaps)
    checks.append(_safe("loans.leumi", "loan_payment", leumi_loans))

    # 7. salary (bank-only ledger, deduped the way digest.py does)
    checks.append(_safe("salary", "salary", lambda: check_salary(
        digest.consolidate_transactions([dict(r) for r in rows]), as_of, coverage, gaps)))

    counts = Counter(c["status"] for c in checks)
    return {"generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "as_of": as_of.isoformat(),
            "summary": {s: counts.get(s, 0) for s in STATUSES},
            "checks": checks}


# --- Output -----------------------------------------------------------------

def _clean(obj):
    """JSON-safe copy: drop internal keys, stringify dates."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def _fmt_detail(d):
    bits = [d.get("date"), d.get("source"), d.get("description")]
    amt = d.get("amount")
    if amt is not None:
        bits.append(f"₪{amt:,.2f}")
    line = " · ".join(str(b) for b in bits if b not in (None, ""))
    return f"{line} — {d['reason']}" if d.get("reason") else line


def write_markdown(report, path):
    s = report["summary"]
    icon = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}
    md = [f"# Data validation — {report['generated_at'][:10]}\n",
          f"*`python3 data/validate.py` · as of {report['as_of']} · direct bank and card sources only "
          "(no RiseUp).*\n",
          f"**{s['pass']} pass · {s['warn']} warn · {s['fail']} fail · {s['skip']} skip**\n",
          "| Status | Check | Summary |", "|---|---|---|"]
    for c in report["checks"]:
        md.append(f"| {icon[c['status']]} | `{c['id']}` | {c['summary']} |")
    for c in report["checks"]:
        if c["status"] in ("warn", "fail") and c["details"]:
            md.append(f"\n## {c['id']} — {c['status']}\n")
            shown = [d for d in c["details"] if d.get("level") != "info"][:12]
            md += [f"- {_fmt_detail(d)}" for d in shown]
            if len(c["details"]) > len(shown):
                md.append(f"- … {len(c['details']) - len(shown)} more in validation.json")
    Path(path).write_text("\n".join(md) + "\n", encoding="utf-8")


def write_report(report, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "validation.json").write_text(
        json.dumps(_clean(report), ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(_clean(report), out / "validation.md")


# --- Actions for the app's "לטיפול" list ---------------------------------------

ACTION_TITLES = {
    "dump": "סנכרון {id} נראה שגוי",
    "card_bill": "חיוב אשראי לא תואם לחיוב בבנק",
    "card_statement": "עסקאות הכרטיס לא מסתכמות לדף החשבון",
    "balance": "פער בנתוני חשבון הבנק",
    "internal_transfer": "העברה בין החשבונות ללא צד שני",
    "loan_payment": "תשלום הלוואה לא תואם לחיוב בבנק",
    "salary": "המשכורת לא נמצאה",
}


def validation_actions(report, include_warn=False):
    """Action items (the shape data/actions.py emits) for failing checks.

    Ids are stable for the report's month so a per-device dismiss sticks until the
    situation changes. Dump and salary failures are critical; the rest are high.
    Warnings are low-severity and only included on request.
    """
    month = str(report.get("generated_at", ""))[:7]
    actions = []
    for c in report.get("checks", []):
        if c["status"] == "fail" or (include_warn and c["status"] == "warn"):
            fail = c["status"] == "fail"
            severity = ("critical" if c["type"] in ("dump", "salary") else "high") if fail else "low"
            title = ACTION_TITLES.get(c["type"], "בדיקת נתונים נכשלה").format(id=c["id"].split(".")[-1])
            amounts = [abs(d["amount"]) for d in c.get("details", [])
                       if d.get("level", "fail") == ("fail" if fail else "warn") and d.get("amount")]
            actions.append({
                "id": f"validation:{c['id']}:{month}", "severity": severity, "title": title,
                "detail": c["summary"], "cta": {"label": "לסנכרונים", "to": "/syncs"},
                "amount": round(sum(amounts), 2) if amounts else None,
            })
    return actions


# --- CLI --------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Validate the scraped data.")
    ap.add_argument("command", nargs="?", choices=["all", "dump"], default="all")
    ap.add_argument("source", nargs="?", help="source id for `dump`")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--as-of", help="YYYY-MM-DD (default today)")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any check fails")
    args = ap.parse_args(argv)
    as_of = _d(args.as_of) if args.as_of else date.today()

    if args.command == "dump":
        if not args.source:
            ap.error("dump needs a source, e.g. `dump discount`")
        if args.source not in SOURCE_SPECS:
            print(f"unknown source {args.source!r}; known: {', '.join(SOURCE_SPECS)}", file=sys.stderr)
            return 2
        res = check_dump(args.source, args.data_dir, as_of)
        print(("REJECT " if res["status"] == "fail" else "OK     ") + res["summary"])
        for d in res["details"]:
            print(f"  [{d['level']}] {d['reason']}")
        return 1 if res["status"] == "fail" else 0

    report = run_all(args.data_dir, as_of)
    write_report(report, args.out_dir)
    s = report["summary"]
    print(f"validation: {s['pass']} pass, {s['warn']} warn, {s['fail']} fail, {s['skip']} skip "
          f"-> {Path(args.out_dir) / 'validation.json'}")
    for c in report["checks"]:
        if c["status"] in ("warn", "fail"):
            print(f"  {c['status'].upper():4} {c['id']}: {c['summary']}")
    return 1 if args.strict and s["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
