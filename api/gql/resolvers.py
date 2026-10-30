"""Resolvers for api/schema: one class per entity, bound to the schema by name (api/gql/binding.py).

    NodeResolver          global `id` and `Query.node` refetch
    └─ GroupResolver      a set of transactions with a name (merchant, category, tag):
                          `<entity>.transactions`, the root `Query.<plural>` connection with
                          edge totals, and an M:M connection to every other group entity
                          (`resolve_<other.plural>`, made up on demand by `__getattr__`)
    TransactionResolver   the ledger row itself
    NotificationResolver  the inbox (db/inbox.py): not ledger data, so its mutations never signal a rebuild
    QueryResolver         the root fields, delegating to the entity that owns the data

A resolver is a method named `resolve_<snake_field>` (the contract is generated in
api/gql/generated/resolvers.py). A field with arguments takes them validated as its last
parameter, `args: Model`; a mutation takes `inp: InputModel` and returns a thunk building the
payload, which `bind_all` wraps (validate the input with nulls kept, record the write for the
rebuild signal, refresh the ledger, echo `clientMutationId`). `RESOLVERS` maps each SDL type to
its provider(s) and `ATTRIBUTES` lists the required fields read straight off the parent; a
required field with neither makes `build()` fail at startup.

A new grouped resource is one GroupResolver subclass in ENTITIES plus its SDL; the
cross-entity fields (`Merchant.categories`, `Tag.merchants`, …) come for free.
Every resolver reads the per-request `Ledger` from the context. Fields with no resolver read the
parent's attribute or key in snake_case (`absAmount` -> `abs_amount`).
"""
import datetime as dt
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar, Generic, TypeVar

from graphql import GraphQLError
from pydantic import BaseModel

from api.schema_bindings import load_schema, snake

from .inputs import (CategoryMergeInput, CategoryUnmergeInput, AssetCreateInput, AssetUpdateInput, BulkNotificationInput, ClearTransactionOverrideInput, GoalCreateInput, GoalDeleteInput, DeleteTagInput, GroupArgs,
                     GroupOrder, LinkOffsetInput, NotificationArgs, NotificationIdInput, ResetOffsetsInput,
                     SetTransactionTagsInput, SnoozeAllNotificationsInput, SyncSourceRetryInput, TenantCreateInput, TenantMemberRemoveInput, TenantAccessSyncInput, TenantMemberSetInput, TenantSetStatusInput, TransactionArgs, TransactionOrder,
                     UnlinkOffsetInput, UnreadCountArgs, GoalUpdateInput, UpdateNotificationInput, PlanTargetsUpdateInput, UpdateTagInput,
                     UpdateTransactionInput)
from .binding import bind_all
from .generated.inputs import Direction, QueryNodeArgs, QueryTransactionByKeyArgs
from .inbox import TYPENAMES, Notification
from .sync import SyncSource
from . import tenants as tenant_store
from finance import tenancy
from .ledger import CENT, Ledger, Merchant, Txn, offset_candidates, totals
from .relay import ConnectionArgs, paginate, to_global_id, validated

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "db"))   # the shared write paths
import asset_store  # noqa: E402
import goal_store  # noqa: E402
import inbox  # noqa: E402
import offset_store  # noqa: E402
import overrides  # noqa: E402
import tags as tag_store  # noqa: E402

T = TypeVar("T")


def default_resolver(source, info, **args):
    """Dict key or attribute, by the field's name in snake_case (or as written)."""
    for key in (snake(info.field_name), info.field_name):
        if isinstance(source, dict):
            if key in source:
                return source[key]
        elif isinstance(source, BaseModel):
            if key in type(source).model_fields:
                return getattr(source, key)
        elif hasattr(source, key):
            return getattr(source, key)
    return None


def ledger(info) -> Ledger:
    return info.context["ledger"]


_TXN_SORT = {
    TransactionOrder.DATE_DESC: lambda t: (-t.date.toordinal(), -int(t.abs_amount * 100)),
    TransactionOrder.DATE_ASC: lambda t: (t.date.toordinal(), int(t.abs_amount * 100)),
    TransactionOrder.AMOUNT_DESC: lambda t: (-int(t.abs_amount * 100), -t.date.toordinal()),
    TransactionOrder.AMOUNT_ASC: lambda t: (int(t.abs_amount * 100), t.date.toordinal()),
}


