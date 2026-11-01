"""One household's figures: every view computed once from one set of inputs.

`Inputs` is everything the views read; `Household(inputs, today)` computes each view lazily,
at most once, so a consumer pays only for what it asks for. The pipeline builds `Inputs` from
the digested files (data/inputs.py); the API and the host jobs will build it from Postgres as
the migration moves each input into a table (docs/json-to-db-migration.md). The views never
read a file, a table or the clock themselves.
"""
from dataclasses import dataclass, field
from datetime import date
from functools import cached_property

from finance import offsets
from finance.views import (actions, bills, budgets, cashflow, forecast, goals, history, horizons,
                           months_view, projection, runway, spending)


@dataclass(frozen=True)
class Inputs:
    ledger: list[dict]                      # ledger rows, edits applied and offsets resolved
    snapshot: dict                          # the headline position (finance/views/snapshot.py)
    category_merges: dict[str, str] = field(default_factory=dict)
    budget: dict | None = None              # RiseUp's current budget doc (until phase 2b)
    cycle_start_day: int | None = None      # household_settings; None = the budget doc's
    budget_history: list[dict] = field(default_factory=list)
    budget_overrides: dict[str, float] = field(default_factory=dict)
    forecast_sources: forecast.Sources = field(default_factory=forecast.Sources)
    validation: dict | None = None          # data/validate.py's report
    horizons: list[dict] | None = None      # horizon rows; None = the built-in defaults
    goals: list[dict] | None = None         # goal rows; None = no database
    goal_store: dict = field(default_factory=dict)   # plan targets + goals, as goals.build reads them
    cash_accounts: list[dict] = field(default_factory=list)  # history.cash per checking account
    positions: list[dict] = field(default_factory=list)      # recorded daily positions


class Household:
    def __init__(self, inputs: Inputs, today: date):
        self.inputs = inputs
        self.today = today

    @property
    def ledger(self):
        """Real money: balances, runway and bills read this."""
        return self.inputs.ledger

    @property
    def snapshot(self):
        return self.inputs.snapshot

    @cached_property
    def transactions(self):
        """The ledger with paybacks netted against what they repay: spend and income figures."""
        return offsets.cashflow_view(self.ledger)

    @cached_property
    def months(self):
        return cashflow.aggregate_by_month(self.transactions)

    @cached_property
    def current_month(self):
        current = cashflow.pick_current_month(self.months, self.today)
        if current is None:
            raise ValueError("no transactions to build a cashflow from")
        return current

    @cached_property
    def forecast(self):
        """None without a RiseUp budget doc, as forecast.py then wrote nothing."""
        if not self.inputs.budget:
            return None
        return forecast.build_all(self.inputs.budget, {"transactions": self.ledger}, self.today,
                                  self.inputs.forecast_sources)

    @cached_property
    def projection(self):
        return projection.build(self.snapshot, self.today, forecast=self.forecast,
                                schedule=self.inputs.forecast_sources.schedule)

    @cached_property
    def runway(self):
        return runway.build_runway(self.ledger, self.snapshot["bank_accounts"],
                                   self.snapshot.get("savings", []), self.today)

    @cached_property
    def bills(self):
        return bills.build_bills(self.inputs.budget, self.ledger, self.today, self.inputs.cycle_start_day)

    @cached_property
    def budgets(self):
        expected = cashflow.expected_for_month(self.forecast, (self.inputs.budget or {}).get("budgetDate"))
        return budgets.build_budgets(
            self.inputs.budget, self.transactions, self.today, self.inputs.budget_overrides,
            ledger=self.ledger, merges=self.inputs.category_merges,
            expected_income=expected["income"] if expected else None, start_day=self.inputs.cycle_start_day)

    @cached_property
    def fixed_expenses(self):
        return cashflow.fixed_expenses(self.ledger, self.current_month)

    @cached_property
    def spending(self):
        return spending.build_spending(self.transactions, today=self.today)

    @cached_property
    def months_view(self):
        return months_view.build_months_view(self.transactions, self.forecast,
                                             self.inputs.budget_history, self.today)

    @cached_property
    def history(self):
        return history.build(self.snapshot, self.today, self.inputs.cash_accounts, self.inputs.positions)

    @cached_property
    def horizons(self):
        return horizons.build_horizons(self.transactions, meta=self.inputs.horizons, goals=self.inputs.goals)

    @cached_property
    def actions(self):
        return actions.build_actions(
            self.runway, self.bills, self.budgets, self.fixed_expenses,
            self.snapshot.get("syncs", []), self.today,
            actions.validation_actions(self.inputs.validation or {}))

    @cached_property
    def pace(self):
        return {**cashflow.build_pace(self.transactions, self.current_month, today=self.today),
                "expected": cashflow.expected_for_month(self.forecast, self.current_month)}

    @cached_property
    def charts(self):
        return cashflow.build_charts(self.months, self.current_month)

    @cached_property
    def metrics(self):
        return (cashflow.build_metrics(self.months[self.current_month], self.snapshot)
                + self.projection["metrics"])

    def cashflow_document(self, generated_at):
        """cashflow.json, key for key."""
        proj = self.projection
        return {
            "generated_at": generated_at,
            "currency": "ILS",
            "current_month": self.current_month,
            "note": (
                "Cashflow model (Phase 1: today + breakdowns). 'current_month' is the "
                "latest complete calendar month. Savings% is an estimate pending "
                "net-worth history. Forward projections not yet implemented."
            ),
            "metrics": self.metrics,
            "today": self.charts["today"],
            "pace": self.pace,
            "fixed_expenses": self.fixed_expenses,
            "charts": {
                **{k: v for k, v in self.charts.items() if k != "today"},
                "net_worth": proj["chart"],
            },
            "projection": {
                "config": proj["config"],
                "net_worth_today": proj["net_worth_today"],
                "net_worth_at_retirement": proj["net_worth_at_retirement"],
                "total_loan_balance_today": proj["total_loan_balance_today"],
                "loans_modeled": proj["loans_modeled"],
                "focal_points": proj["focal_points"],
            },
            "runway": self.runway,
            # How the money got here: cash (running balances), debt (amortization), and the
            # daily positions recorded in Postgres. Read by the home screen's lenses.
            "history": self.history,
            "bills": self.bills,
            "budgets": self.budgets,
            "spending": self.spending,
            "horizons": self.horizons,
            "months_view": self.months_view,
            "actions": self.actions,
            "months": [
                {"month": k, "income": v["income"], "expense": v["expense"], "net": v["net"],
                 "count": v["count"]}
                for k, v in self.months.items()
            ],
        }

    def goals_document(self, generated_at, cashflow_doc=None):
        """goals.json. It reads the cashflow model's projection and pace."""
        return goals.build(self.inputs.goal_store, self.snapshot,
                           cashflow_doc or self.cashflow_document(generated_at), self.today, generated_at)
