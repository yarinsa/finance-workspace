#!/usr/bin/env python3
"""Normalize Bank Leumi dumps -> leumi/normalized/*.json

The Leumi gateway (Broker.svc) wraps every payload as
    {"ProcessRequestResult": 0, "jsonResp": {...}}
Reads:
    raw/accounts.json      -> account list (number, type)
    raw/summary.json       -> per-type totals (CHECKING balance, LOAN balance)
    raw/transactions.json  -> current-account history
    raw/loans.json         -> per-loan detail (rate, installments, dates),
                               scraped by dump-loans.sh from the loan-summary /
                               loan-activity pages

Emits:
    accounts.json      -> the checking account (balance from summary)
    loans.json         -> one record per loan, from raw/loans.json (falls
                           back to a single aggregate from the summary if
                           raw/loans.json is absent)
    transactions.json  -> flattened, deduped current-account transactions

Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/leumi
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "leumi"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load(name):
    """Load a raw Leumi file and unwrap the jsonResp envelope."""
    fp = RAW / name
    if not fp.exists():
        return None
    data = json.load(open(fp, encoding="utf-8"))
    if isinstance(data, dict) and "jsonResp" in data:
        return data["jsonResp"]
    return data


def emit(entity, records):
    path = OUT / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": SOURCE, "entity": entity, "generated_at": NOW, "records": records},
        ensure_ascii=False, indent=2))
    print(f"  {SOURCE}/{path.name}: {len(records)} records")


def iso(date_so):
    """'10/06/2026' -> '2026-06-10'."""
    try:
        d, m, y = date_so.split("/")
        return f"{y}-{m}-{d}"
    except (AttributeError, ValueError):
        return None


def iso_ddmmyy(date_str):
    """'02/12/28' -> '2028-12-02'. Leumi's loan pages use 2-digit years."""
    try:
        d, m, y = date_str.split("/")
        yyyy = f"20{y}" if len(y) == 2 else y
        return f"{yyyy}-{m}-{d}"
    except (AttributeError, ValueError):
        return None


def money(s):
    """'45,436.45' -> 45436.45. Leumi money fields are comma-thousands strings."""
    if s is None:
        return None
    try:
        return round(float(str(s).replace(",", "").strip()), 2)
    except ValueError:
        return None


def pct(s):
    """'8%' -> 8.0."""
    if s is None:
        return None
    try:
        return float(str(s).replace("%", "").strip())
    except ValueError:
        return None


def loan_id_from_general_info(gi):
    """Prefer the numeric 'מספר הלוואה' field; it's stable and unambiguous."""
    return gi.get("מספר הלוואה")


# ---- per-type totals from the summary ----
summary = load("summary.json") or {}
totals = {t["accountType"]: t["totalPerAccountType"]
          for t in summary.get("TotalPerTypeItems", [])}

# ---- accounts (the checking account, balance taken from the summary) ----
accounts = []
acc_data = load("accounts.json") or {}
checking_id = None
for a in acc_data.get("AccountsItems", []):
    if a.get("Type") == "CHECKING":
        checking_id = a.get("MaskedNumber")
        accounts.append({
            "institution": "leumi",
            "account_id": checking_id,
            "label": a.get("DisplayName") or checking_id,
            "kind": "checking",
            "balance": round(totals.get("CHECKING", 0), 2),
            "currency": "ILS",
        })
emit("accounts", accounts)

# ---- loans ----
# Prefer per-loan detail scraped into raw/loans.json (loan-summary +
# loan-activity pages carry rate/installments per loan). Fall back to a
# single aggregate from the summary totals if that file is absent, so the
# pipeline never crashes on a partial scrape.
loans = []
loans_raw_path = RAW / "loans.json"
if loans_raw_path.exists():
    loans_data = json.load(open(loans_raw_path, encoding="utf-8"))
    for ln in loans_data.get("loans", []):
        gi = ln.get("generalInfo", {})
        bal = ln.get("balances", {})
        interest = ln.get("interest", {})
        dates = ln.get("dates", {})

        remaining_raw = bal.get("תשלומים שנותרו")
        try:
            remaining = int(remaining_raw)
        except (TypeError, ValueError):
            remaining = 0
        installment_count = ln.get("installmentCount") or 0
        payments_total = remaining + 0 if not installment_count else max(installment_count, remaining)

        loans.append({
            "lender": "Bank Leumi",
            "loan_id": loan_id_from_general_info(gi),
            "name": (ln.get("loanLabel") or "").strip(),
            "category": "consumer",
            "original_amount": money(bal.get("סכום הלוואה מקורי")),
            "balance": money(bal.get("יתרת קרן")),
            "rate_pct": pct(interest.get("שיעור ריבית")),
            "rate_type": "fixed" if "קבועה" in gi.get("סוג", "") else "variable",
            "index_linked": interest.get("סוג הצמדה") not in (None, "לא צמוד"),
            "payments_remaining": remaining,
            "payments_total": payments_total,
            "monthly_payment": money(bal.get("סכום התשלום הבא")) or 0,
            "final_date": iso_ddmmyy(dates.get("תאריך סיום")),
            "currency": "ILS",
        })

if not loans and totals.get("LOAN"):
    # No per-loan detail on disk yet (e.g. before the first loans.json scrape)
    # -- keep the old aggregate as a fallback so totals aren't silently zero.
    loans.append({
        "lender": "Bank Leumi",
        "loan_id": "leumi-loans",
        "name": "Leumi loans (aggregate)",
        "category": "consumer",
        "original_amount": None,
        "balance": round(abs(totals["LOAN"]), 2),
        "rate_pct": None,
        "rate_type": "variable",
        "index_linked": False,
        "payments_remaining": 0,
        "payments_total": 0,
        "monthly_payment": 0,
        "final_date": None,
        "currency": "ILS",
    })
emit("loans", loans)

# ---- transactions ----
txns = {}
tx = load("transactions.json") or {}
for t in tx.get("HistoryTransactionsItems", []):
    key = t.get("FITID") or (t.get("DateSO"), t.get("ReferenceNumberLong"), t.get("Amount"))
    txns[key] = {
        "account_id": checking_id,
        "date": iso(t.get("DateSO")),
        "processed_date": iso(t.get("EffectiveDateSO")),
        "amount": round(t.get("Amount", 0), 2),
        "currency": "ILS",
        "description": t.get("Description"),
        "balance_after": round(t.get("RunningBalance", 0), 2),
        "status": "completed",
    }
emit("transactions", sorted(txns.values(), key=lambda r: r["date"] or ""))
