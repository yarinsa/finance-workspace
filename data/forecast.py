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
Run: python3 data/forecast.py
"""
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUDGET = ROOT / "riseup" / "raw" / "budget_current.json"
LEDGER = ROOT / "digested" / "transactions.json"
CAL_BIG = ROOT / "cal" / "raw" / "bigNumberAndDetails.json"
AMEX_BILL = ROOT / "amex" / "raw" / "billingsOverview.json"
MORTGAGE = ROOT / "discount-mortgage" / "raw" / "mortgage_details.json"

# RiseUp tags the mortgage envelope with this expense category. We suppress it
# and substitute the authoritative next-installment sum from the mortgage data
# (see authoritative_mortgage_payment).
MORTGAGE_EXPENSE = "משכנתא"
OUT_JSON = ROOT / "digested" / "forecast.json"
OUT_MD = ROOT / "digested" / "forecast.md"


HORIZON = 6  # months to project: next month through end of horizon (Jul→Dec 2026)


def add_months(yyyymm, n):
    y, m = int(yyyymm[:4]), int(yyyymm[5:7])
    idx = (y * 12 + (m - 1)) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def next_month(yyyymm):
    return add_months(yyyymm, 1)


def load():
    b = json.loads(BUDGET.read_text())
    tx = json.loads(LEDGER.read_text())
    return b, tx


def category_names(b):
    m = {}
    for x in b.get("trackingCategoryMetadata", []):
        cid = x.get("trackingCategoryId") or x.get("id") or x.get("_id")
        if cid:
            m[cid] = x.get("name")
    return m


def authoritative_mortgage_payment(target_month=None):
    """Full mortgage installment from the Discount mortgage dump for `target_month`.

    Returns ``(total, due_date)`` where total = Σ ``NextPayment`` across loans
    still active in ``target_month`` (YYYY-MM) and due_date is the installment
    day in that month (YYYY-MM-DD), or ``(None, None)`` if the file is missing.

    The dump only knows each loan's *next* payment date, but the loans are
    standard monthly amortising loans, so we carry ``NextPayment`` forward and
    simply drop any loan whose ``LastPaymentDate`` falls before ``target_month``.
    When ``target_month`` is None we report the dump's own next installment.

    Why this and not RiseUp's envelope: RiseUp (and the mortgage ``Summary``'s
    ``CurrentMonthTotalPayment``) report the *residual* of the current billing
    cycle — once the month's installment is paid that figure collapses to a few
    hundred ₪. The recurring monthly charge is the per-loan ``NextPayment`` sum
    (~₪8.5k), which is what actually hits the account next month. We therefore
    drop the RiseUp mortgage envelope (expense == MORTGAGE_EXPENSE) and use this.
    """
    try:
        d = json.loads(MORTGAGE.read_text())
    except FileNotFoundError:
        return None, None
    block = d["MortgagesDetails"]["MortgagesBlock"]["MortgageEntry"][0]
    loans = block["MortgageDetailsBlock"]["LoanEntry"]
    raw = next((l.get("NextPaymentDate") for l in loans if l.get("NextPaymentDate")), None)
    day = raw[6:8] if raw and len(raw) == 8 else "10"

    active = loans
    if target_month:
        # Keep loans whose final payment is in or after the target month.
        active = [l for l in loans
                  if (l.get("LastPaymentDate") or "99999999")[:6] >= target_month.replace("-", "")]
        due = f"{target_month}-{day}"
    else:
        due = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if raw and len(raw) == 8 else raw

    total = sum(l.get("NextPayment", 0) for l in active)
    return round(total, 2), due


def committed_card_charges(fmonth):
    """Already-locked credit-card billings settling in `fmonth` (YYYY-MM).

    These are the *settlement* of purchases RiseUp already tracks inside its
    spend envelopes, so they are NOT summed into the forecast net — they are a
    confidence cross-check of how much next-month spend is already committed
    (installments + posted transactions), independent of RiseUp's prediction.
    """
    out = []
    y, m = fmonth[:4], fmonth[5:7]

    # CAL: result.bigNumbers[].totalDebit, keyed by debitDate.
    try:
        cal = json.loads(CAL_BIG.read_text())
        for bn in cal["result"]["bigNumbers"]:
            dd = bn.get("debitDate", "")[:7]
            if dd == fmonth:
                amt = sum(d.get("totalDebit", 0) for d in bn.get("totalDebits", []))
                if amt:
                    out.append({"issuer": "cal", "debit_date": bn["debitDate"][:10],
                                "amount": round(amt, 2)})
    except (FileNotFoundError, KeyError):
        pass

    # AMEX: data[].billingAmounts.billingAmountIls, billingDate "MM/YYYY".
    try:
        amex = json.loads(AMEX_BILL.read_text())
        for d in amex.get("data", []):
            mm, yy = (d.get("billingDate", "/").split("/") + [""])[:2]
            if yy == y and mm == m:
                amt = (d.get("billingAmounts") or {}).get("billingAmountIls") or 0
                if amt:
                    out.append({"issuer": "amex", "debit_date": f"{y}-{m}",
                                "amount": round(amt, 2),
                                "final": d.get("isFinalBillingDate", False)})
    except (FileNotFoundError, KeyError):
        pass

    return out


def ledger_band(tx):
    """Net of recent full calendar months (excludes the current partial month)."""
    bym = defaultdict(lambda: [0.0, 0.0])
    cur = date.today().strftime("%Y-%m")
    for r in tx["transactions"]:
        mm = r.get("date", "")[:7]
        a = r.get("amount", 0)
        if a < 0:
            bym[mm][0] += a
        else:
            bym[mm][1] += a
    full = {m: v for m, v in bym.items() if m < cur and v[1] > 1000}
    band = sorted(full.items())[-5:]
    return [{"month": m, "net": round(v[1] + v[0], 2)} for m, v in band]


def build(b, fmonth):
    """Project a single target month `fmonth` (YYYY-MM) from the envelopes."""
    envs = b["envelopes"]
    base_month = b["budgetDate"]
    names = category_names(b)

    # Authoritative mortgage installment replaces RiseUp's residual-cycle figure.
    mort_amt, mort_due = authoritative_mortgage_payment(fmonth)

    fixed_income, fixed_expense = [], []
    for e in envs:
        if e["type"] != "fixed":
            continue
        d = e.get("details", {})
        # Drop RiseUp's mortgage envelope — substituted below from mortgage data.
        if d.get("expense") == MORTGAGE_EXPENSE:
            continue
        amt = e.get("originalAmount") or 0
        name = d.get("businessName") or d.get("expense") or e["id"]
        row = {"name": str(name), "category": d.get("expense"), "amount": abs(amt)}
        if d.get("isIncome"):
            fixed_income.append(row)
        else:
            fixed_expense.append(row)

    if mort_amt:
        fixed_expense.append({
            "name": f"משכנתא — full next installment (due {mort_due})",
            "category": MORTGAGE_EXPENSE,
            "amount": mort_amt,
            "source": "discount-mortgage",
        })

    discretionary = []
    for e in envs:
        if e["type"] != "trackingCategory":
            continue
        amt = e.get("originalAmount") or 0
        if amt <= 0:
            continue
        cid = e["id"].split("#")[-1]
        nm = names.get(cid) or names.get(e["id"]) or cid
        if nm == "__saving-hidden-category__":
            nm = "השקעה וחיסכון"
        discretionary.append({"name": nm, "amount": round(amt, 2)})

    income_total = sum(r["amount"] for r in fixed_income)
    fixed_exp_total = sum(r["amount"] for r in fixed_expense)
    discr_total = sum(r["amount"] for r in discretionary)
    expense_total = fixed_exp_total + discr_total
    net = income_total - expense_total

    cards = committed_card_charges(fmonth)
    cards_total = round(sum(c["amount"] for c in cards), 2)

    return {
        "forecast_month": fmonth,
        "based_on_budget": base_month,
        "horizon_offset": None,  # set by build_all
        "confidence": None,      # set by build_all
        "currency": "ILS",
        "income": {"total": round(income_total, 2), "items": fixed_income},
        "expenses": {
            "total": round(expense_total, 2),
            "fixed_total": round(fixed_exp_total, 2),
            "discretionary_total": round(discr_total, 2),
            "fixed_items": sorted(fixed_expense, key=lambda r: -r["amount"]),
            "discretionary_items": sorted(discretionary, key=lambda r: -r["amount"]),
        },
        "projected_net": round(net, 2),
        "committed_card_charges": {"total": cards_total, "items": cards},
    }


def build_all(b, tx):
    """Project HORIZON months forward, sharing one ledger sanity band."""
    base_month = b["budgetDate"]
    band = ledger_band(tx)
    months = []
    for off in range(1, HORIZON + 1):
        fmonth = add_months(base_month, off)
        m = build(b, fmonth)
        m["horizon_offset"] = off
        m["confidence"] = "high" if off == 1 else "carry-forward"
        months.append(m)
    return {
        "generated_for": date.today().isoformat(),
        "based_on_budget": base_month,
        "horizon_months": HORIZON,
        "currency": "ILS",
        "months": months,
        "ledger_band": band,
    }


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
    out = build_all(b, tx)
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
