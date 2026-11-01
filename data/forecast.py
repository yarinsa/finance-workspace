#!/usr/bin/env python3
"""
Three-month cashflow forecast (next month + the two after).

Reads RiseUp's forward-looking budget envelopes (data/riseup/raw/budget_current.json)
— which already carry RiseUp's per-category monthly *predictions* — and the digested
ledger (data/digested/transactions.json) as a sanity band, then writes:

  data/digested/forecast.json   (all 3 months under "months": [...])
  data/digested/forecast.md

RiseUp envelope model:
  - type "fixed"            -> recurring monthly bills/income (rent, mortgage, loans,
                              subscriptions, salary). `details.isIncome` flags income.
  - type "trackingCategory" -> discretionary spend categories, predicted per month
                              (originalAmount = predicted, name in trackingCategoryMetadata).
  - type "variable"/"variableIncome" -> uncategorised misc this month (used for run-rate only).

Projection horizon & confidence:
  RiseUp emits ONE monthly prediction, not a separate figure per future month, so the
  income / fixed / discretionary envelopes are held flat across all three months. Two
  things are recomputed per target month from authoritative source data:
    - mortgage installment — per-loan NextPayment, dropped once a loan's LastPaymentDate
      passes (so a loan ending mid-horizon stops being charged);
    - committed card charges — only exist for months the issuer has already billed
      (typically just next month), so later months correctly show none.
  Month 1 (next month) is therefore high-confidence; months 2-3 are an envelope
  carry-forward — treat them as a planning baseline, not a hard prediction.

Money out is negative, income positive — matching repo convention.
The compute lives in finance/views/forecast.py; this file loads the dumps, renders
the markdown and writes the outputs.
Run: python3 data/forecast.py
"""
import json
from datetime import date
from pathlib import Path

from finance.paths import data_root
from finance.views.forecast import (  # noqa: F401 — re-exported for scripts and tests
    HORIZON, MORTGAGE_EXPENSE, Sources, add_months, authoritative_mortgage_payment,
    build, build_all, category_names, committed_card_charges, envelope_category,
    is_internal_fixed, ledger_band, next_month, payment_for_track, schedule_adjusted,
    scheduled_payment)

ROOT = data_root()
BUDGET = ROOT / "riseup" / "raw" / "budget_current.json"
LEDGER = ROOT / "digested" / "transactions.json"
CAL_BIG = ROOT / "cal" / "raw" / "bigNumberAndDetails.json"
AMEX_BILL = ROOT / "amex" / "raw" / "billingsOverview.json"
MORTGAGE = ROOT / "discount-mortgage" / "raw" / "mortgage_details.json"
FREEZE = ROOT / "freeze.json"
# The bank's own amortization schedule (לוח סילוקין), hand-entered from the PDF —
# gitignored like freeze.json since it holds real payment figures.
SCHEDULE = ROOT / "mortgage_schedule.json"
OUT_JSON = ROOT / "digested" / "forecast.json"
OUT_MD = ROOT / "digested" / "forecast.md"


def load():
    b = json.loads(BUDGET.read_text())
    tx = json.loads(LEDGER.read_text())
    return b, tx


def load_mortgage_schedule(path=None):
    """Bank-schedule bands ``[{"from": "YYYY-MM", "to": "YYYY-MM", "payment": n}]``
    from data/mortgage_schedule.json, or [] when the file is absent."""
    try:
        return json.loads(Path(path or SCHEDULE).read_text()).get("periods", [])
    except FileNotFoundError:
        return []


def load_freeze():
    """User-confirmed freeze parameters from data/freeze.json (or {} if none).

    Written by ``detect_freeze.py`` when the bank's dump still shows the frozen
    (interest-only) installment but the user has told us the freeze's real shape,
    so we can project the correct full payment once it lifts — before the bank
    reflects it.
    """
    try:
        return json.loads(FREEZE.read_text()).get("tracks", {})
    except FileNotFoundError:
        return {}


def _read(path):
    """Parsed JSON at ``path``, or None when the file is absent."""
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def load_sources():
    """The mortgage, freeze, schedule, CAL and AMEX dumps as the view's ``Sources``."""
    return Sources(mortgage=_read(MORTGAGE), freeze=load_freeze(),
                   schedule=load_mortgage_schedule(), cal=_read(CAL_BIG),
                   amex=_read(AMEX_BILL))


