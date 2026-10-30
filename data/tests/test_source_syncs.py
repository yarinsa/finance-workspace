"""Tests for digest.source_syncs — the per-source freshness behind the Syncs page."""
import json, os

import digest


def _source(root, name, raw_mtime, txns=None):
    raw = root / name / "raw"
    raw.mkdir(parents=True)
    f = raw / "dump.json"
    f.write_text("{}")
    os.utime(f, (raw_mtime, raw_mtime))
    if txns is not None:
        norm = root / name / "normalized"
        norm.mkdir()
        (norm / "transactions.json").write_text(json.dumps(
            {"source": name, "entity": "transactions", "records": txns}))


def test_last_synced_is_raw_mtime_not_normalize_time(tmp_path):
    # discount-business was last scraped 2026-10-09 while everything else ran on
    # 10-15; a later digest re-normalizes it, which must not make it look fresh.
    _source(tmp_path, "discount-business", 1791579540,  # 2026-10-09 23:59 IDT
            txns=[{"date": "2026-10-08", "amount": -50}, {"date": "2026-10-09", "amount": -12}])
    [row] = digest.source_syncs(tmp_path)
    assert row["source"] == "discount-business"
    assert row["last_synced"].startswith("2026-10-09")
    assert row["latest_txn_date"] == "2026-10-09"
    assert row["entities"] == {"transactions": 2}


def test_savings_source_has_no_txn_date_and_empty_raw_is_skipped(tmp_path):
    _source(tmp_path, "harel", 1791957840)
    (tmp_path / "unscraped" / "raw").mkdir(parents=True)
    rows = digest.source_syncs(tmp_path)
    assert [r["source"] for r in rows] == ["harel"]
    assert rows[0]["latest_txn_date"] is None


def test_rows_carry_the_sources_manifest(tmp_path):
    _source(tmp_path, "harel", 1791957840)
    [row] = digest.source_syncs(tmp_path)
    assert row["label"] == "הראל" and row["account_types"] == ["pension", "study_fund"]
    assert row["capabilities"] == ["savings"]
