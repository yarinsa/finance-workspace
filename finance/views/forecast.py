"""Three-month cashflow forecast (next month + the two after): the pure builders.

Projects RiseUp's forward-looking budget envelopes (the ``budget_current.json`` dump,
which already carries RiseUp's per-category monthly *predictions*) with the digested
ledger as a sanity band. ``data/forecast.py`` loads the files, calls ``build_all`` and
writes ``forecast.json`` / ``forecast.md``.

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

Pure functions of explicit inputs (``Sources`` holds the dumps already parsed, ``today``
the date); no file reads. Money out is negative, income positive — matching repo convention.
"""
from collections import defaultdict
from dataclasses import dataclass, field

from finance import categories
from finance.transfers import is_internal_transfer

# The mortgage envelope's category (finance/categories.py: RiseUp's "משכנתא" label
# or the ledger's category for its payee, דסק-משכנתא). We suppress it and
# substitute the authoritative next-installment sum from the mortgage data
# (see authoritative_mortgage_payment).
MORTGAGE_EXPENSE = "משכנתא"

HORIZON = 6  # months to project: next month through end of horizon (Jul→Dec 2026)


@dataclass(frozen=True)
class Sources:
    """The authoritative dumps the forecast reads besides the budget envelopes.

    Each is already parsed; the empty value means "not known" (the file was absent).
    ``mortgage`` is the Discount mortgage's tracks as stored loans (``Loan`` dicts with
    ``category == "mortgage"``: ``loan_id``, ``monthly_payment``, ``final_date``,
    ``next_payment_date``; ISO dates), ``freeze`` the ``tracks`` of
    ``freeze.json``, ``schedule`` the ``periods`` of ``mortgage_schedule.json``, ``cal``
    CAL's ``bigNumberAndDetails.json`` and ``amex`` AMEX's ``billingsOverview.json``.
    """
    mortgage: list | None = None
    freeze: dict = field(default_factory=dict)
    schedule: list = field(default_factory=list)
    cal: dict | None = None
    amex: dict | None = None


def add_months(yyyymm, n):
    y, m = int(yyyymm[:4]), int(yyyymm[5:7])
    idx = (y * 12 + (m - 1)) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def next_month(yyyymm):
    return add_months(yyyymm, 1)


def category_names(b):
    m = {}
    for x in b.get("trackingCategoryMetadata", []):
        cid = x.get("trackingCategoryId") or x.get("id") or x.get("_id")
        if cid:
            m[cid] = x.get("name")
    return m


def authoritative_mortgage_payment(src, target_month=None):
    """Full mortgage installment from the Discount mortgage tracks for `target_month`.

    Returns ``(total, due_date)`` where total = Σ ``monthly_payment`` (the dump's per-track
    ``NextPayment``) across loans still active in ``target_month`` (YYYY-MM) and due_date
    is the installment day in that month (YYYY-MM-DD), or ``(None, None)`` with no tracks.

    The dump only knows each loan's *next* payment date, but the loans are
    standard monthly amortising loans, so we carry ``monthly_payment`` forward and
    simply drop any loan whose ``final_date`` falls before ``target_month``.
    When ``target_month`` is None we report the dump's own next installment.

    Why this and not RiseUp's envelope: RiseUp (and the mortgage ``Summary``'s
    ``CurrentMonthTotalPayment``) report the *residual* of the current billing
    cycle — once the month's installment is paid that figure collapses to a few
    hundred ₪. The recurring monthly charge is the per-loan ``NextPayment`` sum
    (~₪8.5k), which is what actually hits the account next month. We therefore
    drop the RiseUp mortgage envelope (expense == MORTGAGE_EXPENSE) and use this.
    """
    loans = src.mortgage
    if not loans:
        return None, None
    raw = next((l["next_payment_date"] for l in loans if l.get("next_payment_date")), None)
    day = raw[8:10] if raw else "10"

    active = loans
    if target_month:
        # Keep loans whose final payment is in or after the target month.
        active = [l for l in loans if (l.get("final_date") or "9999-12")[:7] >= target_month]
        due = f"{target_month}-{day}"
    else:
        due = raw

    total = round(sum(payment_for_track(l, target_month, src.freeze) for l in active), 2)
    if target_month and raw:
        # The dump only knows the current installment; the bank's schedule knows
        # the Jan-2027 step-up (מתווה tranches end their reduced-principal phase).
        total = schedule_adjusted(total, raw[:7], target_month, src.schedule)
    return total, due