def transaction_connection(rows, args: TransactionArgs):
    """A TransactionConnection over `rows` narrowed by `args.filter`, with `sum` over all pages."""
    rows = sorted((t for t in rows if args.filter.matches(t)), key=_TXN_SORT[args.order_by])
    key = _TXN_SORT[args.order_by]
    conn = paginate([{"node": t} for t in rows], lambda e: key(e["node"]), args)
    return {"edges": conn.edges, "page_info": conn.page_info, "total_count": conn.total_count,
            "sum": totals(rows)["sum"]}


class NodeResolver(Generic[T]):
    """An SDL type implementing `Node`: a global ID and a way back from it."""
    type_name: ClassVar[str]
    rebuilds: ClassVar[bool] = True   # its mutations change ledger data, so the app signals a rebuild

    def key(self, obj: T) -> str:
        """The part of the global ID after the type name."""
        raise NotImplementedError

    def fetch(self, lg: Ledger, key: str) -> T | None:
        """The object for `key`, or None (a stale or forged id is not an error)."""
        raise NotImplementedError

    def resolve_id(self, obj, info):
        return to_global_id(self.type_name, self.key(obj))

    def require(self, info, ref) -> T:
        """The object a mutation input's id names; an error if it does not exist."""
        obj = self.fetch(ledger(info), ref.key)
        if obj is None:
            raise GraphQLError(f"no such {self.type_name.lower()}")
        return obj


class GroupResolver(NodeResolver[T]):
    """A named set of transactions; see the module docstring for what it provides."""
    plural: ClassVar[str]          # field name of the root connection and of M:M fields: "categories"
    keep_empty: ClassVar[bool] = False   # list members with no transactions at the root
    siblings: ClassVar[dict[str, "GroupResolver"]] = {}   # plural -> entity, set below ENTITIES

    def groups_of(self, t: Txn) -> list[T]:
        """The groups of this entity that transaction `t` belongs to."""
        raise NotImplementedError

    def all(self, lg: Ledger) -> list[T]:
        """Every member, for the root connection when `keep_empty`."""
        return sorted({g for t in lg.rows for g in self.groups_of(t)}, key=self.label)

    def label(self, obj: T) -> str:
        """What `search` matches."""
        return obj.name

    def natural_order(self, obj: T) -> tuple:
        """NAME_ASC: by label unless the entity has an order of its own."""
        return (self.label(obj).casefold(), self.sort_id(obj))

    def contains(self, obj: T):
        return lambda t: obj in self.groups_of(t)

    def sort_id(self, obj: T):
        return getattr(obj, "id", obj.name)

    # -- connections ----------------------------------------------------------------------

    def connection(self, rows, args: GroupArgs, nodes=None):
        """Connection of this entity's members; each edge totals the `rows` in that member.

        Rows are the default view (no excluded rows, no transfers) within `args.date_range`."""
        members: dict = {}
        for t in rows:
            if t.excluded or t.is_transfer or (args.date_range and not args.date_range.contains(t.date)):
                continue
            for g in self.groups_of(t):
                members.setdefault(g, []).append(t)
        pool = nodes if nodes is not None else sorted(members, key=self.label)
        edges = [{"node": n, "totals": totals(members.get(n, []))} for n in pool
                 if not args.search or args.search in self.label(n).casefold()]
        key = self._sort_key(args.order_by)
        edges.sort(key=key)
        return paginate(edges, key, args)

    def _sort_key(self, order):
        def key(e):
            node, tot = e["node"], e["totals"]
            name, ident = self.label(node).casefold(), self.sort_id(node)
            cents = int(abs(tot["sum"]) * 100)
            return {GroupOrder.NAME_ASC: self.natural_order(node),
                    GroupOrder.COUNT_DESC: (-tot["count"], name, ident),
                    GroupOrder.TOTAL_DESC: (-cents, name, ident),
                    GroupOrder.TOTAL_ASC: (cents, name, ident)}[order]
        return key

    # -- field resolvers ------------------------------------------------------------------

    def root(self, info, args: GroupArgs):
        """`Query.<plural>`."""
        lg = ledger(info)
        return self.connection(lg.rows, args, self.all(lg) if self.keep_empty else None)

    def resolve_transactions(self, obj, info, args: TransactionArgs):
        inside = self.contains(obj)
        return transaction_connection([t for t in ledger(info).rows if inside(t)], args)

    def __getattr__(self, name):
        """`resolve_<other.plural>`: the other entity's members among this one's transactions
        (`Merchant.categories`, `Tag.merchants`, …), generated for every sibling in ENTITIES."""
        other = self.siblings.get(name.removeprefix("resolve_")) if name.startswith("resolve_") else None
        if other is None or other is self:
            raise AttributeError(name)

        def resolve(obj, info, args: GroupArgs):
            inside = self.contains(obj)
            return other.connection([t for t in ledger(info).rows if inside(t)], args)
        return resolve


