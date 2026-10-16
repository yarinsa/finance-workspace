"""The ledger as GraphQL resolvers see it: one load per request, then filtered in memory.

The household ledger is a few thousand rows, so a request reads every effective row
once (scraped layer + overrides + tags, like db/overrides.py) and answers every
connection, filter and total from that. Merchants only exist this way: they are
derived from descriptions in Python (finance/merchants.py), not stored. Move a
filter into SQL when the ledger outgrows this, not before.
"""
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from functools import cached_property

from finance.merchants import merchant_name

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Category:
    TYPENAME = "Category"
    id: int
    name: str
    source: str


@dataclass(frozen=True)
class Tag:
    TYPENAME = "Tag"
    id: int
    name: str
    color: str | None


@dataclass(frozen=True)
class Merchant:
    TYPENAME = "Merchant"
    name: str


@dataclass
class Txn:
    """One effective ledger row. Attribute names follow the SDL in snake_case."""
    TYPENAME = "Transaction"
    date: dt.date
    abs_amount: Decimal
    amount: Decimal
    description: str
    origin: str | None
    sources: list[str]
    category: Category | None
    raw_category: Category | None
    note: str | None
    excluded: bool
    overridden: bool
    horizon: str | None
    raw_horizon: str | None
    account_id: str | None
    card_last4: str | None
    is_card_bill_payment: bool
    is_internal_transfer: bool
    is_savings: bool
    tag_links: list[tuple[Tag, dt.datetime]] = field(default_factory=list)

    @property
    def key(self):
        return self.date, self.abs_amount

    @property
    def key_str(self):
        return f"{self.date.isoformat()}:{self.abs_amount:.2f}"

    @property
    def direction(self):
        return "EXPENSE" if self.amount < 0 else "INCOME"

    @cached_property
    def merchant(self):
        return Merchant(merchant_name(self.description))

    @property
    def is_transfer(self):
        return self.is_card_bill_payment or self.is_internal_transfer

    @property
    def raw(self):
        return {"category": self.raw_category, "horizon": self.raw_horizon}


ROWS = """
SELECT s.txn_date, s.abs_amount, s.amount, s.description, s.origin, s.sources,
       c.id, c.name, c.source, sc.id, sc.name, sc.source,
       o.note, COALESCE(o.excluded, false), o.txn_date IS NOT NULL,
       COALESCE(h.key, s.record->>'horizon'), s.record->>'horizon',
       s.record->>'account_id', s.record->>'card_last4',
       COALESCE((s.record->>'card_bill_payment')::boolean, false),
       COALESCE((s.record->>'internal_transfer')::boolean, false),
       COALESCE((s.record->>'savings')::boolean, false)
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
LEFT JOIN categories c  ON c.id = COALESCE(o.category_id, s.category_id)
LEFT JOIN horizons h    ON h.id = COALESCE(o.horizon_id, s.horizon_id)
ORDER BY s.position
"""

TAG_LINKS = """
SELECT tt.txn_date, tt.abs_amount, t.id, t.name, t.color, tt.created_at
FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id ORDER BY t.name
"""


def _cat(i, name, source):
    return Category(i, name, source) if i is not None else None


class Ledger:
    """Per-request, read-only view of the ledger. Loads lazily, at most once."""

    def __init__(self, conn):
        self.conn = conn

    @cached_property
    def rows(self):
        out = []
        for (d, a, amount, desc, origin, sources, cid, cname, csrc, rid, rname, rsrc, note, excluded,
             overridden, horizon, raw_horizon, account_id, last4, bill, transfer, savings) in self.conn.execute(ROWS):
            out.append(Txn(d, Decimal(a).quantize(CENT), Decimal(amount).quantize(CENT), desc or "", origin,
                           list(sources or []), _cat(cid, cname, csrc), _cat(rid, rname, rsrc), note, excluded,
                           overridden, horizon, raw_horizon, account_id, last4, bill, transfer, savings))
        by_key = {t.key: t for t in out}
        for d, a, tid, name, color, at in self.conn.execute(TAG_LINKS):
            if (t := by_key.get((d, Decimal(a).quantize(CENT)))):
                t.tag_links.append((Tag(tid, name, color), at))
        return out

    @cached_property
    def by_key(self):
        return {t.key: t for t in self.rows}

    @cached_property
    def categories(self):
        return {i: Category(i, n, s) for i, n, s in
                self.conn.execute("SELECT id, name, source FROM categories ORDER BY name")}

    @cached_property
    def tags(self):
        return {i: Tag(i, n, c) for i, n, c in self.conn.execute("SELECT id, name, color FROM tags ORDER BY name")}

    @cached_property
    def merchants(self):
        return {t.merchant.name for t in self.rows}

    def invalidate(self):
        """Forget what was loaded, so reads after a mutation see the write."""
        for name in ("rows", "by_key", "categories", "tags", "merchants"):
            self.__dict__.pop(name, None)

    def audit(self, txn):
        return self.conn.execute(
            "SELECT id, at, actor, field, old, new FROM override_audit "
            "WHERE (txn_date, abs_amount) = (%s, %s) ORDER BY id DESC", txn.key).fetchall()


def totals(rows):
    """TransactionTotals over `rows`."""
    return {"count": len(rows), "sum": sum((t.amount for t in rows), Decimal("0.00"))}
