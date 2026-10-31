"""Real-case style: rows mirror actual ledger decisions (own transfers and card bills are never spending)."""
from assistant import agent, tools

LEDGER = [
    {"date": "2026-10-03", "amount": -120.0, "category": "אוכל בחוץ", "description": "וולט"},
    {"date": "2026-10-09", "amount": -80.0, "category": "אוכל בחוץ", "description": "קפה"},
    {"date": "2026-10-10", "amount": -5000.0, "category": "העברות", "description": "ישראכרט", "card_bill_payment": 1},
    {"date": "2026-10-11", "amount": -1000.0, "category": "חיסכון", "description": "הפקדה", "savings": 1},
    {"date": "2026-10-12", "amount": 9000.0, "category": "משכורת", "description": "שכר", "is_income": True},
    {"date": "2026-09-30", "amount": -50.0, "category": "תחבורה", "description": "דלק"},
]


def test_card_bill_and_savings_are_not_spending():
    assert tools.spending_by_category("2026-10", LEDGER) == [{"category": "אוכל בחוץ", "total": 200.0}]


def test_monthly_totals_split_spent_and_income():
    assert tools.monthly_totals(2, LEDGER) == [
        {"month": "2026-09", "spent": 50.0, "income": 0.0},
        {"month": "2026-10", "spent": 200.0, "income": 9000.0},
    ]


def test_search_is_newest_first_and_month_filtered():
    found = tools.search_transactions("ק", "2026-10", ledger=LEDGER)
    assert [r["description"] for r in found] == ["הפקדה", "קפה"]
    assert tools.search_transactions("דלק", "2026-10", ledger=LEDGER) == []


def test_unknown_tool_returns_error_not_exception():
    assert "error" in tools.call("nope", {})


def test_agent_runs_tool_then_answers(monkeypatch):
    monkeypatch.setattr(tools, "_ledger", lambda: LEDGER)
    script = iter([
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "1", "function": {"name": "spending_by_category", "arguments": '{"month": "2026-10"}'}}]},
        {"role": "assistant", "content": "<think>hm</think>אוכל בחוץ: ₪200"},
    ])
    answer, messages = agent.ask("כמה הוצאתי על אוכל?", chat=lambda m, tools=None: next(script))
    assert answer == "אוכל בחוץ: ₪200"
    assert "200.0" in messages[-2]["content"]
