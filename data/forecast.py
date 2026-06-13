#!/usr/bin/env python3
"""
Next-month cashflow forecast.

Reads RiseUp's forward-looking budget envelopes (data/riseup/raw/budget_current.json)
— which already carry RiseUp's per-category monthly *predictions* — and the digested
ledger (data/digested/transactions.json) as a sanity band, then writes:

  data/digested/forecast.json
  data/digested/forecast.md

RiseUp envelope model:
  - type "fixed"            -> recurring monthly bills/income (rent, mortgage, loans,
                              subscriptions, salary). `details.isIncome` flags income.
  - type "trackingCategory" -> discretionary spend categories, predicted per month
                              (originalAmount = predicted, name in trackingCategoryMetadata).
  - type "variable"/"variableIncome" -> uncategorised misc this month (used for run-rate only).

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


def next_month(yyyymm):
    y, m = int(yyyymm[:4]), int(yyyymm[5:7])
    m += 1
    if m > 12:
        y, m = y + 1, 1
    return f"{y:04d}-{m:02d}"


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


def authoritative_mortgage_payment():
    """Full next mortgage installment from the Discount mortgage dump.

    Returns ``(total, due_date)`` where total = Σ ``NextPayment`` across all
    active loans and due_date is their shared ``NextPaymentDate`` (YYYY-MM-DD),
    or ``(None, None)`` if the file is missing.

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
    total = sum(l.get("NextPayment", 0) for l in loans)
    raw = next((l.get("NextPaymentDate") for l in loans if l.get("NextPaymentDate")), None)
    due = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if raw and len(raw) == 8 else raw
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


def build(b, tx):
    envs = b["envelopes"]
    base_month = b["budgetDate"]
    fmonth = next_month(base_month)
    names = category_names(b)

    # Authoritative mortgage installment replaces RiseUp's residual-cycle figure.
    mort_amt, mort_due = authoritative_mortgage_payment()

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

    # Ledger sanity band: net of full calendar months (exclude current partial month).
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

    cards = committed_card_charges(fmonth)
    cards_total = round(sum(c["amount"] for c in cards), 2)

    return {
        "forecast_month": fmonth,
        "based_on_budget": base_month,
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
        "ledger_band": [
            {"month": m, "net": round(v[1] + v[0], 2)} for m, v in band
        ],
    }


def render_md(f):
    L = []
    L.append(f"# Cashflow forecast — {f['forecast_month']}")
    L.append("")
    L.append(
        f"*Projected from RiseUp's `{f['based_on_budget']}` budget envelopes "
        f"(recurring bills + category predictions). `python3 data/forecast.py`.*"
    )
    L.append("")
    L.append("## Bottom line")
    L.append("")
    inc = f["income"]["total"]
    exp = f["expenses"]["total"]
    net = f["projected_net"]
    sign = "surplus" if net >= 0 else "shortfall"
    L.append(f"- **Projected income:** ₪{inc:,.0f}")
    L.append(f"- **Projected spending:** ₪{exp:,.0f}  "
             f"(fixed ₪{f['expenses']['fixed_total']:,.0f} · "
             f"discretionary ₪{f['expenses']['discretionary_total']:,.0f})")
    L.append(f"- **Projected net:** ₪{net:,.0f} ({sign})")
    L.append("")
    L.append("## Income")
    L.append("")
    L.append("| Source | ₪ |")
    L.append("|---|--:|")
    for r in f["income"]["items"]:
        L.append(f"| {r['name']} | {r['amount']:,.0f} |")
    L.append(f"| **Total** | **{inc:,.0f}** |")
    L.append("")
    L.append("## Fixed / recurring expenses")
    L.append("")
    L.append(
        "> Mortgage uses the **full next installment** (Σ per-loan `NextPayment`) "
        "from the Discount mortgage dump, not RiseUp's residual-cycle figure — see "
        "`docs/forecast-architecture.md`."
    )
    L.append("")
    L.append("| Item | Category | ₪ |")
    L.append("|---|---|--:|")
    for r in f["expenses"]["fixed_items"]:
        L.append(f"| {r['name']} | {r['category'] or ''} | {r['amount']:,.0f} |")
    L.append(f"| **Total** | | **{f['expenses']['fixed_total']:,.0f}** |")
    L.append("")
    L.append("## Discretionary (predicted per category)")
    L.append("")
    L.append("| Category | ₪ |")
    L.append("|---|--:|")
    for r in f["expenses"]["discretionary_items"]:
        L.append(f"| {r['name']} | {r['amount']:,.0f} |")
    L.append(f"| **Total** | **{f['expenses']['discretionary_total']:,.0f}** |")
    L.append("")
    cc = f.get("committed_card_charges", {})
    if cc.get("items"):
        L.append(f"## Already-committed card charges — {f['forecast_month']}")
        L.append("")
        L.append(
            "Credit-card billings already locked in for next month (installments + "
            "posted transactions). **Not added to the net above** — these settle "
            "purchases RiseUp already counts in its envelopes; shown here as a "
            "confidence check on how much July spend is already fixed."
        )
        L.append("")
        L.append("| Card | Debit date | ₪ |")
        L.append("|---|---|--:|")
        for c in cc["items"]:
            L.append(f"| {c['issuer']} | {c['debit_date']} | {c['amount']:,.0f} |")
        L.append(f"| **Total committed** | | **{cc['total']:,.0f}** |")
        L.append("")

    L.append("## Sanity check — recent full-month net (from ledger)")
    L.append("")
    L.append("| Month | Net ₪ |")
    L.append("|---|--:|")
    for r in f["ledger_band"]:
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
    f = build(b, tx)
    OUT_JSON.write_text(json.dumps(f, ensure_ascii=False, indent=2))
    OUT_MD.write_text(render_md(f))
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")
    print(f"\n{f['forecast_month']}: income ₪{f['income']['total']:,.0f}  "
          f"spend ₪{f['expenses']['total']:,.0f}  net ₪{f['projected_net']:,.0f}")


if __name__ == "__main__":
    main()
