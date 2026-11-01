"""The hand-kept inputs that were side files (offset rules, mortgage schedule, loan freezes,
the budget cycle's start day):
stored, read back in the file's own shape, and imported from the real files when present."""
import json
from pathlib import Path

import pytest

import input_store

RULES = [{"payer": "בללי אסף", "against": ["לעיין ניהול", "לעיין ניהול נכ"], "note": "roommate's share"},
         {"payer": "חבר", "against": ["מסעדה"]}]
PERIODS = [{"from": "2026-09", "to": "2026-12", "payment": 5717}, {"from": "2027-01", "to": "2053-08", "payment": 8190.5}]
FREEZE = {"0001-123": {"frozen_payment": 1707.54, "resume_month": "2026-07", "resume_payment": 2950.0, "note": "6m full"}}


def test_offset_rules_round_trip(conn):
    assert input_store.set_offset_rules(conn, RULES) == 2
    assert input_store.offset_rules(conn) == RULES      # order kept, no note -> no key
    input_store.set_offset_rules(conn, RULES[:1])
    assert input_store.offset_rules(conn) == RULES[:1]


def test_mortgage_schedule_round_trip(conn):
    input_store.set_mortgage_schedule(conn, PERIODS, "PDF 2026-09-06")
    assert input_store.mortgage_schedule(conn) == PERIODS    # 5717 == 5717.0
    assert conn.execute("SELECT DISTINCT source FROM mortgage_schedule_periods").fetchall() == [("PDF 2026-09-06",)]


def test_a_freeze_is_recorded_then_cleared(conn):
    input_store.set_loan_freezes(conn, FREEZE)
    assert input_store.loan_freezes(conn) == FREEZE
    input_store.set_loan_freezes(conn, {})
    assert input_store.loan_freezes(conn) == {}


def test_the_cycle_start_day_is_unset_then_set_then_changed(conn):
    assert input_store.cycle_start_day(conn) is None
    input_store.set_cycle_start_day(conn, 10)
    input_store.set_cycle_start_day(conn, 1)
    assert input_store.cycle_start_day(conn) == 1
    assert conn.execute("SELECT count(*) FROM household_settings").fetchone() == (1,)


def test_import_skips_a_missing_file(conn, tmp_path):
    assert input_store.import_file(conn, "freeze", tmp_path) is None


DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.mark.parametrize("which", ["rules", "schedule", "settings"])
def test_real_side_files_import_unchanged(conn, which):
    """The real files, imported, read back exactly as the pipeline read them (D7)."""
    path = DATA / input_store.FILES[which]
    if not path.exists():
        pytest.skip(f"no {path.name} in this checkout")
    doc = json.loads(path.read_text(encoding="utf-8"))
    input_store.import_file(conn, which, DATA)
    if which == "rules":
        assert input_store.offset_rules(conn) == doc
    elif which == "settings":
        assert input_store.cycle_start_day(conn) == int(doc["cashflowStartDay"])
    else:
        assert input_store.mortgage_schedule(conn) == doc["periods"]
