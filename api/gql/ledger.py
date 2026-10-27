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

from finance import offsets as offset_rules
from finance.merchants import merchant_name

CENT = Decimal("0.01")


@dataclass(frozen=True)
class Category:
    TYPENAME = "Category"
    id: int
    name: str
    source: str
    group: str | None = None
    kind: str | None = None
    usage_based: bool = False


@dataclass(frozen=True)
class Tag:
    TYPENAME = "Tag"
    id: int
    name: str
    color: str | None


@dataclass(frozen=True)
class Horizon:
    TYPENAME = "Horizon"
    id: int
    key: str
    name: str
    target_pct: float
    position: int


@dataclass(frozen=True)
class Goal:
    TYPENAME = "Goal"
    id: int
    slug: str
    description: str
    amount: Decimal
    start_date: dt.date | None
    end_date: dt.date | None
    interval: str | None
    repetitions: int
    rise: Decimal
    from_asset_id: str | None
    horizon: Horizon | None

    @property
    def name(self):
        return self.description


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
    horizon: Horizon | None
    raw_horizon: Horizon | None
    goal: Goal | None
    account_id: str | None
    card_last4: str | None
    is_card_bill_payment: bool
    is_internal_transfer: bool
    is_savings: bool
    is_round_trip: bool = False
    kind: str | None = None                # fixed / variable (transaction_kinds view)
    kind_source: str | None = None
    auto_offsets: list | None = None       # the digest's suggestion (scraped record), on a payback
    manual_offsets: list | None = None     # transaction_offsets, on a payback ([] = offsets nothing)
    tag_links: list[tuple[Tag, dt.datetime]] = field(default_factory=list)
    offset_links: list[tuple["Txn", Decimal, str]] = field(default_factory=list)   # (other row, ₪, kind)

    @property
    def offset_amount(self):
        return sum((a for _, a, _ in self.offset_links), Decimal("0.00"))

    @property
    def net_amount(self):
        return self.amount + self.offset_amount if self.amount < 0 else self.amount - self.offset_amount

    def as_ledger_row(self):
        """The dict finance/offsets.py works on."""
        return {"date": self.date.isoformat(), "amount": float(self.amount), "description": self.description,
                "origin": self.origin, "internal_transfer": self.is_internal_transfer,
                "card_bill_payment": self.is_card_bill_payment, "savings": self.is_savings,
                "auto_offsets": self.auto_offsets, "manual_offsets": self.manual_offsets,
                "offset_amount": float(self.offset_amount) or None}

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
       tk.category_id, sc.id,
       o.note, COALESCE(o.excluded, false), o.txn_date IS NOT NULL,
       COALESCE(o.horizon_id, s.horizon_id), s.horizon_id, o.goal_id,
       s.record->>'account_id', s.record->>'card_last4',
       COALESCE((s.record->>'card_bill_payment')::boolean, false),
       COALESCE((s.record->>'internal_transfer')::boolean, false),
       COALESCE((s.record->>'savings')::boolean, false),
       COALESCE((s.record->>'round_trip')::boolean, false), tk.kind, tk.kind_source,
       s.record->'auto_offsets'