class MerchantResolver(GroupResolver[Merchant]):
    type_name, plural = "Merchant", "merchants"

    def key(self, m):
        return m.name

    def fetch(self, lg, key):
        return Merchant(key) if key in lg.merchants else None

    def groups_of(self, t):
        return [t.merchant]


class CategoryResolver(GroupResolver):
    type_name, plural, keep_empty = "Category", "categories", True

    def key(self, c):
        return str(c.id)

    def fetch(self, lg, key):
        return lg.categories.get(int(key)) if key.isdigit() else None

    def groups_of(self, t):
        return [t.category] if t.category else []

    def all(self, lg):
        return list(lg.categories.values())

    def _set(self, info, cat, into):
        lg = ledger(info)
        try:
            overrides.merge_category(lg.conn, cat.name, into.name if into else None, info.context["user"])
        except ValueError as e:
            raise GraphQLError(str(e)) from None
        return lambda: {"category": self.fetch(ledger(info), str(cat.id))}

    def resolve_category_merge(self, inp: CategoryMergeInput, info):
        return self._set(info, self.require(info, inp.id), self.require(info, inp.into_id))

    def resolve_category_unmerge(self, inp: CategoryUnmergeInput, info):
        return self._set(info, self.require(info, inp.id), None)

    def resolve_merged_into(self, c, info):
        return ledger(info).categories.get(c.merged_into_id) if c.merged_into_id else None


class TagResolver(GroupResolver):
    type_name, plural, keep_empty = "Tag", "tags", True

    def key(self, tag):
        return str(tag.id)

    def fetch(self, lg, key):
        return lg.tags.get(int(key)) if key.isdigit() else None

    def groups_of(self, t):
        return [tag for tag, _ in t.tag_links]

    def all(self, lg):
        return list(lg.tags.values())

    def resolve_update_tag(self, inp: UpdateTagInput, info):
        tag = self.require(info, inp.id)
        conn = ledger(info).conn
        if inp.name and tag_store.tag_name_taken(conn, inp.name, tag.id):
            raise GraphQLError("a tag with that name already exists")
        changes = {f: getattr(inp, f) for f in inp.model_fields_set & {"name", "color"} if f != "name" or inp.name}
        tag_store.update_tag(conn, tag.id, **changes)
        return lambda: {"tag": self.fetch(ledger(info), str(tag.id))}

    def resolve_delete_tag(self, inp: DeleteTagInput, info):
        tag = self.require(info, inp.id)
        tag_store.delete_tag(ledger(info).conn, tag.id)
        return lambda: {"deleted_tag_id": to_global_id(self.type_name, str(tag.id))}


class HorizonResolver(GroupResolver):
    type_name, plural, keep_empty = "Horizon", "horizons", True

    def __init__(self, goals: "GoalResolver"):
        self.goal_resolver = goals

    def key(self, h):
        return str(h.id)

    def fetch(self, lg, key):
        return lg.horizons.get(int(key)) if key.isdigit() else None

    def groups_of(self, t):
        return [t.horizon] if t.horizon else []

    def all(self, lg):
        return list(lg.horizons.values())

    def natural_order(self, h):
        return (h.position, h.id)

    def resolve_goals(self, h, info, args: GroupArgs):
        """The goals assigned to `h` (not derived from transactions), with each goal's totals."""
        lg = ledger(info)
        mine = [g for g in lg.goals.values() if g.horizon == h]
        return self.goal_resolver.connection(lg.rows, args, mine)

class GoalResolver(GroupResolver):
    type_name, plural, keep_empty = "Goal", "goals", True

    def key(self, g):
        return str(g.id)

    def fetch(self, lg, key):
        return lg.goals.get(int(key)) if key.isdigit() else None

    def groups_of(self, t):
        return [t.goal] if t.goal else []

    def all(self, lg):
        return list(lg.goals.values())

    def label(self, g):
        return g.description

    def _refetched(self, info, goal_id):
        return lambda: {"goal": self.fetch(ledger(info), str(goal_id))}

    def resolve_goal_create(self, inp: GoalCreateInput, info):
        g = goal_store.create_goal(ledger(info).conn, inp.description.strip(), inp.amount, **inp.fields())
        return self._refetched(info, g["id"])

    def resolve_goal_update(self, inp: GoalUpdateInput, info):
        g = self.require(info, inp.id)
        changes = inp.changes()
        if not changes:
            raise GraphQLError("send at least one goal field")
        goal_store.update_goal(ledger(info).conn, g.id, **changes)
        return self._refetched(info, g.id)

    def resolve_goal_delete(self, inp: GoalDeleteInput, info):
        g = self.require(info, inp.id)
        goal_store.delete_goal(ledger(info).conn, g.id)
        return lambda: {"entity_id": to_global_id(self.type_name, str(g.id))}


