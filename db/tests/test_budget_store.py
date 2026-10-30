"""Budget lines (db/budget_store.py) against the throwaway test database."""
import json

import pytest

import budget_store


def test_replace_upserts_changed_lines_and_deletes_unset_ones(conn):
    assert budget_store.replace(conn, {"אוכל בחוץ": 250.0, "תחבורה": 120.5}) == {"אוכל בחוץ": 250.0, "תחבורה": 120.5}
    assert budget_store.replace(conn, {"תחבורה": 130.0, "עציצים": 700.0}) == {"תחבורה": 130.0, "עציצים": 700.0}
    assert budget_store.all_lines(conn) == {"תחבורה": 130.0, "עציצים": 700.0}


def test_negative_line_is_rejected_before_anything_is_written(conn):
    budget_store.replace(conn, {"אוכל בחוץ": 250.0})
    with pytest.raises(ValueError):
        budget_store.replace(conn, {"אוכל בחוץ": 1.0, "תחבורה": -5.0})
    assert budget_store.all_lines(conn) == {"אוכל בחוץ": 250.0}


def test_import_json_keeps_lines_already_in_the_table(conn, tmp_path):
    f = tmp_path / "budgets.json"
    f.write_text(json.dumps({"אוכל בחוץ": 1500, "תיירות": 1000, "junk": "x"}), encoding="utf-8")
    budget_store.replace(conn, {"אוכל בחוץ": 250.0})
    assert budget_store.import_json(conn, f) == 1
    assert budget_store.all_lines(conn) == {"אוכל בחוץ": 250.0, "תיירות": 1000.0}
