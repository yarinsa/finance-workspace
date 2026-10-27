"""Resolvers for api/schema: one class per entity, wired onto the schema built from the SDL.

    NodeResolver          global `id` and `Query.node` refetch
    └─ GroupResolver      a set of transactions with a name (merchant, category, tag):
                          `<entity>.transactions`, the root `Query.<plural>` connection with
                          edge totals, and an M:M connection to every other group entity
    TransactionResolver   the ledger row itself
    NotificationResolver  the inbox (db/inbox.py): not ledger data, so its mutations never signal a rebuild

Mutations live on the entity they change: a resolver lists them in `mutations()` as
{field: (input model, method)}, and `NodeResolver.bind` wraps each one (validate the
input with nulls kept, record the write for the rebuild signal, refresh the ledger,
echo `clientMutationId`).

A new grouped resource is one GroupResolver subclass in ENTITIES plus its SDL; the
cross-entity fields (`Merchant.categories`, `Tag.merchants`, …) come for free.
Every resolver validates its arguments through a Pydantic model (api/gql/inputs.py)
and reads the per-request `Ledger` from the context. Fields with no resolver read the
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
                     SetTransactionTagsInput, SnoozeAllNotificationsInput, SyncSourceRetryInput, TransactionArgs, TransactionOrder,
                     UnlinkOffsetInput, UnreadCountArgs, GoalUpdateInput, UpdateNotificationInput, PlanTargetsUpdateInput, UpdateTagInput,
                     UpdateTransactionInput)
from .inbox import TYPENAMES, Notification
from .sync import SyncSource
from .ledger import CENT, Ledger, Merchant, Txn, offset_candidates, totals
from .relay import ConnectionArgs, GlobalId, paginate, to_global_id, validated

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

    def mutations(self) -> dict:
        """{Mutation field: (input model, method(input, info) -> payload dict)}."""
        return {}

    def _mutation(self, model, method):
        """The resolver of a mutation field. Linear-style fields take `id` as its own argument
        (merged into the input), Relay-style ones carry it in `input`."""
        def resolve(_, info, input=None, id=None):
            args = {**(input or {}), **({} if id is None else {"id": id})}
            inp = validated(model, args, keep_null=True)
            payload = method(inp, info)
            if self.rebuilds:
                info.context["writes"] += 1
                ledger(info).invalidate()
            return {"client_mutation_id": inp.client_mutation_id, "success": True, **payload()}
        return resolve

    def bind(self, schema):
        schema.type_map[self.type_name].fields["id"].resolve = self.resolve_id
        for field, (model, method) in self.mutations().items():
            schema.mutation_type.fields[field].resolve = self._mutation(model, method)


class GroupResolver(NodeResolver[T]):
    """A named set of transactions; see the module docstring for what it provides."""
    plural: ClassVar[str]          # field name of the root connection and of M:M fields: "categories"
    keep_empty: ClassVar[bool] = False   # list members with no transactions at the root

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

    def resolve_root(self, _, info, **args):
        lg = ledger(info)
        return self.connection(lg.rows, validated(GroupArgs, args), self.all(lg) if self.keep_empty else None)

    def resolve_transactions(self, obj, info, **args):
        inside = self.contains(obj)
        return transaction_connection([t for t in ledger(info).rows if inside(t)], validated(TransactionArgs, args))

    def related(self, other: "GroupResolver"):
        """`<this>.<other.plural>`: the other entity's members among this one's transactions."""
        def resolve(obj, info, **args):
            inside = self.contains(obj)
            return other.connection([t for t in ledger(info).rows if inside(t)], validated(GroupArgs, args))
        return resolve

    def bind(self, schema, others=()):
        super().bind(schema)
        fields = schema.type_map[self.type_name].fields
        fields["transactions"].resolve = self.resolve_transactions
        schema.query_type.fields[self.plural].resolve = self.resolve_root
        for other in others:
            if other is not self and other.plural in fields:
                fields[other.plural].resolve = self.related(other)


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

    def mutations(self):
        return {"categoryMerge": (CategoryMergeInput, self.merge),
                "categoryUnmerge": (CategoryUnmergeInput, self.unmerge)}

    def _set(self, info, cat, into):
        lg = ledger(info)
        try:
            overrides.merge_category(lg.conn, cat.name, into.name if into else None, info.context["user"])
        except ValueError as e:
            raise GraphQLError(str(e)) from None
        return lambda: {"category": self.fetch(ledger(info), str(cat.id))}

    def merge(self, inp, info):
        return self._set(info, self.require(info, inp.id), self.require(info, inp.into_id))

    def unmerge(self, inp, info):
        return self._set(info, self.require(info, inp.id), None)

    def bind(self, schema, others=()):
        super().bind(schema, others)
        schema.type_map[self.type_name].fields["mergedInto"].resolve = (
            lambda c, info: ledger(info).categories.get(c.merged_into_id) if c.merged_into_id else None)


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

    def mutations(self):
        return {"updateTag": (UpdateTagInput, self.update), "deleteTag": (DeleteTagInput, self.delete)}

    def update(self, inp, info):
        tag = self.require(info, inp.id)
        conn = ledger(info).conn
        if inp.name and tag_store.tag_name_taken(conn, inp.name, tag.id):
            raise GraphQLError("a tag with that name already exists")
        changes = {f: getattr(inp, f) for f in inp.model_fields_set & {"name", "color"} if f != "name" or inp.name}
        tag_store.update_tag(conn, tag.id, **changes)
        return lambda: {"tag": self.fetch(ledger(info), str(tag.id))}

    def delete(self, inp, info):
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

    def resolve_goals(self, h, info, **args):
        """The goals assigned to `h` (not derived from transactions), with each goal's totals."""
        lg = ledger(info)
        mine = [g for g in lg.goals.values() if g.horizon == h]
        return self.goal_resolver.connection(lg.rows, validated(GroupArgs, args), mine)

    def bind(self, schema, others=()):
        super().bind(schema, others)
        schema.type_map[self.type_name].fields["goals"].resolve = self.resolve_goals


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

    def mutations(self):
        return {"goalCreate": (GoalCreateInput, self.create), "goalUpdate": (GoalUpdateInput, self.update),
                "goalDelete": (GoalDeleteInput, self.delete)}

    def _refetched(self, info, goal_id):
        return lambda: {"goal": self.fetch(ledger(info), str(goal_id))}

    def create(self, inp, info):
        g = goal_store.create_goal(ledger(info).conn, inp.description.strip(), inp.amount, **inp.fields())
        return self._refetched(info, g["id"])

    def update(self, inp, info):
        g = self.require(info, inp.id)
        changes = inp.changes()
        if not changes:
            raise GraphQLError("send at least one goal field")
        goal_store.update_goal(ledger(info).conn, g.id, **changes)
        return self._refetched(info, g.id)

    def delete(self, inp, info):
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

    def mutations(self):
        return {"updateTransaction": (UpdateTransactionInput, self.update),
                "clearTransactionOverride": (ClearTransactionOverrideInput, self.clear),
                "setTransactionTags": (SetTransactionTagsInput, self.set_tags),
                "linkOffset": (LinkOffsetInput, self.link_offset),
                "unlinkOffset": (UnlinkOffsetInput, self.unlink_offset),
                "resetOffsets": (ResetOffsetsInput, self.reset_offsets)}

    def _refetched(self, info, t):
        return lambda: {"transaction": ledger(info).by_key[t.key]}

    def update(self, inp, info):
        t = self.require(info, inp.id)
        if inp.goal_id is not None:
            self.goal_resolver.require(info, inp.goal_id)
        changes = inp.changes()
        if not changes:
            raise GraphQLError("send at least one of category, note, excluded, horizon, goalId")
        overrides.patch(ledger(info).conn, t.key, changes, info.context["user"])
        return self._refetched(info, t)

    def clear(self, inp, info):
        t = self.require(info, inp.id)
        overrides.reset(ledger(info).conn, t.key, info.context["user"])
        return self._refetched(info, t)

    def set_tags(self, inp, info):
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

    def link_offset(self, inp, info):
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

    def unlink_offset(self, inp, info):
        p, e = self.require(info, inp.payback_id), self.require(info, inp.expense_id)
        if not any(o.key == e.key for o, _, _ in p.offset_links):
            raise GraphQLError("these two are not offset against each other")
        offset_store.set_offsets(ledger(info).conn, p.key, self._links_without(p, e), info.context["user"])
        return self._offset_payload(info, p, e)

    def reset_offsets(self, inp, info):
        p = self.require(info, inp.payback_id)
        offset_store.reset_offsets(ledger(info).conn, p.key, info.context["user"])
        return lambda: {"payback": ledger(info).by_key[p.key]}

    def resolve_offsets(self, t, info):
        return [{"transaction": o, "amount": amount, "kind": kind} for o, amount, kind in t.offset_links]

    def resolve_offset_candidates(self, t, info, **args):
        """Ranked (same merchant, then nearest date), so the edge order is the rank."""
        a = validated(ConnectionArgs, args)
        rows = offset_candidates(ledger(info), t, 50)
        rank = {r.key: i for i, r in enumerate(rows)}
        conn = paginate([{"node": r} for r in rows], lambda e: (rank[e["node"].key],), a)
        return {"edges": conn.edges, "page_info": conn.page_info, "total_count": conn.total_count,
                "sum": totals(rows)["sum"]}

    def resolve_by_key(self, _, info, date, absAmount):
        return ledger(info).by_key.get((date, Decimal(absAmount).quantize(CENT)))

    def resolve_list(self, direction=None):
        """`Query.transactions` / `expenses` / `incomes`."""
        def resolve(_, info, **args):
            if direction:
                args = {**args, "filter": {**(args.get("filter") or {}), "direction": direction}}
            return transaction_connection(ledger(info).rows, validated(TransactionArgs, args))
        return resolve

    def resolve_tags(self, t, info, **args):
        """Edge totals are scoped to this one transaction; `taggedAt` is when the link was made."""
        a = validated(ConnectionArgs, args)
        edges = [{"node": tag, "totals": totals([t]), "tagged_at": at} for tag, at in t.tag_links]
        key = lambda e: (e["node"].name.casefold(), e["node"].id)  # noqa: E731
        return paginate(sorted(edges, key=key), key, a)

    def resolve_audit_log(self, t, info, **args):
        a = validated(ConnectionArgs, args)
        edges = [{"node": {"at": at, "actor": actor, "field": f, "old": old, "new": new}, "id": i}
                 for i, at, actor, f, old, new in ledger(info).audit(t)]
        return paginate(edges, lambda e: (-e["id"],), a)

    def bind(self, schema):
        super().bind(schema)
        q, fields = schema.query_type.fields, schema.type_map[self.type_name].fields
        q["transactionByKey"].resolve = self.resolve_by_key
        q["transactions"].resolve = self.resolve_list()
        q["expenses"].resolve = self.resolve_list("EXPENSE")
        q["incomes"].resolve = self.resolve_list("INCOME")
        fields["tags"].resolve = self.resolve_tags
        fields["auditLog"].resolve = self.resolve_audit_log
        fields["offsets"].resolve = self.resolve_offsets
        fields["offsetCandidates"].resolve = self.resolve_offset_candidates
        fields["offsetsManual"].resolve = lambda t, info: t.manual_offsets is not None


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

    def mutations(self):
        return {"updateNotification": (UpdateNotificationInput, self.update),
                "archiveNotification": (NotificationIdInput, self.archive),
                "unarchiveNotification": (NotificationIdInput, self.unarchive),
                "markAllNotificationsRead": (BulkNotificationInput, self.read_all),
                "archiveAllNotifications": (BulkNotificationInput, self.archive_all),
                "snoozeAllNotifications": (SnoozeAllNotificationsInput, self.snooze_all)}

    def _set(self, info, ref, changes):
        n = self.require(info, ref)
        row = inbox.update(ledger(info).conn, n.id, changes, now=_now())
        return lambda: {"notification": Notification.from_row(row)}

    def update(self, inp, info):
        changes = inp.changes(_now())
        if not changes:
            raise GraphQLError("send read and/or snoozedUntilAt")
        return self._set(info, inp.id, changes)

    def archive(self, inp, info):
        return self._set(info, inp.id, {"archived_at": _now()})

    def unarchive(self, inp, info):
        return self._set(info, inp.id, {"archived_at": None})

    def _bulk(self, info, run):
        count = run(ledger(info).conn)
        return lambda: {"count": count}

    def read_all(self, inp, info):
        return self._bulk(info, lambda conn: inbox.mark_all_read(conn, inp.categories()))

    def archive_all(self, inp, info):
        return self._bulk(info, lambda conn: inbox.archive_all(conn, inp.categories()))

    def snooze_all(self, inp, info):
        return self._bulk(info, lambda conn: inbox.snooze_all(conn, inp.snoozed_until_at, inp.categories()))

    def resolve_list(self, _, info, **args):
        a = validated(NotificationArgs, args)
        f = a.filter
        rows = inbox.select(ledger(info).conn, [c.value for c in f.category] if f.category is not None else None,
                            f.unread, f.include_archived, f.include_resolved, f.include_snoozed)
        edges = sorted(({"node": Notification.from_row(r)} for r in rows), key=lambda e: e["node"].sort_key)
        return paginate(edges, lambda e: e["node"].sort_key, a)

    def resolve_unread_count(self, _, info, **args):
        categories = validated(UnreadCountArgs, args).category
        return inbox.unread_count(ledger(info).conn, [c.value for c in categories] if categories is not None else None)

    def resolve_transaction(self, n, info):
        key = n.transaction_key
        return ledger(info).by_key.get(key) if key else None

    def bind(self, schema):
        for name in TYPENAMES:   # `id` is a field of every subtype (an interface's resolver is never run)
            schema.type_map[name].fields["id"].resolve = self.resolve_id
        for field, (model, method) in self.mutations().items():
            schema.mutation_type.fields[field].resolve = self._mutation(model, method)
        schema.type_map["Notification"].resolve_type = lambda obj, *_: obj.TYPENAME
        schema.query_type.fields["notifications"].resolve = self.resolve_list
        schema.query_type.fields["notificationsUnreadCount"].resolve = self.resolve_unread_count
        schema.type_map["TransactionNotification"].fields["transaction"].resolve = self.resolve_transaction