class TransactionResolver(NodeResolver[Txn]):
    type_name = "Transaction"

    def __init__(self, goals: GoalResolver):
        self.goal_resolver = goals

    def key(self, t):
        return t.key_str

    def fetch(self, lg, key):
        try:
            d, a = key.split(":")
            return lg.by_key.get((dt.date.fromisoformat(d), Decimal(a).quantize(CENT)))
        except (ValueError, InvalidOperation):
            return None

    def _refetched(self, info, t):
        return lambda: {"transaction": ledger(info).by_key[t.key]}

    def resolve_update_transaction(self, inp: UpdateTransactionInput, info):
        t = self.require(info, inp.id)
        if inp.goal_id is not None:
            self.goal_resolver.require(info, inp.goal_id)
        changes = inp.changes()
        if not changes:
            raise GraphQLError("send at least one of category, note, excluded, horizon, goalId")
        overrides.patch(ledger(info).conn, t.key, changes, info.context["user"])
        return self._refetched(info, t)

    def resolve_clear_transaction_override(self, inp: ClearTransactionOverrideInput, info):
        t = self.require(info, inp.id)
        overrides.reset(ledger(info).conn, t.key, info.context["user"])
        return self._refetched(info, t)

    def resolve_set_transaction_tags(self, inp: SetTransactionTagsInput, info):
        t = self.require(info, inp.id)
        tag_store.set_tags(ledger(info).conn, t.key, inp.tags, info.context["user"])
        return self._refetched(info, t)

    # --- offsets (קיזוז) ---------------------------------------------------------

    def _pair(self, inp, info):
        p, e = self.require(info, inp.payback_id), self.require(info, inp.expense_id)
        for t, direction, what in ((p, "INCOME", "payback"), (e, "EXPENSE", "expense")):
            if t.direction != direction or t.is_transfer or t.is_savings or t.excluded:
                raise GraphQLError(f"the {what} must be {'money in' if direction == 'INCOME' else 'money out'}, "
                                   "not a transfer, savings or a hidden row")
        return p, e

    def _links_without(self, p, e):
        """The payback's current effective links, minus the one to `e`, as stored links."""
        return [(o.key, amount) for o, amount, _ in p.offset_links if o.key != e.key]

    def _offset_payload(self, info, p, e):
        return lambda: {"payback": ledger(info).by_key[p.key], "expense": ledger(info).by_key[e.key]}

    def resolve_link_offset(self, inp: LinkOffsetInput, info):
        p, e = self._pair(inp, info)
        current = {o.key: a for o, a, _ in p.offset_links}.get(e.key, Decimal("0.00"))
        p_free = p.abs_amount - p.offset_amount + current
        e_free = e.abs_amount - e.offset_amount + current
        amount = inp.amount if inp.amount is not None else min(p_free, e_free)
        if amount <= 0:
            raise GraphQLError("nothing left to offset: the payback or the expense is already fully netted")
        if amount > p_free or amount > e_free:
            raise GraphQLError(f"at most ₪{min(p_free, e_free):.2f} is left to offset between these two")
        offset_store.set_offsets(ledger(info).conn, p.key, [*self._links_without(p, e), (e.key, amount)],
                                 info.context["user"])
        return self._offset_payload(info, p, e)

    def resolve_unlink_offset(self, inp: UnlinkOffsetInput, info):
        p, e = self.require(info, inp.payback_id), self.require(info, inp.expense_id)
        if not any(o.key == e.key for o, _, _ in p.offset_links):
            raise GraphQLError("these two are not offset against each other")
        offset_store.set_offsets(ledger(info).conn, p.key, self._links_without(p, e), info.context["user"])
        return self._offset_payload(info, p, e)

    def resolve_reset_offsets(self, inp: ResetOffsetsInput, info):
        p = self.require(info, inp.payback_id)
        offset_store.reset_offsets(ledger(info).conn, p.key, info.context["user"])
        return lambda: {"payback": ledger(info).by_key[p.key]}

    def resolve_offsets(self, t, info):
        return [{"transaction": o, "amount": amount, "kind": kind} for o, amount, kind in t.offset_links]

    def resolve_offset_candidates(self, t, info, args: ConnectionArgs):
        """Ranked (same merchant, then nearest date), so the edge order is the rank."""
        rows = offset_candidates(ledger(info), t, 50)
        rank = {r.key: i for i, r in enumerate(rows)}
        conn = paginate([{"node": r} for r in rows], lambda e: (rank[e["node"].key],), args)
        return {"edges": conn.edges, "page_info": conn.page_info, "total_count": conn.total_count,
                "sum": totals(rows)["sum"]}

    def resolve_tags(self, t, info, args: ConnectionArgs):
        """Edge totals are scoped to this one transaction; `taggedAt` is when the link was made."""
        edges = [{"node": tag, "totals": totals([t]), "tagged_at": at} for tag, at in t.tag_links]
        key = lambda e: (e["node"].name.casefold(), e["node"].id)  # noqa: E731
        return paginate(sorted(edges, key=key), key, args)

    def resolve_audit_log(self, t, info, args: ConnectionArgs):
        edges = [{"node": {"at": at, "actor": actor, "field": f, "old": old, "new": new}, "id": i}
                 for i, at, actor, f, old, new in ledger(info).audit(t)]
        return paginate(edges, lambda e: (-e["id"],), args)

    def resolve_offsets_manual(self, t, info):
        return t.manual_offsets is not None


