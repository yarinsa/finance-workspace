#!/usr/bin/env python3
"""Detect a mortgage-payment freeze BEFORE the bank reflects it, and record it.

The bank only updates a loan's ``NextPayment`` *after* the freeze's first charge
posts. But the household knows about a freeze the moment they arrange it. This
script closes that gap: it flags any mortgage track whose current ``NextPayment``
is suspiciously far from the payment we'd expect, asks the user what changed
(the three parameters a Discount freeze is defined by), and writes
``data/freeze.json`` — which ``forecast.py`` reads to project the real forward
payments instead of naively carrying the frozen figure forward.

A Discount freeze ("גרייס"/הקפאה) is fully described by three parameters:
  1. duration      — 3 or 6 months
  2. type          — principal-only (pay interest, defer principal) or
                     full (pay ₪0, interest capitalises onto the balance)
  3. push_end_date — whether the loan's end date moves out by the freeze length.
                     If pushed: the same full payment resumes later.
                     If NOT pushed: the deferred principal is squeezed into the
                     unchanged remaining term, so the post-freeze payment RISES.

Detection signal (a HINT, not a verdict): for a normal amortising track the
installment covers interest plus principal. Under a *principal-only* freeze the
installment collapses to about the monthly interest (balance × annual_rate / 12).
So a track whose NextPayment ≈ its interest-only figure is *worth investigating*.

*** THIS SCRIPT CANNOT DATE A FREEZE. Read this before trusting its output. ***

mortgage_details.json gives exactly two data points per track — PreviousPayment
and NextPayment. Two points cannot tell you when a freeze began, how many months
it runs, or whether it is still active. This script therefore reports a
*suspicion* and asks the user; it never establishes a freeze on its own.

Two failure modes this heuristic has actually hit (Aug 2026, the household's
real mortgage), both of which produced confidently wrong answers:

  1. FALSE POSITIVE from coincidence. Track 1 (4.60%, ₪441,497) had NextPayment
     1,692.40 vs an interest-only figure of 1,692.40 — an exact match to the
     agora. It was NOT frozen; the freeze had ended two months earlier and the
     match was luck. An interest-only match proves nothing by itself.

  2. WRONG FREEZE TYPE. The real freeze was FULL, not principal-only: the three
     main tracks paid ₪0 and only the three 0.0001% מתווה tracks kept paying
     (461.59 + 659.51 + 586.44 = 1,707.54 exactly). A full freeze does NOT leave
     tracks sitting at interest-only, so this heuristic cannot see one at all —
     it is blind to the very freeze shape Discount actually granted.

THE ONLY WAY TO DATE A FREEZE is the checking-account charge history: the
mortgage posts one debit per month described "דסק-משכנתא".

  GET /Titan/gatewayAPI/lastTransactions/transactions/<acct>/ByDate
        ?FromDate=YYYYMMDD&ToDate=YYYYMMDD&IsTransactionDetails=True
        &IsFutureTransactionFlag=True&IsEventNames=True&IsCategoryDescCode=True
  Headers: UUID: <live UUID from the running app>   (mandatory)
           BusinessProcessID: OSH_LENTRIES_ALTAMIRA (mandatory)
  Omitting either returns HTTP 200 with {"Error":{"MsgText":"קלט לא תקין"}}.
  Lookback is capped at ~9-10 months (FromDate=20250901 works, 20250801 is empty).

See .claude/skills/refresh/references/discount-mortgage.md ("Dating a freeze from
payment history") for the full recipe and the worked Apr-Jun 2026 example.

For the record, that history — the evidence that settled it:

    2025-09-01   -8,622.29    normal
    2025-10-03   -8,652.03    normal
    2025-11-02   -8,640.80    normal
    2025-12-01   -8,637.99    normal
    2026-01-01   -8,574.38    normal
    2026-02-01   -8,504.54    normal
    2026-03-10  -10,272.44    catch-up/double month; charge day moves 1st -> 10th
    2026-04-10   -1,707.54    FREEZE month 1  (= the 3 מתווה tracks, exactly)
    2026-05-10   -1,707.54    FREEZE month 2
    2026-06-10   -1,707.54    FREEZE month 3
    2026-07-10   -6,240.16    post-freeze (carries ~₪250 unexplained residue)
    2026-08-10   -5,901.25    scheduled; = sum(LoanEntry[].NextPayment)

  => 3-month FULL freeze covering the Apr/May/Jun 2026 charges. Already ENDED.
     Post-freeze payment settled at 5,901.25, ~₪2,700 BELOW the pre-freeze
     ~8,600 — the end date was pushed out rather than the deferred principal
     being squeezed into the unchanged term.

Run: python3 data/detect_freeze.py            (interactive)
     python3 data/detect_freeze.py --check     (report only, no prompts, exit 1 if discrepancy)

Read-only over scraped data; only writes the freeze (`loan_freezes`, or data/freeze.json without a database).
"""
import json
import sys
from datetime import date
from pathlib import Path