def render_month(f):
    """Render one month's detail section."""
    L = []
    tag = "high confidence" if f["confidence"] == "high" else "envelope carry-forward"
    L.append(f"## {f['forecast_month']} — *{tag}*")
    L.append("")
    inc = f["income"]["total"]
    exp = f["expenses"]["total"]
    net = f["projected_net"]
    sign = "surplus" if net >= 0 else "shortfall"
    L.append(f"- **Income:** ₪{inc:,.0f}")
    L.append(f"- **Spending:** ₪{exp:,.0f}  "
             f"(fixed ₪{f['expenses']['fixed_total']:,.0f} · "
             f"discretionary ₪{f['expenses']['discretionary_total']:,.0f})")
    L.append(f"- **Net:** ₪{net:,.0f} ({sign})")
    L.append("")
    L.append("### Income")
    L.append("")
    L.append("| Source | ₪ |")
    L.append("|---|--:|")
    for r in f["income"]["items"]:
        L.append(f"| {r['name']} | {r['amount']:,.0f} |")
    L.append(f"| **Total** | **{inc:,.0f}** |")
    L.append("")
    L.append("### Fixed / recurring expenses")
    L.append("")
    L.append("| Item | Category | ₪ |")
    L.append("|---|---|--:|")
    for r in f["expenses"]["fixed_items"]:
        L.append(f"| {r['name']} | {r['category'] or ''} | {r['amount']:,.0f} |")
    L.append(f"| **Total** | | **{f['expenses']['fixed_total']:,.0f}** |")
    L.append("")
    L.append("### Discretionary (predicted per category)")
    L.append("")
    L.append("| Category | ₪ |")
    L.append("|---|--:|")
    for r in f["expenses"]["discretionary_items"]:
        L.append(f"| {r['name']} | {r['amount']:,.0f} |")
    L.append(f"| **Total** | **{f['expenses']['discretionary_total']:,.0f}** |")
    L.append("")
    cc = f.get("committed_card_charges", {})
    if cc.get("items"):
        L.append("### Already-committed card charges")
        L.append("")
        L.append(
            "Credit-card billings already locked in (installments + posted "
            "transactions). **Not added to the net above** — these settle purchases "
            "RiseUp already counts in its envelopes; shown as a confidence check on "
            "how much spend is already fixed."
        )
        L.append("")
        L.append("| Card | Debit date | ₪ |")
        L.append("|---|---|--:|")
        for c in cc["items"]:
            L.append(f"| {c['issuer']} | {c['debit_date']} | {c['amount']:,.0f} |")
        L.append(f"| **Total committed** | | **{cc['total']:,.0f}** |")
        L.append("")
    return L


def render_md(out):
    months = out["months"]
    L = []
    L.append(f"# Cashflow forecast — {months[0]['forecast_month']} → "
             f"{months[-1]['forecast_month']}")
    L.append("")
    L.append(
        f"*{out['horizon_months']}-month projection from RiseUp's "
        f"`{out['based_on_budget']}` budget envelopes (recurring bills + category "
        f"predictions). `python3 data/forecast.py`.*"
    )
    L.append("")
    L.append(
        "> Mortgage uses the **full installment** (Σ per-loan `NextPayment`) from the "
        "Discount mortgage dump, not RiseUp's residual-cycle figure — see "
        "`docs/forecast-architecture.md`. Income/fixed/discretionary envelopes are held "
        "**flat** across months (RiseUp emits one monthly prediction). Month 1 is "
        "high-confidence; later months are an envelope carry-forward for planning — "
        "committed card charges only exist where the issuer has already billed."
    )
    L.append("")
    # At-a-glance summary
    L.append("## At a glance")
    L.append("")
    L.append("| Month | Income | Spending | Net | Confidence |")
    L.append("|---|--:|--:|--:|---|")
    for f in months:
        L.append(f"| **{f['forecast_month']}** | {f['income']['total']:,.0f} | "
                 f"{f['expenses']['total']:,.0f} | {f['projected_net']:,.0f} | "
                 f"{f['confidence']} |")
    cum = 0
    cum_parts = []
    for f in months:
        cum += f["projected_net"]
        cum_parts.append(f"{f['forecast_month']} ₪{cum:,.0f}")
    L.append("")
    L.append(f"**Cumulative net:** {' · '.join(cum_parts)}")
    L.append("")
    # Per-month detail
    for f in months:
        L += render_month(f)
    # Shared ledger band
    L.append("## Sanity check — recent full-month net (from ledger)")
    L.append("")
    L.append("| Month | Net ₪ |")
    L.append("|---|--:|")
    for r in out["ledger_band"]:
        L.append(f"| {r['month']} | {r['net']:,.0f} |")
    L.append("")
    L.append(
        "> Ledger net is noisy: the unified ledger dedups on `(date, abs(amount))`, "
        "so internal transfers and card↔bank pairs distort monthly totals. Treat the "
        "envelope projection above as the primary forecast and the ledger band as a "
        "reasonableness check."
    )
    L.append("")
    return "\n".join(L)


def main():
    b, tx = load()
    out = build_all(b, tx, date.today(), load_sources())
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    OUT_MD.write_text(render_md(out))
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    for f in out["months"]:
        print(f"{f['forecast_month']} ({f['confidence']:>13}): "
              f"income ₪{f['income']['total']:,.0f}  "
              f"spend ₪{f['expenses']['total']:,.0f}  "
              f"net ₪{f['projected_net']:,.0f}")


if __name__ == "__main__":
    main()
