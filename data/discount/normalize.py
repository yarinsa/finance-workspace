#!/usr/bin/env python3
"""Normalize Discount checking dumps -> discount/normalized/*.json

Reads every raw/fetch-transactions_*.json, dedupes transactions across pulls by
(account_id, identifier), and emits:
    accounts.json      -> per-account current balance
    transactions.json  -> flattened, deduped transaction list
    savings.json        -> bank deposits (פיקדונות), from deposits_depositsDetails.json

Deposits are an ASSET, not spending: no `transactions` entity is emitted for
them, matching the harel savings producer. Unlike Harel's pension/study funds
(illiquid, locked for years), a Discount נזיל deposit can be exited daily — so
each record carries `liquid: true/false` (kind-derived: "נזיל" in the product
name => liquid, anything else conservatively marked illiquid) so digest.py can
tell the two apart instead of lumping locked and available money into one
number.

Common envelope: {"source", "entity", "generated_at", "records": [...]}
Self-contained; safe to re-run after each scrape.
"""
import json, datetime, glob
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/discount
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "discount"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def emit(entity, records):
    path = OUT / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": SOURCE, "entity": entity, "generated_at": NOW, "records": records},
        ensure_ascii=False, indent=2))
    print(f"  {SOURCE}/{path.name}: {len(records)} records")


accounts = {}          # account_id -> latest balance record
txns = {}              # (account_id, identifier) -> txn record

# Authoritative current balance comes from the CDP scraper's infoAndBalance.json
# (AccountBalance field). The legacy fetch-transactions_*.json files carry a stale
# `balance` baked in at MCP-scrape time, so they must NOT drive the balance — they
# are kept only as an extra transaction source.
info_fp = RAW / "infoAndBalance.json"
if info_fp.exists():
    info = json.load(open(info_fp, encoding="utf-8")).get("AccountInfoAndBalance", {})
    aid = info.get("HandlingBranchID", "discount")
    accounts[aid] = {
        "institution": "discount",
        "account_id": aid,
        "kind": "checking",
        "balance": round(info.get("AccountBalance", 0), 2),
        "available_balance": round(info.get("AccountAvailableBalance", 0), 2),
        "overdraft_limit": round(info.get("AccountLimit", 0), 2),
        "currency": "ILS",
    }

# If infoAndBalance.json gave us the authoritative account, the legacy dumps
# must not introduce phantom accounts with their stale balances — they use a
# different account_id (full number vs branch id), so we'd otherwise double-count.
have_authoritative = bool(accounts)

for fp in sorted(glob.glob(str(RAW / "fetch-transactions_*.json"))):
    data = json.load(open(fp, encoding="utf-8"))
    for acc in data.get("accounts", []):
        aid = acc["accountNumber"]
        # Seed an account from legacy dumps only when we have no authoritative
        # balance at all (old MCP-only setups). Otherwise use them for txns only.
        if not have_authoritative and aid not in accounts:
            accounts[aid] = {
                "institution": "discount",
                "account_id": aid,
                "kind": "checking",
                "balance": round(acc.get("balance", 0), 2),
                "currency": "ILS",
            }
        for t in acc.get("txns", []):
            key = (aid, t.get("identifier"))
            txns[key] = {
                "account_id": aid,
                "date": (t.get("date") or "")[:10],
                "processed_date": (t.get("processedDate") or "")[:10],
                "amount": round(t.get("chargedAmount", t.get("originalAmount", 0)), 2),
                "currency": t.get("originalCurrency", "ILS"),
                "description": t.get("description"),
                "status": t.get("status"),
            }

emit("accounts", list(accounts.values()))
emit("transactions", sorted(txns.values(), key=lambda r: r["date"]))


# ---- savings (bank deposits / פיקדונות) ----
# Institutions vary in shape: personal Discount returns real deposit data;
# discount-business returns {"Error": {...}} when there are no active deposits
# ("לא נמצאו הפקדות פעילות") — that must normalize to zero records, not a crash
# and not a phantom record.
def normalize_deposits(fp, institution):
    if not fp.exists() or fp.stat().st_size == 0:
        return []
    data = json.load(open(fp, encoding="utf-8"))
    if "Error" in data:
        return []  # e.g. RET011039 "no active deposits" — a valid empty state

    details = data.get("DepositsDetails", {})
    records = []
    for acc in (details.get("DepositAccountBlock") or {}).get("DepositAccountEntry", []):
        label = acc.get("ProductShortName") or acc.get("ProductLongName") or "deposit"
        balance = acc.get("TotalDepositsCurrentValue")
        if balance is None:
            continue
        records.append({
            "institution": institution,
            "account_id": acc.get("TermNewAccountNumber") or acc.get("AccountNumber"),
            "kind": "bank_deposit",
            "label": label,
            "liquid": "נזיל" in label,  # daily-exit deposit vs a locked term deposit
            "balance": round(balance, 2),
            "currency": acc.get("CurrencyCode", "ILS"),
            "maturity_date": None,
            "management_fee": None,
            "yield_ytd": None,
        })
    return records


emit("savings", normalize_deposits(RAW / "deposits_depositsDetails.json", "discount"))