import stores
from finance.paths import data_root

ROOT = data_root()
MORTGAGE = ROOT / "discount-mortgage" / "raw" / "mortgage_details.json"
FREEZE = ROOT / "freeze.json"

# A track is flagged as "looks frozen" when its NextPayment is within this many
# ₪ of the pure interest-only amount — i.e. it is paying interest but ~no
# principal. Tuned to absorb rounding / index drift without missing a real freeze
# (a real freeze defers hundreds–thousands of ₪ of principal, far above this).
INTEREST_ONLY_TOLERANCE = 60.0

# Only tracks above this balance carry enough principal for a freeze to matter
# and to be detectable; the tiny 0%-ish מתווה bridging tracks are excluded.
MIN_TRACK_BALANCE = 100_000


def load_tracks():
    d = json.loads(MORTGAGE.read_text())
    block = d["MortgagesDetails"]["MortgagesBlock"]["MortgageEntry"][0]
    return block["MortgageDetailsBlock"]["LoanEntry"]


def monthly_interest(track):
    """Pure interest portion of one month on this track's current balance."""
    bal = track.get("PrincipalBalance", 0)
    rate = track.get("TotalInterestRate", 0)
    return bal * (rate / 100) / 12


def full_payment_estimate(track):
    """Estimate the *un-frozen* (principal+interest) installment for a track.

    Prefer the track's own ``PreviousPayment`` when it is clearly higher than the
    current one (the bank still shows last cycle's full charge). Otherwise fall
    back to a standard annuity over the remaining term at the current rate — the
    same shape the bank uses to recompute once the freeze lifts. Returns a float.
    """
    nxt = track.get("NextPayment", 0)
    prev = track.get("PreviousPayment", 0)
    if prev and prev > nxt + INTEREST_ONLY_TOLERANCE:
        return prev
    bal = track.get("PrincipalBalance", 0)
    n = int(track.get("NumOfPaymentsRemained", 0) or 0)
    r = (track.get("TotalInterestRate", 0) / 100) / 12
    if n <= 0:
        return nxt
    if r == 0:
        return bal / n
    factor = (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    return bal * factor


def detect(tracks):
    """Return tracks that *might* be principal-frozen, with diagnostics.

    Deliberately conservative. An interest-only match alone is NOT enough — see
    the module docstring: track 1 matched its interest-only figure to the agora
    in Aug 2026 while not being frozen at all. So we additionally require
    corroboration that the payment actually *dropped*: PreviousPayment must be
    materially above NextPayment. A track that has been paying the same amount
    for two cycles is not entering a freeze, whatever its interest-only figure
    happens to equal.

    This still cannot see a FULL freeze (tracks paying ₪0 are absent from the
    charge entirely, not sitting at interest-only) — see detect_full_freeze.
    """
    flagged = []
    for t in tracks:
        bal = t.get("PrincipalBalance", 0)
        if bal < MIN_TRACK_BALANCE:
            continue
        nxt = t.get("NextPayment", 0)
        prev = t.get("PreviousPayment", 0)
        int_only = monthly_interest(t)
        stepped_down = prev > nxt + INTEREST_ONLY_TOLERANCE
        if abs(nxt - int_only) <= INTEREST_ONLY_TOLERANCE and stepped_down:
            full = full_payment_estimate(t)
            flagged.append({
                "loan_account": t.get("LoanAccount"),
                "name": t.get("LoanName", ""),
                "rate": t.get("TotalInterestRate"),
                "balance": round(bal, 2),
                "current_payment": round(nxt, 2),
                "interest_only": round(int_only, 2),
                "full_payment_est": round(full, 2),
                "deferred_principal_per_mo": round(full - nxt, 2),
                "payments_remaining": int(t.get("NumOfPaymentsRemained", 0) or 0),
                "next_payment_date": t.get("NextPaymentDate"),
            })
    return flagged


def _ask(prompt, choices):
    """Prompt until the user picks one of `choices` (list of accepted strings)."""
    while True:
        ans = input(prompt).strip().lower()
        if ans in choices:
            return ans
        print(f"  please answer one of: {', '.join(choices)}")


def add_months(yyyymm, n):
    y, m = int(yyyymm[:4]), int(yyyymm[5:7])
    idx = (y * 12 + (m - 1)) + n
    return f"{idx // 12:04d}-{idx % 12 + 1:02d}"


def post_freeze_payment(track, months, freeze_type, push_end_date):
    """Full installment that resumes once the freeze lifts.

    - push_end_date True  → term extends by the freeze length, so the original
      full annuity simply resumes (same ₪).
    - push_end_date False → deferred principal (and, for a full freeze, the
      capitalised interest) must be repaid over the UNCHANGED remaining term, so
      the installment rises. We recompute the annuity over the shortened window.
    """
    full = full_payment_estimate(track)
    if push_end_date:
        return round(full, 2)

    bal = track["balance"] if "balance" in track else track.get("PrincipalBalance", 0)
    rate = track.get("rate", track.get("TotalInterestRate", 0))
    r = (rate / 100) / 12
    n = track.get("payments_remaining", track.get("NumOfPaymentsRemained", 0))
    n = int(n or 0)
    # A full freeze capitalises the missed interest onto the balance; a
    # principal-only freeze leaves the balance unchanged (interest was paid).
    if freeze_type == "full":
        bal = bal * ((1 + r) ** months) if r else bal
    # Remaining term after the freeze months elapse, end date NOT pushed.
    n_after = max(n - months, 1)
    if r == 0:
        return round(bal / n_after, 2)
    factor = (r * (1 + r) ** n_after) / ((1 + r) ** n_after - 1)
    return round(bal * factor, 2)


def prompt_for_freeze(flagged):
    """Interactively collect the 3 freeze params for each flagged track."""
    print("\nA freeze is defined by 3 things. Answer per track.\n")
    entries = {}
    # The freeze started on the cycle whose reduced charge we can already see:
    # its NextPaymentDate is the first frozen charge.
    for f in flagged:
        print(f"── Track {f['rate']}%  balance ₪{f['balance']:,.0f}")
        print(f"   pays ₪{f['current_payment']:,.0f} now vs full ≈ "
              f"₪{f['full_payment_est']:,.0f}  "
              f"(deferring ≈ ₪{f['deferred_principal_per_mo']:,.0f}/mo)")
        dur = _ask("   1) Freeze duration — 3 or 6 months? [3/6] ", ["3", "6"])
        ftype = _ask("   2) Principal-only or full freeze? [p/f] ", ["p", "f"])
        push = _ask("   3) Is the loan END DATE pushed out? [y/n] ", ["y", "n"])
        # Free-text override: the user can record anything the data can't see
        # (e.g. "8% but a monthly refund makes it effectively 0%") to inform the
        # calculation and future sessions. Blank = no note.
        note = input("   4) Any note / your own take on this loan? "
                     "(optional, Enter to skip) ").strip()
        months = int(dur)
        freeze_type = "principal_only" if ftype == "p" else "full"
        push_end = push == "y"

        start = (f.get("next_payment_date") or "")[:6]
        start_month = f"{start[:4]}-{start[4:6]}" if len(start) == 6 else \
            date.today().strftime("%Y-%m")
        # First full-price month = start + freeze length.
        resume_month = add_months(start_month, months)
        resume_pay = post_freeze_payment(f, months, freeze_type, push_end)

        entries[f["loan_account"]] = {
            "name": f["name"],
            "rate": f["rate"],
            "months": months,
            "type": freeze_type,
            "push_end_date": push_end,
            "frozen_payment": f["current_payment"],
            "frozen_from_month": start_month,
            "resume_month": resume_month,
            "resume_payment": resume_pay,
            "note": note,  # user's free-text override / perspective, "" if none
        }
        print(f"   → frozen ₪{f['current_payment']:,.0f} through "
              f"{add_months(resume_month, -1)}, then ₪{resume_pay:,.0f} "
              f"from {resume_month}.")
        if note:
            print(f"   → note: {note}")
        print()
    return entries


HISTORY_HINT = """
  ⚠ This is a SUSPICION, not a finding. mortgage_details.json holds only two
    data points per track (PreviousPayment / NextPayment) and CANNOT tell you
    when a freeze started, how long it runs, or whether it already ended.

    To confirm, query the checking-account charge history and read the
    "דסק-משכנתא" debits month by month — the frozen months are visibly smaller:

      GET /Titan/gatewayAPI/lastTransactions/transactions/<acct>/ByDate
            ?FromDate=YYYYMMDD&ToDate=YYYYMMDD&IsTransactionDetails=True
            &IsFutureTransactionFlag=True&IsEventNames=True&IsCategoryDescCode=True
      Headers: UUID: <live from app>, BusinessProcessID: OSH_LENTRIES_ALTAMIRA
      (lookback caps at ~9-10 months)

    Recipe: .claude/skills/refresh/references/discount-mortgage.md
            -> "Dating a freeze from payment history"
"""


def zero_paying_tracks(tracks):
    """Tracks charging ~₪0 — the signature of a FULL freeze.

    Under a full freeze the track pays nothing at all (interest capitalises), so
    it never resembles interest-only and detect() is blind to it. The Apr-Jun
    2026 freeze was exactly this shape.
    """
    out = []
    for t in tracks:
        if t.get("PrincipalBalance", 0) < MIN_TRACK_BALANCE:
            continue
        if abs(t.get("NextPayment", 0)) < 1.0:
            out.append(t)
    return out


def report(flagged, zeroed=()):
    if zeroed:
        print(f"{len(zeroed)} substantial track(s) are charging ~₪0 — the "
              f"signature of a FULL freeze:\n")
        for t in zeroed:
            print(f"  ⚠ {t.get('TotalInterestRate')}%  balance "
                  f"₪{t.get('PrincipalBalance', 0):,.0f}: NextPayment ₪0")
        print()

    if flagged:
        print(f"Detected {len(flagged)} track(s) that MAY be principal-frozen "
              f"(paying ≈ interest-only AND stepped down last cycle):\n")
        for f in flagged:
            print(f"  ⚠ {f['rate']}%  balance ₪{f['balance']:,.0f}: "
                  f"pays ₪{f['current_payment']:,.0f}, full ≈ "
                  f"₪{f['full_payment_est']:,.0f}  "
                  f"(Δ ₪{f['deferred_principal_per_mo']:,.0f}/mo deferred)")
    print(HISTORY_HINT)


def main():
    check_only = "--check" in sys.argv
    tracks = load_tracks()
    flagged = detect(tracks)
    zeroed = zero_paying_tracks(tracks)

    if not flagged and not zeroed:
        print("No payment discrepancy detected in the current dump.")
        print("NOTE: this does NOT rule out a freeze — a freeze that has already "
              "ended leaves no trace here. Only the charge history can tell you.")
        print(HISTORY_HINT)
        # Clear a stale freeze so the forecast stops applying it.
        if not check_only:
            if stores.from_db("input_store", lambda m, conn: bool(m.loan_freezes(conn)) and (m.set_loan_freezes(conn, {}) or True)):
                print("Removed the stale freeze from loan_freezes.")
            if FREEZE.exists():
                FREEZE.unlink()
                print(f"Removed stale {FREEZE.name}.")
        return 0

    report(flagged, zeroed)

    if check_only:
        print("(--check) Nothing has been recorded. Run the history query above "
              "to establish whether a freeze is real, when it started, and "
              "whether it is still active — then run without --check to record "
              "the confirmed parameters.")
        return 1

    if not flagged:
        # Only a full freeze was seen; there is no interest-only track to
        # parameterise, and we will not invent one.
        print("Nothing recorded: confirm the window from the charge history "
              "first, then record it deliberately.")
        return 1

    print("Confirm against the charge history BEFORE answering these prompts — "
          "if the freeze has already ended, do not record one.")
    proceed = _ask("Record a freeze anyway? [y/n] ", ["y", "n"])
    if proceed == "n":
        print("Nothing written.")
        return 0

    entries = prompt_for_freeze(flagged)
    payload = {
        "generated_at": date.today().isoformat(),
        "source": "detect_freeze.py",
        "note": "User-confirmed mortgage freeze. forecast.py applies frozen_payment "
                "through resume_month-1, then resume_payment.",
        "tracks": entries,
    }
    if stores.from_db("input_store", lambda m, conn: m.set_loan_freezes(conn, entries) or True):
        print("Recorded the freeze in loan_freezes. Re-run `python3 data/forecast.py` to apply it.")
    else:   # no database: the side file, as before
        FREEZE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"Wrote {FREEZE}. Re-run `python3 data/forecast.py` to apply it.")
    return 0


if __name__ == "__main__":
    from finance.tenancy import use_cli_tenant
    use_cli_tenant()
    sys.exit(main())
