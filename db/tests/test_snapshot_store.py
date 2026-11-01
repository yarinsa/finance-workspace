"""The position's machine tables (accounts, credit_cards, loans, savings_holdings, source_dumps,
digest_runs): what the digest stores, and that the totals over the stored rows are the ones
snapshot.json carries.

The made-up rows are shaped like the reconciled snapshot; the parity case uses this checkout's
real data/digested/snapshot.json when it is present.
"""
import json
from pathlib import Path

import pytest

import ledger
import snapshot_store
from finance.views import snapshot as views

POSITION = {
    "bank_accounts": [{"institution": "leumi", "account_id": "1", "kind": "checking", "balance": 1234.56,
                       "currency": "ILS", "available_balance": 5000.0, "overdraft_limit": 4000.0}],
    "credit_cards": [{"issuer": "cal", "last4": "1111", "name": "כאל", "owed": 812.3,
                      "next_charge_date": "2026-11-10", "currency": "ILS"}],
    "loans": [{"lender": "discount", "loan_id": None, "name": "משכנתא", "category": "mortgage", "balance": 500000.0,
               "rate_pct": 4.1, "monthly_payment": 2500.0, "final_date": "2053-08-10", "currency": "ILS"},
              {"lender": "leumi", "loan_id": "77", "name": "הלוואה", "category": "consumer", "balance": 20000.0,
               "monthly_payment": 900.0, "currency": "ILS"}],
    "savings": [{"institution": "harel", "kind": "pension", "balance": 100000.0, "topic_id": "123", "label": "פנסיה",
                 "currency": "ILS"},
                {"institution": "discount", "kind": "deposit", "balance": 3000.0, "label": "נזיל", "liquid": True}],
}
DUMPS = [{"source": "cal", "last_synced": "2026-11-01T06:21:30+02:00", "raw_files": 4,
          "entities": {"credit_cards": 2, "transactions": 40}, "latest_txn_date": "2026-10-30"},
         {"source": "harel", "last_synced": "2026-10-20T08:00:00+03:00", "raw_files": 2,
          "entities": {"savings": 1}, "latest_txn_date": None}]
RUN = {"started_at": "2026-11-01T07:00:00+02:00", "normalized": True}


def test_load_stores_the_position_and_totals_match(conn):
    ledger.load(conn, [], POSITION, DUMPS, RUN)
    rows = snapshot_store.position(conn)
    assert [r.holding_id for r in rows["savings"]] == ["discount:נזיל", "harel:123"]
    assert [l.name for l in rows["loans"]] == ["משכנתא", "הלוואה"]   # digest order kept
    assert str(rows["credit_cards"][0].next_charge_date) == "2026-11-10"
    assert snapshot_store.totals(rows) == views.totals(POSITION)
    assert snapshot_store.as_of(conn) is not None


def test_dumps_round_trip(conn):
    ledger.load(conn, [], dumps=DUMPS)
    out = snapshot_store.dumps(conn)
    dump, counts = out["cal"]
    assert (dump.raw_files, str(dump.latest_txn_date), counts) == (4, "2026-10-30", {"credit_cards": 2, "transactions": 40})
    assert out["harel"][1] == {"savings": 1} and out["harel"][0].latest_txn_date is None


def test_a_later_digest_replaces_the_position(conn):
    ledger.load(conn, [], POSITION, DUMPS, RUN)
    smaller = {**POSITION, "loans": POSITION["loans"][:1], "savings": []}
    ledger.load(conn, [], smaller, DUMPS[:1], RUN)
    rows = snapshot_store.position(conn)
    assert len(rows["loans"]) == 1 and rows["savings"] == []
    assert list(snapshot_store.dumps(conn)) == ["cal"]
    assert conn.execute("SELECT count(*) FROM digest_runs").fetchone() == (2,)


def test_a_bare_ledger_leaves_the_position_alone(conn):
    """`ledger.py sync` still takes a plain ledger list; it then touches only scraped_transactions."""
    ledger.load(conn, [], POSITION)
    ledger.load(conn, [])
    assert len(snapshot_store.position(conn)["bank_accounts"]) == 1
    assert snapshot_store.as_of(conn) is None


REAL = Path(__file__).resolve().parents[2] / "data" / "digested" / "snapshot.json"


@pytest.mark.skipif(not REAL.exists(), reason="no digested snapshot in this checkout")
def test_real_snapshot_totals_survive_the_tables(conn):
    """Parity (D7): the real position, stored and read back, sums to snapshot.json's totals."""
    snap = json.loads(REAL.read_text())
    ledger.load(conn, [], {k: snap[k] for k in ("bank_accounts", "credit_cards", "loans", "savings")},
                snap["syncs"], RUN)
    got = snapshot_store.totals(snapshot_store.position(conn), snap["assets"])
    want = {k: v for k, v in snap["totals"].items() if k != "detected_monthly_salary"}
    assert {k: v for k, v in got.items() if k != "detected_monthly_salary"} == want
    assert len(snapshot_store.dumps(conn)) == len(snap["syncs"])
