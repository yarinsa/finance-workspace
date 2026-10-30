"""Generate api/gql/generated/inputs.py (enums, input types, field-argument models) and
api/gql/generated/resolvers.py (one resolver contract per object type) from the SDL.

    poetry run python -m api.codegen.generate           # rewrite the file
    poetry run python -m api.codegen.generate --check   # exit 1 if it is stale

The SDL in api/schema/*.graphql is the source of truth. The output is the plain structure
(names, types, nullability, defaults, camelCase aliases); validation and behaviour live in
api/gql/inputs.py, whose classes subclass these.
"""
import keyword
import re
import sys
from pathlib import Path

from graphql import (GraphQLEnumType, GraphQLInputObjectType, GraphQLList, GraphQLNonNull, GraphQLObjectType,
                     GraphQLScalarType, Undefined)
from pydantic.alias_generators import to_camel

from api.schema_bindings import (args_model_name, load_schema, mutation_input_name, required_fields,
                                 resolver_name)

OUT = Path(__file__).resolve().parents[1] / "gql" / "generated" / "inputs.py"
OUT_RESOLVERS = OUT.with_name("resolvers.py")

SCALARS = {"String": "str", "Int": "int", "Float": "float", "Boolean": "bool", "ID": "GlobalId",
           "Date": "dt.date", "DateTime": "dt.datetime", "Money": "Decimal", "JSON": "Any"}

HEADER = '''"""GENERATED from api/schema/*.graphql by `poetry run python -m api.codegen.generate` — do not edit.

Edit the SDL, rerun the generator, commit both. Structure only (types, nullability, defaults,
camelCase aliases); validation and behaviour are added by subclasses in api/gql/inputs.py.
Enum members mirror the SDL names; where the server maps an enum to other runtime values
(see `bind` in api/gql/resolvers.py) the hand model in inputs.py declares the field itself.
"""
# ruff: noqa: F401
import datetime as dt
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import Field

from ..relay import GlobalId, _GraphQLModel
'''


def snake(name):
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def py_type(t):
    """(annotation, nullable) for a GraphQL type."""
    nullable = not isinstance(t, GraphQLNonNull)
    if not nullable:
        t = t.of_type
    if isinstance(t, GraphQLList):
        inner, inner_null = py_type(t.of_type)
        return f"list[{inner}{' | None' if inner_null else ''}]", nullable
    if isinstance(t, GraphQLScalarType):
        return SCALARS[t.name], nullable
    return t.name, nullable   # enum or input type


def py_default(t, value):
    t = t.of_type if isinstance(t, GraphQLNonNull) else t
    if isinstance(t, GraphQLEnumType):
        return f"{t.name}.{value}"
    if isinstance(value, (bool, int, float, str)):
        return repr(value)
    raise ValueError(f"unsupported default {value!r} for {t}")


def field_line(sdl_name, t, default):
    """One model field: `name: annotation = default`, with an alias unless camelCase round-trips."""
    ann, nullable = py_type(t)
    has_default = default is not Undefined and default is not None
    name = snake(sdl_name)
    kwargs = []
    if keyword.iskeyword(name):
        name += "_"
    if to_camel(name) != sdl_name:
        kwargs.append(f'alias="{sdl_name}"')
    if has_default:
        # Query arguments treat an explicit null as "use the default" (relay.validated), so no `| None`.
        value = py_default(t, default)
    elif nullable:
        ann, value = f"{ann} | None", "None"
    else:
        value = None
    if kwargs:
        value = f"Field({', '.join(([f'default={value}'] if value is not None else []) + kwargs)})"
    return f"    {name}: {ann}" + (f" = {value}" if value is not None else "")


def deps(t):
    return {f.type for f in t.fields.values()}


def render_model(name, fields, doc=None):
    lines = [f"class {name}(_GraphQLModel):"]
    if doc:
        lines.append(f'    """{doc}"""')
    lines += [field_line(n, t, d) for n, t, d in fields] or ["    pass"]
    return "\n".join(lines)


