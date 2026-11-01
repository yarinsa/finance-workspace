"""Build `finance.views.household.Inputs` from this tenant's digested files (and the DB where
the pipeline already reads it). Each loader moves to Postgres as its input gets a table
(docs/json-to-db-migration.md); the views do not change when it does."""
import json
import os

import budgets
import forecast
import goals
import history
from finance.paths import data_root
from finance.views.household import Inputs

DIGESTED = os.path.join(str(data_root()), "digested")


def _json(name, optional=False):
    path = os.path.join(DIGESTED, name)
    if optional:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load(today):
    """Everything `Household` reads, as of `today` (the cash history walks back from it)."""
    tx_doc = _json("transactions.json")
    snapshot = _json("snapshot.json")
    return Inputs(
        ledger=tx_doc.get("transactions", []),
        snapshot=snapshot,
        category_merges=tx_doc.get("category_merges") or {},
        budget=budgets.load_budget(),
        budget_history=budgets.load_history(),
        budget_overrides=budgets.load_overrides(),
        forecast_sources=forecast.load_sources(),
        validation=_json("validation.json", optional=True),
        horizons=goals.horizons_from_db(),
        goals=goals.goals_from_db(),
        cash_accounts=history.load_cash(snapshot, today),
        positions=history.positions(snapshot, today),
    )
