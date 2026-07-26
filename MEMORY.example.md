# Project memory — Finance workspace (TEMPLATE)

Copy this file to `MEMORY.md` (which is **gitignored**) and fill in the real
values. `MEMORY.md` is the project-local household memory: facts the pipeline
cannot infer from scraped data — the human context behind the numbers. It is
loaded each session via `CLAUDE.md` and is isolated from the user's machine-global
Claude memory so it travels with the project folder, not the computer.

    cp MEMORY.example.md MEMORY.md   # then edit MEMORY.md with real facts

Keep entries to verifiable facts + why they matter. Convert relative dates to
absolute. Do **not** put real personal values in this template — it is committed.

---

## The household

- **Birth date: <YYYY-MM-DD>.** Used by `data/projection.py` via `BIRTH_DATE`.
  Drives every loan-payoff/retirement age — if the projection age looks wrong,
  this is the source of truth.

## Loans — non-obvious facts

<!-- Anything the scraped rate/payment can't show. Examples: -->

- **<Loan name/id> effective rate differs from nominal.** e.g. nominal X% but a
  monthly refund/subsidy offsets the interest → effectively ~0%.
  - *Why it matters:* don't quote the nominal rate as real cost; may/may-not be a
    prepayment target as a result.

- **Mortgage freeze (if active).** Which tracks, frozen amount vs full price, and
  the month full price returns.
  - *Why it matters:* the bank's dump reflects a freeze only *after* the charge
    posts. When an installment looks unusually low, run
    `python3 data/detect_freeze.py`, confirm the 3 params, and let
    `data/freeze.json` drive the forecast. Don't treat the low figure as permanent.

## Advice preferences

- **Loan prepayment for cashflow** → record the current best target and the
  mechanism (Schpitzer loan + instruct bank *הקטנת התשלום*, not קיצור התקופה).
  See the "Saving money" section in `CLAUDE.md` for the general method.

---

*Bug fixes, code structure, and git history are intentionally NOT recorded here —
the repo already captures those. This file is only for human context the data
can't derive.*