def scheduled_payment(periods, month):
    """The schedule's installment for ``month`` (YYYY-MM): the band's payment,
    0.0 once past the final band (mortgage paid off), None if ``month`` precedes
    the schedule or there is no schedule."""
    if not periods:
        return None
    for p in periods:
        if p["from"] <= month <= p["to"]:
            return float(p["payment"])
    return 0.0 if month > max(p["to"] for p in periods) else None


def schedule_adjusted(current, base_month, target_month, periods):
    """Today's real installment moved by the schedule's step between months.

    ``current`` (the dump's NextPayment sum) runs a little over the schedule —
    index linkage the PDF can't know — so we apply the schedule as a *delta*
    from ``base_month`` rather than replacing the figure. Falls back to
    ``current`` when either month is outside the schedule; 0 once paid off.
    """
    tgt = scheduled_payment(periods, target_month)
    base = scheduled_payment(periods, base_month)
    if tgt == 0.0:
        return 0.0
    if tgt is None or not base:
        return current
    return round(current + tgt - base, 2)


def payment_for_track(track, target_month, freeze):
    """Payment for one mortgage track in ``target_month``, applying any freeze.

    The bank's dump reports the current (frozen) ``NextPayment`` and won't reflect
    the post-freeze figure until that charge posts. If ``freeze`` (``Sources.freeze``,
    the tracks of freeze.json) records this track, we return the frozen payment through
    the freeze window and the recomputed full payment from ``resume_month`` onward.
    With no freeze record, or no target month, we fall back to ``NextPayment``.
    """
    nxt = track.get("monthly_payment") or 0
    if not target_month:
        return nxt
    frz = (freeze or {}).get(track.get("loan_id"))
    if not frz:
        return nxt
    if target_month >= frz["resume_month"]:
        return frz["resume_payment"]
    return frz.get("frozen_payment", nxt)


def committed_card_charges(src, fmonth):
    """Already-locked credit-card billings settling in `fmonth` (YYYY-MM).

    These are the *settlement* of purchases RiseUp already tracks inside its
    spend envelopes, so they are NOT summed into the forecast net — they are a
    confidence cross-check of how much next-month spend is already committed
    (installments + posted transactions), independent of RiseUp's prediction.
    """
    out = []
    y, m = fmonth[:4], fmonth[5:7]

    # CAL: result.bigNumbers[].totalDebit, keyed by debitDate.
    if src.cal is not None:
        try:
            for bn in src.cal["result"]["bigNumbers"]:
                dd = bn.get("debitDate", "")[:7]
                if dd == fmonth:
                    amt = sum(d.get("totalDebit", 0) for d in bn.get("totalDebits", []))
                    if amt:
                        out.append({"issuer": "cal", "debit_date": bn["debitDate"][:10],
                                    "amount": round(amt, 2)})
        except KeyError:
            pass

    # AMEX: data[].billingAmounts.billingAmountIls, billingDate "MM/YYYY".
    if src.amex is not None:
        try:
            for d in src.amex.get("data", []):
                mm, yy = (d.get("billingDate", "/").split("/") + [""])[:2]
                if yy == y and mm == m:
                    amt = (d.get("billingAmounts") or {}).get("billingAmountIls") or 0
                    if amt:
                        out.append({"issuer": "amex", "debit_date": f"{y}-{m}",
                                    "amount": round(amt, 2),
                                    "final": d.get("isFinalBillingDate", False)})
        except KeyError:
            pass

    return out


def ledger_band(tx, today):
    """Net of recent full calendar months (excludes the current partial month)."""
    bym = defaultdict(lambda: [0.0, 0.0])
    cur = today.strftime("%Y-%m")
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


def is_internal_fixed(row):
    """A RiseUp fixed envelope that is a move between our own accounts.

    The ledger already tags these via ``is_internal_transfer``; the
    forecast reads RiseUp's envelopes directly, so it applies the same rule.
    E.g. the ₪452 standing order personal → own business account, which then
    pays card bills that are already counted.
    """
    return is_internal_transfer({"description": row.get("name") or ""})


