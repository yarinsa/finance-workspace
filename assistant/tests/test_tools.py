"""Real-case style: rows mirror actual ledger decisions (own transfers and card bills are never spending)."""
from assistant import agent
from assistant.tools import Toolbox

ROWS = [
    {"date": "2026-10-03", "amount": -120.0, "category": "אוכל בחוץ", "description": "וולט"},
    {"date": "2026-10-09", "amount": -80.0, "category": "אוכל בחוץ", "description": "קפה"},
    {"date": "2026-10-10", "amount": -5000.0, "category": "העברות", "description": "ישראכרט", "card_bill_payment": 1},
    {"date": "2026-10-11", "amount": -1000.0, "category": "חיסכון", "description": "הפקדה", "savings": 1},
    {"date": "2026-10-12", "amount": 9000.0, "category": "משכורת", "description": "שכר", "is_income": True},
    {"date": "2026-09-30", "amount": -50.0, "category": "תחבורה", "description": "דלק"},
]


class FakeLedger:
    def __init__(self, rows=ROWS, snapshot=None):
        self._rows, self._snapshot = rows, snapshot

    def rows(self):
        return self._rows

    def snapshot(self):
        return self._snapshot


def box(**kw):
    return Toolbox(FakeLedger(**kw))


def test_card_bill_and_savings_are_not_spending():
    assert box().spending_by_category("2026-10") == [{"category": "אוכל בחוץ", "total": 200.0}]


def test_monthly_totals_split_spent_and_income():
    assert box().monthly_totals(2) == [
        {"month": "2026-09", "spent": 50.0, "income": 0.0},
        {"month": "2026-10", "spent": 200.0, "income": 9000.0},
    ]


def test_search_is_newest_first_and_month_filtered():
    found = box().search_transactions("ק", "2026-10")
    assert [r["description"] for r in found] == ["הפקדה", "קפה"]
    assert box().search_transactions("דלק", "2026-10") == []


def test_unknown_tool_returns_error_not_exception():
    assert "error" in box().call("nope", {})


def test_bad_month_comes_back_as_an_error_the_model_can_read():
    assert "YYYY-MM" in box().call("spending_by_category", {"month": "last october"})["error"]


def test_limits_are_capped():
    many = [{"date": "2026-10-01", "amount": -1.0, "description": "x"}] * 500
    assert len(box(rows=many).search_transactions("x", limit=10_000)) == 50


def test_snapshot_tool_is_only_offered_when_the_ledger_has_one():
    names = lambda b: [s["function"]["name"] for s in b.schemas()]  # noqa: E731
    assert "snapshot_totals" not in names(box())
    assert "snapshot_totals" in names(box(snapshot={"totals": {"net": 1}}))
    assert "error" in box().call("snapshot_totals", {})


def test_agent_runs_tool_then_answers():
    script = iter([
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "function": {"name": "spending_by_category", "arguments": '{"month": "2026-10"}'}}]},
        {"role": "assistant", "content": "<think>hm</think>אוכל בחוץ: ₪200"},
    ])
    answer, messages = agent.ask("כמה הוצאתי על אוכל?", box(), chat=lambda m, tools=None: next(script))
    assert answer == "אוכל בחוץ: ₪200"
    assert "200.0" in messages[-2]["content"]
