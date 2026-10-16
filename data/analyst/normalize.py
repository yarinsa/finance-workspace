#!/usr/bin/env python3
"""Normalize Analyst (אנליסט) raw dumps -> analyst/normalized/*.json

Common envelope written for every entity:
    {"source", "entity", "generated_at", "records": [...]}

Entities emitted: savings.

Analyst holds an old self-employed קופת גמל. Like Harel and More it is a
long-term SAVINGS ASSET, not cashflow: deliberately no `transactions` entity.

Raw input: raw/sum-financial-data.json — the GetCustomerSumFinancialData
response: data.sumFinancialData.products[] (one per kupa type) each with
accounts[]. One record is emitted per account with a non-zero balance.

Self-contained; safe to re-run after each scrape.
"""
import json, datetime
from finance.models import write_envelope
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/analyst
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "analyst"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
TODAY = datetime.date.today().isoformat()

# Analyst's kupaTypeId codes (only 1 seen so far; unknown ids fall back to "savings").
KUPA_KIND = {
    1: "provident_fund",    # קופת גמל
    2: "study_fund",        # קרן השתלמות
}


def load(name, default=None):
    path = RAW / name
    if not path.exists() or path.stat().st_size == 0:
        return default
    try:
        return json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def emit(entity, records):
    """Validate through finance.models and write the common envelope."""
    write_envelope(OUT, SOURCE, entity, NOW, records)


def iso(ddmmyyyy):
    """'23/11/2057' -> '2057-11-23' (None if missing/unparseable)."""
    try:
        return datetime.datetime.strptime(ddmmyyyy, "%d/%m/%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


dump = load("sum-financial-data.json", {}) or {}
products = ((dump.get("data") or {}).get("sumFinancialData") or {}).get("products") or []

savings = []
for product in products:
    kind = KUPA_KIND.get(product.get("kupaTypeId"), "savings")
    section = (product.get("kupaTypeName") or kind).strip()
    for a in product.get("accounts") or []:
        balance = round(float(a.get("sumAccount") or 0), 2)
        if balance == 0:
            continue
        liq = iso(a.get("nezilutDate"))
        state = (a.get("state") or "").strip()
        savings.append({
            "institution": "analyst",
            "topic_id": a.get("accountMainForShow") or a.get("kupaNum"),
            "kind": kind,
            "label": f"Analyst {section} {a.get('kupaNum')} ({state})".replace(" ()", ""),
            "section": section,
            "policies_count": None,
            "balance": balance,
            "currency": "ILS",
            "work_state": state or None,
            "liquidity_date": liq,
            # isNazil ("כן"/"לא") is Analyst's own liquidity flag; fall back to the date.
            "liquid": a.get("isNazil") == "כן" or bool(liq and liq <= TODAY),
            "as_of": iso(a.get("revaluationDate") or product.get("revaluationDate")),
            "management_fee": None,
            "yield_ytd": None,
        })

savings.sort(key=lambda r: -r["balance"])
emit("savings", savings)
