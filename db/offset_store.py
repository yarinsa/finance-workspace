"""Manual offsets (קיזוז) through the ORM entity `TransactionOffset` (finance/tables.py).

Shared by the ledger API like db/tags.py: every function takes an open psycopg
connection and commits. A payback is addressed by its ledger key `(date, abs_amount)`.
The user's decision on a payback is the whole set of its links: `set_offsets`
replaces it (`[]` = "this payback offsets nothing", which also turns the digest's
auto suggestion off) and `reset_offsets` drops it, back to auto. Each change writes
one `override_audit` row (field "offsets", old/new = the link lists, or "auto").
"""
import datetime as dt
from decimal import Decimal

from sqlmodel import col, select

from finance.tables import OverrideAudit, TransactionOffset
from ledger import orm_session

CENT = Decimal("0.01")


def _key(k):
    d, a = k
    return (dt.date.fromisoformat(d) if isinstance(d, str) else d), Decimal(a).quantize(CENT)


def _rows(s, k):
    return s.exec(select(TransactionOffset).where(TransactionOffset.payback_date == k[0],
                                                  TransactionOffset.payback_abs_amount == k[1])
                  .order_by(col(TransactionOffset.id))).all()


def _described(rows):
    """The audit/readback form: "auto" without a decision, else the links."""
    if not rows:
        return "auto"
    return [{"date": r.expense_date.isoformat(), "abs_amount": f"{r.expense_abs_amount:.2f}",
             "amount": f"{r.amount:.2f}"} for r in rows if r.expense_date is not None]


def offsets_of(conn, k):
    """The user's links for payback `k`: None when it follows auto, else a list."""
    with orm_session(conn) as s:
        d = _described(_rows(s, _key(k)))
        return None if d == "auto" else d


def set_offsets(conn, k, links, actor):
    """Make `links` — [((date, abs_amount), amount), ...] — exactly payback `k`'s offsets.

    Amounts must be positive; an expense may appear once. Returns the stored links."""
    k = _key(k)
    clean = []
    for ek, amount in links:
        ek, amount = _key(ek), Decimal(str(amount)).quantize(CENT)
        if amount <= 0:
            raise ValueError("an offset amount must be positive")
        if any(ek == e for e, _ in clean):
            raise ValueError("an expense is linked once per payback")
        clean.append((ek, amount))
    with orm_session(conn) as s:
        rows = _rows(s, k)
        old = _described(rows)
        for r in rows:
            s.delete(r)
        s.flush()
        if clean:
            for (ed, ea), amount in clean:
                s.add(TransactionOffset(payback_date=k[0], payback_abs_amount=k[1],
                                        expense_date=ed, expense_abs_amount=ea, amount=amount))
        else:
            s.add(TransactionOffset(payback_date=k[0], payback_abs_amount=k[1]))
        s.flush()
        new = _described(_rows(s, k))
        s.add(OverrideAudit(actor=actor, txn_date=k[0], abs_amount=k[1], field="offsets", old=old, new=new))
        s.commit()
        return new


def reset_offsets(conn, k, actor):
    """Forget the user's decision on payback `k`; the digest's suggestion applies again."""
    k = _key(k)
    with orm_session(conn) as s:
        rows = _rows(s, k)
        if not rows:
            return
        old = _described(rows)
        for r in rows:
            s.delete(r)
        s.add(OverrideAudit(actor=actor, txn_date=k[0], abs_amount=k[1], field="offsets", old=old, new="auto"))
        s.commit()
