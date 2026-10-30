"""bind_all attaches resolvers by name and refuses to start with a required field unresolved."""
import pytest

from api.gql import resolvers
from api.gql.binding import UnresolvedFields, bind_all
from api.gql.generated import resolvers as contracts
from api.schema_bindings import load_schema, required_fields, resolver_name


def test_every_required_field_is_bound_on_the_real_schema():
    schema = resolvers.build()
    for tn, fields in required_fields(schema).items():
        for fn, f in fields.items():
            assert f.resolve is not None or fn in resolvers.ATTRIBUTES.get(tn, ()), f"{tn}.{fn}"


def test_the_generated_contract_matches_the_required_fields():
    schema = load_schema()
    for tn, fields in required_fields(schema).items():
        proto = getattr(contracts, f"{tn}Resolvers")
        assert {n for n in vars(proto) if n.startswith("resolve_")} == {resolver_name(fn) for fn in fields}


def test_a_missing_resolver_fails_at_bind_and_lists_every_field():
    class Partial:
        def resolve_snapshot(self, _, info):
            return None

    with pytest.raises(UnresolvedFields) as e:
        bind_all(load_schema(), {"Query": Partial()})
    text = str(e.value)
    assert "Query.transactions: needs resolve_transactions" in text
    assert "Mutation.updateTag: needs resolve_update_tag" in text
    assert "Query.snapshot" not in text


def test_a_stale_attribute_declaration_is_rejected():
    providers = {**resolvers.RESOLVERS}
    with pytest.raises(UnresolvedFields, match="Tag.name: declared an attribute"):
        bind_all(load_schema(), providers, {**resolvers.ATTRIBUTES, "Tag": frozenset({"name"})})


def test_a_mutation_must_annotate_its_input():
    schema = load_schema()
    mutation = {"Mutation": type("M", (), {"resolve_update_tag": lambda self, inp, info: None})()}
    with pytest.raises(UnresolvedFields, match="must annotate `inp`"):
        bind_all(schema, {**resolvers.RESOLVERS, **mutation}, resolvers.ATTRIBUTES)