def named(t):
    while hasattr(t, "of_type"):
        t = t.of_type
    return t


def generate():
    schema = load_schema()
    types = {n: t for n, t in schema.type_map.items() if not n.startswith("__")}
    out = [HEADER]

    for n in sorted(n for n, t in types.items() if isinstance(t, GraphQLEnumType)):
        body = "\n".join(f'    {v} = "{v}"' for v in types[n].values)
        out.append(f"class {n}(str, Enum):\n{body}")

    inputs = {n: t for n, t in types.items() if isinstance(t, GraphQLInputObjectType)}
    ordered, seen = [], set()

    def visit(n):
        if n in seen:
            return
        seen.add(n)
        for f in inputs[n].fields.values():
            d = named(f.type)
            if d.name in inputs:
                visit(d.name)
        ordered.append(n)

    for n in sorted(inputs):
        visit(n)
    for n in ordered:
        out.append(render_model(n, [(k, f.type, f.default_value) for k, f in inputs[n].fields.items()],
                                inputs[n].description and inputs[n].description.replace('"', "'")))

    args = []
    for tn, t in types.items():
        if isinstance(t, GraphQLObjectType):
            for fn, f in t.fields.items():
                if f.args:
                    args.append((args_model_name(tn, fn), f))
    for name, f in sorted(args):
        out.append(render_model(name, [(k, a.type, a.default_value) for k, a in f.args.items()]))

    return "\n\n\n".join(out) + "\n"


RESOLVERS_HEADER = '''"""GENERATED from api/schema/*.graphql by `poetry run python -m api.codegen.generate` — do not edit.

One Protocol per object type, listing only the fields that need a resolver (`required_fields` in
api/schema_bindings.py): Query/Mutation fields, fields with arguments, global ids and the
`resolved` fields of a bound type. A resolver class provides `resolve_<snake_field>`:

    query/field   resolve_x(self, obj, info[, args])   args = the validated `<Type><Field>Args`
                                                       (or a hand subclass named in the annotation)
    mutation      resolve_x(self, inp, info) -> payload thunk   inp = the validated input model

`bind_all` (api/gql/binding.py) attaches them by name and fails at startup for a missing one; a
field read straight off the parent row is declared in the provider map's `attributes` instead.
"""
# ruff: noqa: F401, E501
from typing import Any, Protocol
'''


def generate_resolvers():
    schema = load_schema()
    contracts = sorted(required_fields(schema).items())
    hand = sorted({mutation_input_name(fn, f) for fn, f in dict(contracts).get("Mutation", {}).items()})
    gen = sorted({args_model_name(tn, fn) for tn, fields in contracts if tn != "Mutation"
                  for fn, f in fields.items() if f.args})
    out = [RESOLVERS_HEADER + f"\nfrom ..inputs import {', '.join(hand)}   # the hand-written mutation inputs"
           + f"\nfrom .inputs import {', '.join(gen)}"]
    for tn, fields in contracts:
        lines = [f"class {tn}Resolvers(Protocol):"]
        for fn, f in fields.items():
            name = resolver_name(fn)
            if tn == "Mutation":
                lines.append(f"    def {name}(self, inp: {mutation_input_name(fn, f)}, info) -> Any: ...")
            elif f.args:
                lines.append(f"    def {name}(self, obj, info, args: {args_model_name(tn, fn)}) -> Any: ...")
            else:
                lines.append(f"    def {name}(self, obj, info) -> Any: ...")
        out.append("\n".join(lines))
    return "\n\n\n".join(out) + "\n"


def main(argv):
    targets = [(OUT, generate()), (OUT_RESOLVERS, generate_resolvers())]
    if "--check" in argv:
        stale = [p for p, text in targets if not p.exists() or p.read_text() != text]
        for p in stale:
            print(f"{p} is stale: run `poetry run python -m api.codegen.generate`", file=sys.stderr)
        return 1 if stale else 0
    for p, text in targets:
        p.write_text(text)
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