def _now():
    return dt.datetime.now(dt.timezone.utc)


class NotificationResolver(NodeResolver[Notification]):
    """The inbox. The global id says "Notification" for every subtype, since which one an item
    is follows its subject and can change; `Query.node` returns whichever fits."""
    type_name = "Notification"
    rebuilds = False

    def key(self, n):
        return n.id

    def fetch(self, lg, key):
        row = inbox.get(lg.conn, key)
        return Notification.from_row(row) if row else None

    def _set(self, info, ref, changes):
        n = self.require(info, ref)
        row = inbox.update(ledger(info).conn, n.id, changes, now=_now())
        return lambda: {"notification": Notification.from_row(row)}

    def resolve_update_notification(self, inp: UpdateNotificationInput, info):
        changes = inp.changes(_now())
        if not changes:
            raise GraphQLError("send read and/or snoozedUntilAt")
        return self._set(info, inp.id, changes)

    def resolve_archive_notification(self, inp: NotificationIdInput, info):
        return self._set(info, inp.id, {"archived_at": _now()})

    def resolve_unarchive_notification(self, inp: NotificationIdInput, info):
        return self._set(info, inp.id, {"archived_at": None})

    def _bulk(self, info, run):
        count = run(ledger(info).conn)
        return lambda: {"count": count}

    def resolve_mark_all_notifications_read(self, inp: BulkNotificationInput, info):
        return self._bulk(info, lambda conn: inbox.mark_all_read(conn, inp.categories()))

    def resolve_archive_all_notifications(self, inp: BulkNotificationInput, info):
        return self._bulk(info, lambda conn: inbox.archive_all(conn, inp.categories()))

    def resolve_snooze_all_notifications(self, inp: SnoozeAllNotificationsInput, info):
        return self._bulk(info, lambda conn: inbox.snooze_all(conn, inp.snoozed_until_at, inp.categories()))

    def listing(self, info, args: NotificationArgs):
        """`Query.notifications`."""
        f = args.filter
        rows = inbox.select(ledger(info).conn, [c.value for c in f.category] if f.category is not None else None,
                            f.unread, f.include_archived, f.include_resolved, f.include_snoozed)
        edges = sorted(({"node": Notification.from_row(r)} for r in rows), key=lambda e: e["node"].sort_key)
        return paginate(edges, lambda e: e["node"].sort_key, args)

    def unread_count(self, info, args: UnreadCountArgs):
        """`Query.notificationsUnreadCount`."""
        categories = args.category
        return inbox.unread_count(ledger(info).conn, [c.value for c in categories] if categories is not None else None)

    def resolve_transaction(self, n, info):
        key = n.transaction_key
        return ledger(info).by_key.get(key) if key else None


