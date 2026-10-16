"""The GraphQL SDL (api/schema) and the Pydantic models it is bound to cannot drift."""
import typing
from typing import Literal, get_args, get_origin

import pytest
from graphql import GraphQLEnumType, GraphQLNonNull, GraphQLObjectType

from api.schema_bindings import BINDINGS, STRUCTURAL, load_schema, model_field, snake
from finance import models

SCHEMA = load_schema()
OBJECT_TYPES = {name: t for name, t in SCHEMA.type_map.items()
                if isinstance(t, GraphQLObjectType) and not name.startswith("__")}


def _optional(annotation):
    return type(None) in get_args(annotation) or annotation is typing.Any


def test_every_object_type_is_bound_or_structural():
    unaccounted = set(OBJECT_TYPES) - set(BINDINGS) - STRUCTURAL
    assert not unaccounted, f"bind these in api/schema_bindings.py or list them as STRUCTURAL: {unaccounted}"
    assert not (set(BINDINGS) | STRUCTURAL) - set(OBJECT_TYPES), "bindings name a type the SDL no longer has"


@pytest.mark.parametrize("type_name", sorted(BINDINGS))
def test_sdl_fields_map_to_model_fields(type_name):
    binding = BINDINGS[type_name]
    fields = binding.model.model_fields
    missing = {f: model_field(binding, f) for f in OBJECT_TYPES[type_name].fields
               if model_field(binding, f) is not None and model_field(binding, f) not in fields}
    assert not missing, f"{type_name}: SDL fields with no {binding.model.__name__} field: {missing}"
    assert binding.resolved <= set(OBJECT_TYPES[type_name].fields), f"{type_name}: stale `resolved` entries"


@pytest.mark.parametrize("type_name", sorted(BINDINGS))
def test_model_fields_are_exposed_or_hidden(type_name):
    binding = BINDINGS[type_name]
    # a resolved field still exposes its same-named model field (`id` -> global id, `tags` -> Tag nodes)
    exposed = {binding.renames.get(f, snake(f)) for f in OBJECT_TYPES[type_name].fields}
    unexposed = set(binding.model.model_fields) - exposed - binding.hidden
    assert not unexposed, f"{type_name}: add to the SDL or to `hidden`: {unexposed}"
    assert not binding.hidden & exposed, f"{type_name}: fields both hidden and exposed: {binding.hidden & exposed}"


@pytest.mark.parametrize("type_name", sorted(BINDINGS))
def test_non_null_sdl_fields_are_never_null_in_the_model(type_name):
    binding = BINDINGS[type_name]
    loose = [f for f, gql in OBJECT_TYPES[type_name].fields.items()
             if isinstance(gql.type, GraphQLNonNull)
             and (mf := model_field(binding, f)) is not None
             and mf not in binding.never_null
             and _optional(binding.model.model_fields[mf].annotation)]
    assert not loose, f"{type_name}: non-null in SDL but optional in the model: {loose}"


def test_horizon_enum_matches_the_ledger_model():
    literal = models.LedgerTransaction.model_fields["horizon"].annotation
    values = next(get_args(a) for a in get_args(literal) if get_origin(a) is Literal)
    enum = SCHEMA.type_map["HorizonKey"]
    assert isinstance(enum, GraphQLEnumType)
    assert set(enum.values) == {v.upper() for v in values}


def test_category_source_enum_matches_the_table_check():
    from finance.tables import Category
    check = next(c for c in Category.__table_args__ if c.name == "categories_source_check")
    assert set(SCHEMA.type_map["CategorySource"].values) == {"RISEUP", "USER"}
    assert all(f"'{v.lower()}'" in str(check.sqltext) for v in SCHEMA.type_map["CategorySource"].values)


def test_every_node_type_is_refetchable():
    node = SCHEMA.type_map["Node"]
    assert {t.name for t in SCHEMA.get_possible_types(node)} == {"Transaction", "Merchant", "Category", "Tag", "Horizon", "Goal"}


def test_connections_follow_the_relay_spec():
    for name, t in OBJECT_TYPES.items():
        if name.endswith("Connection"):
            assert {"edges", "pageInfo"} <= set(t.fields), name
            edge = t.fields["edges"].type.of_type.of_type.of_type
            assert {"node", "cursor"} <= set(edge.fields), edge.name


def test_mutations_take_one_input_and_echo_client_mutation_id():
    for name, m in SCHEMA.mutation_type.fields.items():
        assert list(m.args) == ["input"], name
        assert "clientMutationId" in m.args["input"].type.of_type.fields, name
        assert "clientMutationId" in m.type.of_type.fields, name


def _unwrap(t):
    while hasattr(t, "of_type"):
        t = t.of_type
    return t


def _is_list(t):
    from graphql import GraphQLList
    t = t.of_type if isinstance(t, GraphQLNonNull) else t
    return isinstance(t, GraphQLList)


def test_relations_to_nodes_are_connections_never_lists():
    # 1:M "one" side is the object itself; anything plural over a Node is a paginated connection
    node = SCHEMA.type_map["Node"]
    lists = [f"{name}.{f}" for name, t in OBJECT_TYPES.items() for f, gql in t.fields.items()
             if _is_list(gql.type) and not name.endswith(("Connection",))
             and isinstance(_unwrap(gql.type), GraphQLObjectType) and node in _unwrap(gql.type).interfaces]
    assert not lists, f"return a connection instead of a list: {lists}"


def test_every_connection_has_a_total_count():
    missing = [n for n in OBJECT_TYPES if n.endswith("Connection") and "totalCount" not in OBJECT_TYPES[n].fields]
    assert not missing


def test_group_edges_carry_transaction_totals():
    for name in ("MerchantEdge", "CategoryEdge", "TagEdge", "HorizonEdge", "GoalEdge"):
        assert _unwrap(OBJECT_TYPES[name].fields["totals"].type).name == "TransactionTotals", name


def test_plural_relations_are_paginated_both_ways():
    for name, t in OBJECT_TYPES.items():
        for f, gql in t.fields.items():
            if _unwrap(gql.type).name.endswith("Connection") and name != "Transaction":
                assert {"first", "after", "last", "before"} <= set(gql.args), f"{name}.{f}"
