"""Tags on transactions, through the ORM entities in finance/tables.py (`Tag`, `TransactionTag`).

Shared by `db/edit.py` (actor "cli") and the ledger API, like db/overrides.py: every
function takes an open psycopg connection, works on it through `ledger.orm_session`,
and commits. A transaction is addressed by its ledger key `(date, abs_amount)`.
Each tag added to or removed from a transaction writes an `override_audit` row
(field "tags", old/new = the tag name or null).
"""
import datetime as dt
import re
from decimal import Decimal

from sqlmodel import col, select

from finance.tables import OverrideAudit, ScrapedTransaction, Tag, TransactionTag
from ledger import orm_session

COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_NAME = 40


def _key(k):
    """The ledger key typed for the ORM (`ledger.key` may carry the date as an ISO string)."""
    d, a = k
    return (dt.date.fromisoformat(d) if isinstance(d, str) else d), Decimal(a)


def _tag(t):
    return {"id": t.id, "name": t.name, "color": t.color}


def clean_name(name):
    """A tag name as stored: stripped, non-empty, at most MAX_NAME characters."""
    name = (name or "").strip()
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"a tag name is 1-{MAX_NAME} characters")
    return name


def _check_color(color):
    if color is not None and not COLOR.match(color):
        raise ValueError("color must be #rrggbb or null")


def all_tags(conn):
    """Every tag, by name, with how many transactions carry it."""
    with orm_session(conn) as s:
        tags = s.exec(select(Tag).order_by(Tag.name)).all()
        return [{**_tag(t), "count": len(t.links)} for t in tags]


def tags_of(conn, k):
    """The names of the tags on transaction `k`, sorted."""
    with orm_session(conn) as s:
        return _names(s, _key(k))


def _names(s, k):
    return list(s.exec(select(Tag.name).join(TransactionTag)
                       .where(TransactionTag.txn_date == k[0], TransactionTag.abs_amount == k[1])
                       .order_by(Tag.name)).all())


def _get_or_create(s, name):
    tag = s.exec(select(Tag).where(Tag.name == name)).first()
    if tag is None:
        tag = Tag(name=name)
        s.add(tag)
        s.flush()
    return tag


def set_tags(conn, k, names, actor):
    """Make `names` exactly the tags on transaction `k`, creating unknown tags.

    Returns the sorted names afterwards. Auditing one row per added or removed tag."""
    k = _key(k)
    wanted = sorted({clean_name(n) for n in names})
    with orm_session(conn) as s:
        links = s.exec(select(TransactionTag).where(TransactionTag.txn_date == k[0],
                                                    TransactionTag.abs_amount == k[1])).all()
        have = {link.tag_ref.name: link for link in links}
        for name in sorted(set(have) - set(wanted)):
            s.delete(have[name])
            s.add(OverrideAudit(actor=actor, txn_date=k[0], abs_amount=k[1], field="tags", old=name, new=None))
        for name in sorted(set(wanted) - set(have)):
            s.add(TransactionTag(txn_date=k[0], abs_amount=k[1], tag_ref=_get_or_create(s, name)))
            s.add(OverrideAudit(actor=actor, txn_date=k[0], abs_amount=k[1], field="tags", old=None, new=name))
        s.commit()
        return _names(s, k)


def update_tag(conn, tag_id, name=None, color=...):
    """Rename and/or recolor a tag (`color=None` clears it). None if there is no such tag."""
    with orm_session(conn) as s:
        tag = s.get(Tag, tag_id)
        if tag is None:
            return None
        if name is not None:
            tag.name = clean_name(name)
        if color is not ...:
            _check_color(color)
            tag.color = color
        s.commit()
        return _tag(tag)


def delete_tag(conn, tag_id):
    """Delete a tag and every link to it. False if there is no such tag."""
    with orm_session(conn) as s:
        tag = s.get(Tag, tag_id)
        if tag is None:
            return False
        s.delete(tag)
        s.commit()
        return True


def tag_name_taken(conn, name, tag_id=None):
    with orm_session(conn) as s:
        return s.exec(select(Tag.id).where(Tag.name == name, col(Tag.id) != tag_id)).first() is not None


def orphaned(conn):
    """Tag links whose transaction no longer exists, newest first."""
    with orm_session(conn) as s:
        rows = s.exec(select(TransactionTag).outerjoin(
            ScrapedTransaction, (ScrapedTransaction.txn_date == TransactionTag.txn_date)
            & (ScrapedTransaction.abs_amount == TransactionTag.abs_amount))
            .where(col(ScrapedTransaction.txn_date).is_(None))
            .order_by(col(TransactionTag.txn_date).desc(), TransactionTag.abs_amount)).all()
        return [{"date": r.txn_date.isoformat(), "abs_amount": f"{r.abs_amount:.2f}", "tag": r.tag_ref.name}
                for r in rows]
