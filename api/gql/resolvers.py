"""Resolvers for api/schema: one class per entity, wired onto the schema built from the SDL.

    NodeResolver          global `id` and `Query.node` refetch
    └─ GroupResolver      a set of transactions with a name (merchant, category, tag):
                          `<entity>.transactions`, the root `Query.<plural>` connection with
                          edge totals, and an M:M connection to every other group entity
    TransactionResolver   the ledger row itself

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

from .inputs import (ClearTransactionOverrideInput, CreateGoalInput, DeleteGoalInput, DeleteTagInput, GroupArgs,
                     GroupOrder, SetTransactionTagsInput, TransactionArgs, TransactionOrder, UpdateGoalInput,
                     UpdateTagInput, UpdateTransactionInput)
from .ledger import CENT, Ledger, Merchant, Txn, totals
from .relay import ConnectionArgs, GlobalId, paginate, to_global_id, validated

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "db"))   # the shared write paths
import goal_store  # noqa: E402
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
        def resolve(_, info, input):
            inp = validated(model, input, keep_null=True)
            payload = method(inp, info)
            info.context["writes"] += 1
            ledger(info).invalidate()
            return {"client_mutation_id": inp.client_mutation_id, **payload()}
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
        return {"createGoal": (CreateGoalInput, self.create), "updateGoal": (UpdateGoalInput, self.update),
                "deleteGoal": (DeleteGoalInput, self.delete)}

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
        return lambda: {"deleted_goal_id": to_global_id(self.type_name, str(g.id))}


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
                "setTransactionTags": (SetTransactionTagsInput, self.set_tags)}

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


GOALS = GoalResolver()
ENTITIES: list[GroupResolver] = [MerchantResolver(), CategoryResolver(), TagResolver(), HorizonResolver(GOALS), GOALS]
TRANSACTIONS = TransactionResolver(GOALS)
NODES: dict[str, NodeResolver] = {r.type_name: r for r in [TRANSACTIONS, *ENTITIES]}


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


def build():
    """The executable schema: the SDL with resolvers, scalars and enum values attached."""
    schema = load_schema()
    t = schema.type_map
    t["Money"].serialize = _money
    t["Date"].serialize = lambda v: v.isoformat()
    t["Date"].parse_value = _parse_date
    t["DateTime"].serialize = lambda v: v.isoformat()
    t["JSON"].serialize = lambda v: v
    t["Money"].parse_value = _parse_money
    for enum in ("HorizonKey", "CategorySource", "GoalInterval"):
        for name, value in t[enum].values.items():
            value.value = name.lower()
    t["Node"].resolve_type = lambda obj, *_: obj.TYPENAME

    schema.query_type.fields["node"].resolve = resolve_node
    schema.query_type.fields["snapshot"].resolve = resolve_snapshot
    TRANSACTIONS.bind(schema)
    for entity in ENTITIES:
        entity.bind(schema, ENTITIES)
    return schema