FROM scraped_transactions s
JOIN transaction_kinds tk USING (txn_date, abs_amount)
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
LEFT JOIN categories sc ON sc.id = s.category_id
ORDER BY s.position
"""

TAG_LINKS = """
SELECT tt.txn_date, tt.abs_amount, t.id, t.name, t.color, tt.created_at
FROM transaction_tags tt JOIN tags t ON t.id = tt.tag_id ORDER BY t.name
"""

OFFSET_LINKS = """
SELECT payback_date, payback_abs_amount, expense_date, expense_abs_amount, amount
FROM transaction_offsets ORDER BY id
"""


class Ledger:
    """Per-request, read-only view of the ledger. Loads lazily, at most once."""

    def __init__(self, conn):
        self.conn = conn

    @cached_property
    def rows(self):
        out = []
        cats = self.categories
        for (d, a, amount, desc, origin, sources, cid, rid, note, excluded,
             overridden, hid, raw_hid, goal_id, account_id, last4, bill, transfer, savings, round_trip,
             kind, kind_source, auto) in self.conn.execute(ROWS):
            out.append(Txn(d, Decimal(a).quantize(CENT), Decimal(amount).quantize(CENT), desc or "", origin,
                           list(sources or []), cats.get(cid), cats.get(rid), note, excluded,
                           overridden, self.horizons.get(hid), self.horizons.get(raw_hid), self.goals.get(goal_id),
                           account_id, last4, bill, transfer, savings, round_trip, kind, kind_source, auto))
        by_key = {t.key: t for t in out}
        for d, a, tid, name, color, at in self.conn.execute(TAG_LINKS):
            if (t := by_key.get((d, Decimal(a).quantize(CENT)))):
                t.tag_links.append((Tag(tid, name, color), at))
        for pd, pa, ed, ea, amount in self.conn.execute(OFFSET_LINKS):
            if (t := by_key.get((pd, Decimal(pa).quantize(CENT)))):
                t.manual_offsets = t.manual_offsets or []
                if ed is not None:
                    t.manual_offsets.append({"date": ed.isoformat(), "abs_amount": float(ea),
                                             "amount": float(amount), "kind": "manual"})
        _resolve_offsets([t for t in out if not t.excluded])
        return out

    @cached_property
    def by_key(self):
        return {t.key: t for t in self.rows}

    @cached_property
    def categories(self):
        return {i: Category(i, n, s, g, k, u) for i, n, s, g, k, u in self.conn.execute(
            "SELECT c.id, c.name, c.source, g.name, c.kind, c.usage_based FROM categories c "
            "LEFT JOIN category_groups g ON g.id = c.group_id ORDER BY c.name")}

    @cached_property
    def tags(self):
        return {i: Tag(i, n, c) for i, n, c in self.conn.execute("SELECT id, name, color FROM tags ORDER BY name")}

    @cached_property
    def horizons(self):
        return {i: Horizon(i, k, n, float(p), pos) for i, k, n, p, pos in
                self.conn.execute("SELECT id, key, name, target_pct, position FROM horizons ORDER BY position")}

    @cached_property
    def goals(self):
        rows = self.conn.execute("SELECT id, slug, description, amount, start_date, end_date, interval, "
                                 "repetitions, rise, from_asset_id, horizon_id FROM goals ORDER BY end_date, id")
        return {r[0]: Goal(*r[:3], Decimal(r[3]).quantize(CENT), *r[4:8], Decimal(r[8]).quantize(CENT), r[9],
                           self.horizons.get(r[10])) for r in rows}

    @cached_property
    def merchants(self):
        return {t.merchant.name for t in self.rows}

    def invalidate(self):
        """Forget what was loaded, so reads after a mutation see the write."""
        for name in ("rows", "by_key", "categories", "tags", "horizons", "goals", "merchants"):
            self.__dict__.pop(name, None)

    def audit(self, txn):
        return self.conn.execute(
            "SELECT id, at, actor, field, old, new FROM override_audit "
            "WHERE (txn_date, abs_amount) = (%s, %s) ORDER BY id DESC", txn.key).fetchall()


def _key_of(link):
    return dt.date.fromisoformat(str(link["date"])[:10]), Decimal(str(link["abs_amount"])).quantize(CENT)


def _resolve_offsets(rows):
    """Fill `offset_links` on both sides, exactly as the digest does (finance/offsets.py).
    Excluded rows take no part, like in the `transactions` view."""
    dicts = [t.as_ledger_row() for t in rows]
    offset_rules.resolve(dicts)
    by_key = {t.key: t for t in rows}
    for t, d in zip(rows, dicts):
        t.offset_links = [(by_key[_key_of(o)], Decimal(str(o["amount"])).quantize(CENT), o["kind"])
                          for o in d.get("offsets") or []]


def offset_candidates(lg, expense, first=20):
    """Paybacks that could still offset `expense` (finance/offsets.py `candidates`)."""
    if expense.direction != "EXPENSE" or expense.is_transfer or expense.is_savings or expense.excluded:
        return []
    rows = [t for t in lg.rows if not t.excluded]
    found = offset_rules.candidates([t.as_ledger_row() for t in rows], expense.as_ledger_row(), limit=first)
    return [lg.by_key[_key_of({"date": f["date"], "abs_amount": abs(f["amount"])})] for f in found]


def totals(rows):
    """TransactionTotals over `rows`."""
    return {"count": len(rows), "sum": sum((t.amount for t in rows), Decimal("0.00"))}
