#!/usr/bin/env python3
"""Net-worth projection CLI — Cashflow Phase 2.

The engine is ``finance/views/projection.py`` (see its docstring for the model and
assumptions). This file loads ``data/digested/snapshot.json``, ``forecast.json`` and
the bank's mortgage schedule, runs it for today and prints the result.
Read-only, idempotent. Importable: ``projection.build(snapshot, today, ...)`` re-exports the view's.
"""

import json
import os
from datetime import date

from finance.paths import data_root
from finance.views.projection import (  # noqa: F401 — re-exported for scripts and tests
    BIRTH_DATE, CONFIG, LIMITATIONS, amortize_loans, annuity_payment, build, metrics,
    resolve_config, simulate, to_chart)

HERE = str(data_root())   # the tenant's data directory
SNAPSHOT = os.path.join(HERE, "digested", "snapshot.json")
FORECAST = os.path.join(HERE, "digested", "forecast.json")


def _load_forecast():
    """forecast.py output, or None — the projection still builds without it."""
    try:
        with open(FORECAST, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


if __name__ == "__main__":
    import forecast
    with open(SNAPSHOT, encoding="utf-8") as f:
        snapshot = json.load(f)
    p = build(snapshot, date.today(), _load_forecast(), forecast.load_mortgage_schedule())
    c = p["config"]
    print(f"net worth today: {p['net_worth_today']:,} ₪")
    print(f"monthly surplus: {c['monthly_surplus']:,} ₪ ({c['monthly_surplus_source']}); "
          f"retirement drawdown: {c['retirement_drawdown']:,} ₪/mo")
    print(f"net worth at retirement (age {c['retirement_age']}): "
          f"{p['net_worth_at_retirement']:,} ₪")
    print(f"loans modeled: {p['loans_modeled']}, "
          f"total balance today: {p['total_loan_balance_today']:,} ₪")
    print("focal points:")
    for fp in p["focal_points"]:
        nv = fp.get("net_val")
        nv_s = f"{nv:,} ₪" if nv is not None else "—"
        print(f"  age {fp.get('age')}: {fp['name']} — net {nv_s}"
              + (f" (frees {fp['freed_monthly']:,}/mo)" if fp.get("freed_monthly") else ""))
    for m in p["metrics"]:
        print(f"  {m['key']}: {m['value']} ({m['rank']})")
