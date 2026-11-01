"""Moves between the household's own accounts: not cashflow (digest tags them, views skip them)."""
import re

# --- Internal-transfer detection -------------------------------------------
# Money moved between the household's OWN accounts is not cashflow — it's the
# same shekels in two ledgers. The dedup key (date, abs amount) already collapses
# the clean same-day both-legs case into one row; what survives is a single leg
# whose counterpart sits in another of our accounts (or an untracked personal
# account, e.g. Bank Hapoalim). The reliable signal is the description naming the
# household member or one of our own account numbers. We TAG these
# (`internal_transfer: true`) rather than drop them — the ledger stays complete
# and auditable; the spending summary and cashflow exclude them.
#
# The other reliable signal is structural: when both legs are in the data, a
# self-transfer collapses into one bucket holding a DEBIT at one bank and a CREDIT
# at another (e.g. the monthly salary forward: Leumi "העברת משכורת_י" -22,500 /
# Discount "בנק לאומי,משכורת" +22,500). RiseUp tags the inbound leg "משכורת", so
# without this it reads as a second salary. See `_is_cross_bank_pair`.
#
# NOTE: tuned to this household. Update OWN_NAMES / OWN_ACCOUNT_HINTS if accounts
# or holders change. Salary ("העברת משכורת", "בנק לאומי משכורת") does NOT name the
# holder, so on its own it is kept as real income — only the paired-legs rule
# above turns a forward into a transfer.
OWN_NAMES = ["ירין ששון", "ששון ירין"]
OWN_ACCOUNT_HINTS = ["806-6719", "806-671963", "10-806", "0034069", "0123444499"]
# Account-sweep descriptions that don't name the holder but are confirmed self-
# transfers between our own accounts. "העברה דיגיטל" always originates from the
# Leumi account and empties it to ~0, matched by a "+X העברה מירין ששון" inbound
# on Discount — i.e. a Leumi→Discount sweep. Treated as internal.
OWN_TRANSFER_DESCRIPTIONS = ["העברה דיגיטל"]

# Withdrawals from our own liquid deposit (פיקדון נזיל) coming back into checking,
# plus the tiny interest/profit credited alongside them. The deposit LEG (money
# going in) is real savings (is_savings_deposit, below); the withdrawal LEG is the
# same money returning and must not be double-counted as income.
DEPOSIT_WITHDRAWAL_PHRASES = ["משיכה מפיקדון", "רווחים ממשיכת הפקדה מפיקדון"]

# Loan ids where BOTH "הקמת הלוואה <id>" (opened) and "פירעון/פרעון הלוואה <id>"
# (repaid) were observed in the ledger — i.e. confirmed round-trips that net to
# ~zero, not real borrowing/debt-service. Populated below from ledger evidence.
# Deliberately an allowlist of specific ids, NOT a blanket rule on the phrase —
# most "פירעון הלוואה" rows are real ongoing loan repayments (leumi, discount
# loans 10800100014 / 15500316168) and must stay counted as spend.
ROUND_TRIP_LOAN_IDS = {"13200898802"}

_LOAN_ID_RE = re.compile(r"(?:הקמת|פירעון|פרעון) הלוואה\s+(\d+)")


def is_internal_transfer(rec):
    """True if the transaction is a move between the household's own accounts.

    Matches on the description referencing an own holder name, own account
    number, a known self-transfer phrase, a liquid-deposit withdrawal (the
    money returning from our own deposit), or one leg of a confirmed
    open+repay loan round-trip. Conservative: only fires on a positive
    signal, so external transfers (real income/expense) are kept.
    """
    desc = rec.get("description") or ""
    if any(n in desc for n in OWN_NAMES):
        return True
    if any(a in desc for a in OWN_ACCOUNT_HINTS):
        return True
    if any(p in desc for p in OWN_TRANSFER_DESCRIPTIONS):
        return True
    if any(p in desc for p in DEPOSIT_WITHDRAWAL_PHRASES):
        return True
    m = _LOAN_ID_RE.search(desc)
    if m and m.group(1) in ROUND_TRIP_LOAN_IDS:
        return True
    return False