class PlanTargetsResolver(NodeResolver):
    """`Query.planTargets` and `planTargetsUpdate`: three amounts, not a Node (no id, no refetch)."""
    type_name = "PlanTargets"

    @staticmethod
    def read(conn):
        t = goal_store.get_targets(conn)
        return {"emergency_fund": t["emergency_fund_target"], "inheritance": t["inheritance_target"],
                "retirement": t["retirement_target"]}

    def resolve_query(self, _, info):
        return self.read(ledger(info).conn)

    def mutations(self):
        return {"planTargetsUpdate": (PlanTargetsUpdateInput, self.update)}

    def update(self, inp, info):
        changes = inp.changes()
        if not changes:
            raise GraphQLError("send at least one target")
        goal_store.set_targets(ledger(info).conn, **changes)
        return lambda: {"plan_targets": self.read(ledger(info).conn)}

    def bind(self, schema):
        schema.query_type.fields["planTargets"].resolve = self.resolve_query
        for field, (model, method) in self.mutations().items():
            schema.mutation_type.fields[field].resolve = self._mutation(model, method)


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

    def resolve_all(self, _, info, **args):
        a = validated(ConnectionArgs, args)
        rows = [self._typed(x) for x in asset_store.all_assets(ledger(info).conn)]   # oldest first
        return paginate([{"node": x} for x in rows], lambda e: (e["node"]["id"],), a)

    def mutations(self):
        return {"assetCreate": (AssetCreateInput, self.create), "assetUpdate": (AssetUpdateInput, self.update)}

    def create(self, inp, info):
        try:
            a = asset_store.create_asset(ledger(info).conn, inp.kind.value, inp.label.strip(), inp.value,
                                         inp.valued_at)
        except ValueError as e:
            raise GraphQLError(str(e)) from None
        return lambda: {"asset": self._typed(a)}

    def update(self, inp, info):
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

    def bind(self, schema):
        super().bind(schema)
        schema.query_type.fields["assets"].resolve = self.resolve_all
        for enum in ("AssetKind", "ValuationSource"):
            for name, value in schema.type_map[enum].values.items():
                value.value = name.lower()


