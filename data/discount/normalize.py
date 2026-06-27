#!/usr/bin/env python3
"""Normalize Discount checking dumps -> discount/normalized/*.json

Reads every raw/fetch-transactions_*.json, dedupes transactions across pulls by
(account_id, identifier), and emits:
    accounts.json      -> per-account current balance
    transactions.json  -> flattened, deduped transaction list

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
