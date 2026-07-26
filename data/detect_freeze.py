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

Detection signal: for a normal amortising track the installment covers interest
plus principal. Under a principal-only freeze the installment collapses to about
the monthly interest (balance × annual_rate / 12). So a track whose NextPayment
≈ its interest-only figure — while its own history/siblings pay materially more —
is almost certainly frozen. We surface the discrepancy and let the user confirm.

Run: python3 data/detect_freeze.py            (interactive)
     python3 data/detect_freeze.py --check     (report only, no prompts, exit 1 if discrepancy)

Read-only over scraped data; only writes data/freeze.json.
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
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
    """Return the list of tracks that look principal-frozen, with diagnostics."""
    flagged = []
    for t in tracks:
        bal = t.get("PrincipalBalance", 0)
        if bal < MIN_TRACK_BALANCE:
            continue
        nxt = t.get("NextPayment", 0)
        int_only = monthly_interest(t)
        if abs(nxt - int_only) <= INTEREST_ONLY_TOLERANCE:
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


def report(flagged):
    print(f"Detected {len(flagged)} track(s) that look principal-frozen "
          f"(paying ≈ interest-only):\n")
    for f in flagged:
        print(f"  ⚠ {f['rate']}%  balance ₪{f['balance']:,.0f}: "
              f"pays ₪{f['current_payment']:,.0f}, full ≈ "
              f"₪{f['full_payment_est']:,.0f}  "
              f"(Δ ₪{f['deferred_principal_per_mo']:,.0f}/mo deferred)")


def main():
    check_only = "--check" in sys.argv
    tracks = load_tracks()
    flagged = detect(tracks)

    if not flagged:
        print("No payment discrepancy detected — no mortgage track looks frozen.")
        # Clear a stale freeze file so the forecast stops applying it.
        if FREEZE.exists() and not check_only:
            FREEZE.unlink()
            print(f"Removed stale {FREEZE.name}.")
        return 0

    report(flagged)

    if check_only:
        print("\n(--check) Run without --check to record the freeze parameters.")
        return 1

    entries = prompt_for_freeze(flagged)
    payload = {
        "generated_at": date.today().isoformat(),
        "source": "detect_freeze.py",
        "note": "User-confirmed mortgage freeze. forecast.py applies frozen_payment "
                "through resume_month-1, then resume_payment.",
        "tracks": entries,
    }
    FREEZE.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Wrote {FREEZE}. Re-run `python3 data/forecast.py` to apply it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
