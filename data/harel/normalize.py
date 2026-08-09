#!/usr/bin/env python3
"""Normalize Harel raw dumps -> harel/normalized/*.json

Common envelope written for every entity:
    {"source", "entity", "generated_at", "records": [...]}

Entities emitted: savings.

Harel holds pension (קרן פנסיה) and study funds (קרן השתלמות). These are
long-term SAVINGS ASSETS, not cashflow: deliberately no `transactions` entity is
emitted, so contributions never enter the spending ledger and skew `total_spent`.
The bank-side debit for a deposit is already captured by the bank source.

Self-contained; safe to re-run after each scrape.
"""
import json, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent          # .../data/harel
RAW = HERE / "raw"
OUT = HERE / "normalized"
OUT.mkdir(exist_ok=True)
SOURCE = "harel"
NOW = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

# online-data.json is keyed by Harel's topicId. The ids are stable per product
# family; customer-products.json carries the matching topicName/xTopicName.
TOPIC_KIND = {
    "70": "pension",      # קרנות פנסיה
    "62": "study_fund",   # קרן השתלמות (xtopicId of the גמל/השתלמות topic)
    "60": "study_fund",   # גמל topicId, same family
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
    path = OUT / f"{entity}.json"
    path.write_text(json.dumps(
        {"source": SOURCE, "entity": entity, "generated_at": NOW, "records": records},
        ensure_ascii=False, indent=2))
    print(f"  {SOURCE}/{path.name}: {len(records)} records")


def parse_amount(v):
    """Harel returns balances as thousands-separated strings ("338,361")."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    cleaned = str(v).replace(",", "").replace("₪", "").strip()
    try:
        return round(float(cleaned), 2)
    except ValueError:
        return None


def topic_index():
    """topicId/xtopicId -> product metadata from customer-products.json."""
    products = load("customer-products.json", {}) or {}
    index = {}
    for topics in (products.get("topicsList") or {}).values():
        for t in topics:
            meta = {
                "name": (t.get("xTopicName") or t.get("topicName") or "").strip(),
                "section": (t.get("sectionName") or "").strip(),
                "policies_count": t.get("policiesCount"),
            }
            for key in (t.get("topicId"), t.get("xtopicId")):
                if key is not None:
                    index[str(key)] = meta
    return index


# ---- savings (pension + study funds) ----
balances = load("online-data.json", {}) or {}
topics = topic_index()

savings = []
for topic_id, raw_balance in balances.items():
    balance = parse_amount(raw_balance)
    if balance is None:
        continue
    meta = topics.get(str(topic_id), {})
    savings.append({
        "institution": "harel",
        "topic_id": str(topic_id),
        "kind": TOPIC_KIND.get(str(topic_id), "savings"),
        "label": meta.get("name") or f"harel-{topic_id}",
        "section": meta.get("section"),
        "policies_count": meta.get("policies_count"),
        "balance": balance,
        "currency": "ILS",
        # Per-policy detail (מסלול / דמי ניהול / תשואה) lives behind Harel's legacy
        # SharePoint report iframe, not this JSON API — not captured yet.
        "management_fee": None,
        "yield_ytd": None,
    })

savings.sort(key=lambda r: -r["balance"])
emit("savings", savings)