class SyncSourceResolver(NodeResolver[SyncSource]):
    """Each source's latest run (sync_status). Retrying starts a sync on the Mac and changes no
    ledger data here (the sync publishes when it finishes), so it never signals a rebuild."""
    type_name = "SyncSource"
    rebuilds = False

    def key(self, s):
        return s.source

    def fetch(self, lg, key):
        return SyncSource.get(lg.conn, key)

    def mutations(self):
        return {"syncSourceRetry": (SyncSourceRetryInput, self.retry)}

    def retry(self, inp, info):
        s = self.require(info, inp.id)
        if not s.retry_from:
            raise GraphQLError("the last sync of this source did not fail")
        rebuilder = info.context.get("rebuilder")
        if rebuilder is None or not rebuilder.retry(s.source, s.retry_from):
            raise GraphQLError("the sync worker is not reachable")
        return lambda: {"sync_source": s}

    def resolve_all(self, _, info, **args):
        a = validated(ConnectionArgs, args)
        rows = SyncSource.all(ledger(info).conn)   # ordered by source
        return paginate([{"node": s} for s in rows], lambda e: (e["node"].source,), a)

    def bind(self, schema):
        super().bind(schema)
        schema.query_type.fields["syncSources"].resolve = self.resolve_all
        for name, value in schema.type_map["SyncRetryPoint"].values.items():
            value.value = name.lower()


