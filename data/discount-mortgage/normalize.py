#!/usr/bin/env python3
"""Normalize Discount loan dumps -> discount-mortgage/normalized/*.json

Reads:
    raw/mortgage_details.json        -> housing-mortgage tracks (מסלולים)
    raw/onlineLoans_loansQuery.json  -> other consumer loans (if present)

Emits a single loans.json with one record per loan/track.

Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/discount-mortgage
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "discount-mortgage"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def load(name):
    return json.load(open(RAW / name, encoding="utf-8"))


def normalize_loan(ln, category):
    return {
        "lender": "Bank Discount",
        "loan_id": ln.get("LoanAccount"),
        "name": ln.get("LoanName"),
        "category": category,                 # "mortgage" | "consumer"
        "original_amount": ln.get("LoanAmount"),
        "balance": round(ln.get("TotalLoanBalance", ln.get("LoanDebtBalance", 0)), 2),
        "rate_pct": ln.get("TotalInterestRate"),
        "rate_type": "fixed" if str(ln.get("InterestTypeCode")) == "1" else "variable",
        "index_linked": str(ln.get("LinkageType", "0")) != "0",
        "payments_remaining": int(ln.get("NumOfPaymentsRemained", 0)),
        "payments_total": int(ln.get("NumOfPayments", 0)),
        "monthly_payment": round(ln.get("NextPayment", 0), 2),
        "final_date": ln.get("LastPaymentDate"),
        "currency": "ILS",
    }


records = []

# housing mortgage tracks
m = load("mortgage_details.json")
for entry in m["MortgagesDetails"]["MortgagesBlock"]["MortgageEntry"]:
    for ln in entry["MortgageDetailsBlock"]["LoanEntry"]:
        records.append(normalize_loan(ln, "mortgage"))

# other consumer loans (optional file)
try:
    lq = load("onlineLoans_loansQuery.json")
    for ln in lq["LoansQuery"]["LoanDetailsBlock"]["LoanEntry"]:
        records.append(normalize_loan(ln, "consumer"))
except FileNotFoundError:
    pass

path = OUT / "loans.json"
path.write_text(json.dumps(
    {"source": SOURCE, "entity": "loans", "generated_at": NOW, "records": records},
    ensure_ascii=False, indent=2))
print(f"  {SOURCE}/{path.name}: {len(records)} records")