def envelope_category(details, known=None):
    """Our category for a fixed envelope: the ledger's for the same payee (the
    household's edits apply), else the payee's merchant default or RiseUp's label
    through the taxonomy's SOURCE_ALIASES."""
    from finance.merchants import merchant_name
    name = details.get("businessName") or ""
    return ((known or {}).get(merchant_name(name)) if name else None) \
        or categories.label_category(name, details.get("expense"))


def build(b, fmonth, src, known=None):
    """Project a single target month `fmonth` (YYYY-MM) from the envelopes.

    `known` is ``categories.ledger_categories(ledger)``: each payee's category in
    the ledger, so fixed items carry the same category as their charges."""
    envs = b["envelopes"]
    base_month = b["budgetDate"]
    names = category_names(b)

    # Authoritative mortgage installment replaces RiseUp's residual-cycle figure.
    mort_amt, mort_due = authoritative_mortgage_payment(src, fmonth)

    fixed_income, fixed_expense = [], []
    for e in envs:
        if e["type"] != "fixed":
            continue
        d = e.get("details", {})
        category = envelope_category(d, known)
        # Drop RiseUp's mortgage envelope — substituted below from mortgage data.
        if category == MORTGAGE_EXPENSE:
            continue
        amt = e.get("originalAmount") or 0
        name = d.get("businessName") or d.get("expense") or e["id"]
        row = {"name": str(name), "category": category,
               "category_group": categories.group_of(category),
               "source_category": d.get("expense"), "amount": abs(amt)}
        if is_internal_fixed(row):
            continue
        if d.get("isIncome"):
            fixed_income.append(row)
        else:
            fixed_expense.append(row)

    if mort_amt:
        fixed_expense.append({
            "name": f"משכנתא — full next installment (due {mort_due})",
            "category": MORTGAGE_EXPENSE,
            "category_group": categories.group_of(MORTGAGE_EXPENSE),
            "amount": mort_amt,
            "source": "discount-mortgage",
        })

    discretionary = defaultdict(float)
    for e in envs:
        if e["type"] != "trackingCategory":
            continue
        amt = e.get("originalAmount") or 0
        if amt <= 0:
            continue
        cid = e["id"].split("#")[-1]
        # weekly envelopes (כלכלה#0..#4) carry their name in details, not in the id
        nm = (((e.get("details") or {}).get("trackingCategory") or {}).get("name")
              or names.get(cid) or names.get(e["id"]) or cid)
        # A tracking envelope is a budget line: name it by our category (חופשה ✈️ -> תיירות)
        nm = "השקעה וחיסכון" if nm == "__saving-hidden-category__" else categories.tracking_category(nm) or nm
        discretionary[nm] += amt
    discretionary = [{"name": n, "amount": round(a, 2)} for n, a in discretionary.items()]

    income_total = sum(r["amount"] for r in fixed_income)
    fixed_exp_total = sum(r["amount"] for r in fixed_expense)
    discr_total = sum(r["amount"] for r in discretionary)
    expense_total = fixed_exp_total + discr_total
    net = income_total - expense_total

    cards = committed_card_charges(src, fmonth)
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


def build_all(b, tx, today, src):
    """Project HORIZON months forward, sharing one ledger sanity band."""
    base_month = b["budgetDate"]
    band = ledger_band(tx, today)
    known = categories.ledger_categories(tx["transactions"])
    months = []
    for off in range(1, HORIZON + 1):
        fmonth = add_months(base_month, off)
        m = build(b, fmonth, src, known)
        m["horizon_offset"] = off
        m["confidence"] = "high" if off == 1 else "carry-forward"
        months.append(m)
    # The budget month itself: what RiseUp expects for the month in progress.
    # The dashboard sets month-to-date actuals against it ("₪X of ₪Y expected").
    current = build(b, base_month, src, known)
    current["horizon_offset"] = 0
    current["confidence"] = "budget"
    return {
        "generated_for": today.isoformat(),
        "based_on_budget": base_month,
        "horizon_months": HORIZON,
        "currency": "ILS",
        "current_month": current,
        "months": months,
        "ledger_band": band,
    }