class PlanTargetsResolver(NodeResolver):
    """`Query.planTargets` and `planTargetsUpdate`: three amounts, not a Node (no id, no refetch)."""
    type_name = "PlanTargets"

    @staticmethod
    def read(conn):
        t = goal_store.get_targets(conn)
        return {"emergency_fund": t["emergency_fund_target"], "inheritance": t["inheritance_target"],
                "retirement": t["retirement_target"]}

    def query(self, info):
        """`Query.planTargets`."""
        return self.read(ledger(info).conn)

    def resolve_plan_targets_update(self, inp: PlanTargetsUpdateInput, info):
        changes = inp.changes()
        if not changes:
            raise GraphQLError("send at least one target")
        goal_store.set_targets(ledger(info).conn, **changes)
        return lambda: {"plan_targets": self.read(ledger(info).conn)}

class AssetResolver(NodeResolver[dict]):
    """`Query.assets`, `assetCreate`, `assetUpdate` (db/asset_store.py). A new value changes
    the snapshot totals, so these signal a ledger rebuild."""
    type_name = "Asset"

    @staticmethod
    def _typed(a):
        """asset_store's JSON-ready dict with the date/time/amount types the scalars serialize."""
        return {**a, "value": Decimal(str(a["value"])), "valued_at": dt.date.fromisoformat(a["valued_at"]),
                "updated_at": dt.datetime.fromisoformat(a["updated_at"])}

    def key(self, a):
        return str(a["id"])

    def fetch(self, lg, key):
        a = asset_store.get_asset(lg.conn, int(key)) if key.isdigit() else None
        return self._typed(a) if a else None

    def listing(self, info, args: ConnectionArgs):
        """`Query.assets`."""
        rows = [self._typed(x) for x in asset_store.all_assets(ledger(info).conn)]   # oldest first
        return paginate([{"node": x} for x in rows], lambda e: (e["node"]["id"],), args)

    def resolve_asset_create(self, inp: AssetCreateInput, info):
        try:
            a = asset_store.create_asset(ledger(info).conn, inp.kind.value, inp.label.strip(), inp.value,
                                         inp.valued_at)
        except ValueError as e:
            raise GraphQLError(str(e)) from None
        return lambda: {"asset": self._typed(a)}

    def resolve_asset_update(self, inp: AssetUpdateInput, info):
        a = self.require(info, inp.id)
        changes = inp.changes()
        if not changes:
            raise GraphQLError("send at least one asset field")
        if "label" in changes:
            changes["label"] = changes["label"].strip()
        try:
            out = asset_store.update_asset(ledger(info).conn, a["id"], **changes)
        except ValueError as e:
            raise GraphQLError(str(e)) from None
        return lambda: {"asset": self._typed(out)}

class SyncSourceResolver(NodeResolver[SyncSource]):
    """Each source's latest run (sync_status). Retrying starts a sync on the Mac and changes no
    ledger data here (the sync publishes when it finishes), so it never signals a rebuild."""
    type_name = "SyncSource"
    rebuilds = False

    def key(self, s):
        return s.source

    def fetch(self, lg, key):
        return SyncSource.get(lg.conn, key)

    def resolve_sync_source_retry(self, inp: SyncSourceRetryInput, info):
        s = self.require(info, inp.id)
        if not s.retry_from:
            raise GraphQLError("the last sync of this source did not fail")
        rebuilder = info.context.get("rebuilder")
        if rebuilder is None or not rebuilder.retry(s.source, s.retry_from):
            raise GraphQLError("the sync worker is not reachable")
        return lambda: {"sync_source": s}

    def listing(self, info, args: ConnectionArgs):
        """`Query.syncSources`."""
        rows = SyncSource.all(ledger(info).conn)   # ordered by source
        return paginate([{"node": s} for s in rows], lambda e: (e["node"].source,), args)