GOALS = GoalResolver()
ENTITIES: list[GroupResolver] = [MerchantResolver(), CategoryResolver(), TagResolver(), HorizonResolver(GOALS), GOALS]
TRANSACTIONS = TransactionResolver(GOALS)
NOTIFICATIONS = NotificationResolver()
SYNC_SOURCES = SyncSourceResolver()
PLAN_TARGETS = PlanTargetsResolver()
ASSETS = AssetResolver()
NODES: dict[str, NodeResolver] = {r.type_name: r for r in [TRANSACTIONS, *ENTITIES, NOTIFICATIONS, SYNC_SOURCES,
                                                           ASSETS]}


class _NodeArgs(BaseModel):
    id: GlobalId


def resolve_node(_, info, **args):
    ref = validated(_NodeArgs, args).id
    r = NODES.get(ref.type_name)
    return r.fetch(ledger(info), ref.key) if r else None


def resolve_snapshot(*_):
    raise GraphQLError("snapshot is not served by the API yet")


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
    for enum in ("HorizonKey", "CategorySource", "GoalInterval", "OffsetKind", "ExpenseKind", "KindSource"):
        for name, value in t[enum].values.items():
            value.value = name.lower()
    for name in t["NotificationCategory"].values:
        t["NotificationCategory"].values[name].value = name
    for name, value in t["NotificationSeverity"].values.items():
        value.value = name.lower()
    t["Node"].resolve_type = lambda obj, *_: obj.TYPENAME

    schema.query_type.fields["node"].resolve = resolve_node
    schema.query_type.fields["snapshot"].resolve = resolve_snapshot
    TRANSACTIONS.bind(schema)
    NOTIFICATIONS.bind(schema)
    SYNC_SOURCES.bind(schema)
    PLAN_TARGETS.bind(schema)
    ASSETS.bind(schema)
    for entity in ENTITIES:
        entity.bind(schema, ENTITIES)
    return schema