class TenantResolver(NodeResolver[dict]):
    """`Query.tenants` and the tenant mutations, for platform admins only: the registry of
    tenants and members. They change no ledger data, so they never signal a rebuild, and
    `node(id)` does not serve tenants (not in NODES)."""
    type_name = "Tenant"
    rebuilds = False

    @staticmethod
    def admin(info):
        if not tenancy.is_platform_admin(info.context["user"]):
            raise GraphQLError("only a platform admin can manage tenants")

    def key(self, t):
        return str(t["id"])

    def fetch(self, lg, key):
        return tenant_store.get(lg.conn, key)

    def _run(self, info, tenant_id, fn, *args):
        conn = ledger(info).conn
        try:
            fn(conn, tenant_id, *args)
        except ValueError as e:
            raise GraphQLError(str(e)) from None
        return lambda: {"tenant": tenant_store.get(conn, tenant_id)}

    def resolve_tenant_create(self, inp: TenantCreateInput, info):
        self.admin(info)
        conn = ledger(info).conn
        caller_tenant = info.context["tenant_id"]
        try:
            tid, horizons = tenant_store.create(conn, inp.slug, inp.name.strip())
            tenant_store.set_member(conn, tid, inp.owner_email, "owner")
            tenant_store.seed_horizons(conn, tid, horizons)
        except ValueError as e:
            raise GraphQLError(str(e)) from None
        finally:
            tenancy.bind(conn, caller_tenant, local=False)   # back to the caller's own tenant
        return lambda: {"tenant": tenant_store.get(conn, tid)}

    def resolve_tenant_member_set(self, inp: TenantMemberSetInput, info):
        self.admin(info)
        t = self.require(info, inp.id)
        return self._run(info, t["id"], tenant_store.set_member, inp.email, inp.role)

    def resolve_tenant_member_remove(self, inp: TenantMemberRemoveInput, info):
        self.admin(info)
        t = self.require(info, inp.id)
        return self._run(info, t["id"], tenant_store.remove_member, inp.email)

    def resolve_tenant_set_status(self, inp: TenantSetStatusInput, info):
        self.admin(info)
        t = self.require(info, inp.id)
        return self._run(info, t["id"], tenant_store.set_status, inp.status)

    def resolve_tenant_access_sync(self, inp: TenantAccessSyncInput, info):
        self.admin(info)
        t = self.require(info, inp.id)
        rebuilder = info.context.get("rebuilder")
        if rebuilder is None:
            raise GraphQLError("the sync worker is not reachable")
        ok, message = rebuilder.sync_tenant_access(str(t["id"]), inp.email)
        if not ok:
            raise GraphQLError(message)
        return lambda: {"message": message}

    def listing(self, info):
        """`Query.tenants`."""
        self.admin(info)
        return tenant_store.all_tenants(ledger(info).conn)

GOALS = GoalResolver()
MERCHANTS, CATEGORIES, TAGS, HORIZONS = MerchantResolver(), CategoryResolver(), TagResolver(), HorizonResolver(GOALS)
ENTITIES: list[GroupResolver] = [MERCHANTS, CATEGORIES, TAGS, HORIZONS, GOALS]
GroupResolver.siblings = {e.plural: e for e in ENTITIES}
TRANSACTIONS = TransactionResolver(GOALS)
NOTIFICATIONS = NotificationResolver()
SYNC_SOURCES = SyncSourceResolver()
PLAN_TARGETS = PlanTargetsResolver()
ASSETS = AssetResolver()
TENANTS = TenantResolver()
NODES: dict[str, NodeResolver] = {r.type_name: r for r in [TRANSACTIONS, *ENTITIES, NOTIFICATIONS, SYNC_SOURCES,
                                                           ASSETS]}
class QueryResolver:
    """The root fields: each hands its validated arguments to the entity that owns the data."""

    def resolve_node(self, _, info, args: QueryNodeArgs):
        r = NODES.get(args.id.type_name)
        return r.fetch(ledger(info), args.id.key) if r else None

    def resolve_snapshot(self, _, info):
        raise GraphQLError("snapshot is not served by the API yet")

    def resolve_transaction_by_key(self, _, info, args: QueryTransactionByKeyArgs):
        return ledger(info).by_key.get((args.date, Decimal(args.abs_amount).quantize(CENT)))

    def _transactions(self, info, args: TransactionArgs, direction=None):
        if direction:   # `expenses` / `incomes` are `transactions` with the direction filter set
            args = args.model_copy(update={"filter": args.filter.model_copy(update={"direction": direction})})
        return transaction_connection(ledger(info).rows, args)

    def resolve_transactions(self, _, info, args: TransactionArgs):
        return self._transactions(info, args)

    def resolve_expenses(self, _, info, args: TransactionArgs):
        return self._transactions(info, args, Direction.EXPENSE)

    def resolve_incomes(self, _, info, args: TransactionArgs):
        return self._transactions(info, args, Direction.INCOME)

    def resolve_merchants(self, _, info, args: GroupArgs):
        return MERCHANTS.root(info, args)

    def resolve_categories(self, _, info, args: GroupArgs):
        return CATEGORIES.root(info, args)

    def resolve_tags(self, _, info, args: GroupArgs):
        return TAGS.root(info, args)

    def resolve_horizons(self, _, info, args: GroupArgs):
        return HORIZONS.root(info, args)

    def resolve_goals(self, _, info, args: GroupArgs):
        return GOALS.root(info, args)

    def resolve_plan_targets(self, _, info):
        return PLAN_TARGETS.query(info)

    def resolve_tenants(self, _, info):
        return TENANTS.listing(info)

    def resolve_assets(self, _, info, args: ConnectionArgs):
        return ASSETS.listing(info, args)

    def resolve_sync_sources(self, _, info, args: ConnectionArgs):
        return SYNC_SOURCES.listing(info, args)

    def resolve_notifications(self, _, info, args: NotificationArgs):
        return NOTIFICATIONS.listing(info, args)

    def resolve_notifications_unread_count(self, _, info, args: UnreadCountArgs):
        return NOTIFICATIONS.unread_count(info, args)


RESOLVERS: dict[str, object] = {
    "Query": QueryResolver(),
    "Mutation": [TRANSACTIONS, CATEGORIES, TAGS, GOALS, NOTIFICATIONS, SYNC_SOURCES, PLAN_TARGETS, ASSETS, TENANTS],
    "Transaction": TRANSACTIONS, "Asset": ASSETS, "SyncSource": SYNC_SOURCES, "Tenant": TENANTS,
    **{e.type_name: e for e in ENTITIES},
    **{name: NOTIFICATIONS for name in TYPENAMES},   # `id` is a field of every subtype
}
# Required fields read straight off the parent row (a Txn attribute, a notification's subject, a
# stored column) by the default resolver. bind_all rejects an entry that is not such a field.
ATTRIBUTES: dict[str, frozenset[str]] = {
    "Asset": frozenset({"kind", "valuationSource"}),
    "Transaction": frozenset({"absAmount", "direction", "merchant", "category", "kind", "kindSource", "excluded",
                              "horizon", "goal", "netAmount", "raw"}),
    "Category": frozenset({"source", "group", "kind"}),
    "Horizon": frozenset({"key"}), "Goal": frozenset({"interval", "horizon"}),
    "CashflowNotification": frozenset({"date"}),
    "BudgetNotification": frozenset({"budgetCategories", "cycleStart"}),
    "BillNotification": frozenset({"billName", "dueDate"}),
    "ServiceNotification": frozenset({"services"}), "SyncNotification": frozenset({"sources"}),
}


# --- scalars and enums -------------------------------------------------------------------

def _money(v):
    return f"{Decimal(str(v)).quantize(CENT):.2f}"


def _parse_money(v):
    try:
        return Decimal(str(v)).quantize(CENT)
    except (InvalidOperation, ValueError):
        raise GraphQLError(f"not an amount: {v!r}") from None


def _parse_date(v):
    try:
        return dt.date.fromisoformat(v)
    except (TypeError, ValueError):
        raise GraphQLError(f"not an ISO date: {v!r}") from None


def _parse_datetime(v):
    """An ISO 8601 timestamp; one without an offset is taken as UTC."""
    try:
        parsed = dt.datetime.fromisoformat(v)
    except (TypeError, ValueError):
        raise GraphQLError(f"not an ISO 8601 timestamp: {v!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def build():
    """The executable schema: the SDL with resolvers, scalars and enum values attached."""
    schema = load_schema()
    t = schema.type_map
    t["Money"].serialize = _money
    t["Date"].serialize = lambda v: v.isoformat()
    t["Date"].parse_value = _parse_date
    t["DateTime"].serialize = lambda v: v.isoformat()
    t["DateTime"].parse_value = _parse_datetime
    t["JSON"].serialize = lambda v: v
    t["Money"].parse_value = _parse_money
    for enum in ("HorizonKey", "CategorySource", "GoalInterval", "OffsetKind", "ExpenseKind", "KindSource",
                 "AssetKind", "ValuationSource", "SyncRetryPoint", "TenantRole", "TenantStatus"):
        for name, value in t[enum].values.items():
            value.value = name.lower()
    for name in t["NotificationCategory"].values:
        t["NotificationCategory"].values[name].value = name
    for name, value in t["NotificationSeverity"].values.items():
        value.value = name.lower()
    t["Node"].resolve_type = lambda obj, *_: obj.TYPENAME

    t["Notification"].resolve_type = lambda obj, *_: obj.TYPENAME
    bind_all(schema, RESOLVERS, ATTRIBUTES)
    return schema
