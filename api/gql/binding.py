"""Attach resolver methods to the schema by naming convention, and refuse to start without them.

    bind_all(schema, resolvers, attributes)

`resolvers` maps an object type name to a resolver object (or a list of them, searched in order).
For every field that needs one (`schema_bindings.required_fields`, the contract in
api/gql/generated/resolvers.py) the binder looks for `resolve_<snake_field>`:

    fields   resolve_x(self, obj, info)            or  (self, obj, info, args: Model) when the field has
                                                       arguments; `args` is validated through `Model`,
                                                       the method's `args` annotation if it is a Pydantic
                                                       model (a hand subclass), else the generated
                                                       `<Type><Field>Args`. An explicit null means
                                                       "use the default" (`relay.validated`).
    Mutation resolve_x(self, inp, info) -> payload thunk. `inp` is annotated with the input model; the
             binder validates `input` (plus a Linear-style `id` argument) with nulls kept, records the
             write for the rebuild signal unless the provider says `rebuilds = False`, refreshes the
             ledger, and answers `{clientMutationId, success, **payload()}`.

`attributes` ({type: {SDL fields}}) declares the required fields read straight off the parent row
by the default resolver. Anything required, not an attribute and without a method is a startup error.
"""
import inspect

from pydantic import BaseModel

from api.schema_bindings import args_model_name, required_fields, resolver_name

from .generated import inputs as generated
from .relay import validated


class UnresolvedFields(Exception):
    """The schema has required fields with no resolver (or the maps name things that do not exist)."""


def _as_list(provider):
    return [] if provider is None else provider if isinstance(provider, (list, tuple)) else [provider]


def _annotation(method, param):
    """The Pydantic model `method` annotates `param` with, or None."""
    p = inspect.signature(method).parameters.get(param)
    ann = p.annotation if p else None
    return ann if isinstance(ann, type) and issubclass(ann, BaseModel) else None


def _field_resolver(method, model):
    if model is None:
        return lambda obj, info, **_: method(obj, info)
    return lambda obj, info, **args: method(obj, info, validated(model, args))


def _mutation_resolver(method, model, rebuilds):
    def resolve(_, info, input=None, id=None):
        args = {**(input or {}), **({} if id is None else {"id": id})}
        inp = validated(model, args, keep_null=True)
        payload = method(inp, info)
        if rebuilds:
            info.context["writes"] += 1
            info.context["ledger"].invalidate()
        return {"client_mutation_id": inp.client_mutation_id, "success": True, **payload()}
    return resolve


def bind_all(schema, resolvers, attributes=None):
    attributes = attributes or {}
    required = required_fields(schema)
    problems = [f"{name}: no such object type" for name in [*resolvers, *attributes] if name not in schema.type_map]
    for tn, fields in required.items():
        providers = _as_list(resolvers.get(tn))
        for fn, field in fields.items():
            method_name = resolver_name(fn)
            found = next(((p, getattr(p, method_name)) for p in providers if hasattr(p, method_name)), None)
            if found is None:
                if fn not in attributes.get(tn, ()):
                    problems.append(f"{tn}.{fn}: needs {method_name}")
                continue
            if fn in attributes.get(tn, ()):
                problems.append(f"{tn}.{fn}: is both an attribute and has {method_name}")
            provider, method = found
            if tn == "Mutation":
                model = _annotation(method, "inp")
                if model is None:
                    problems.append(f"Mutation.{fn}: {method_name} must annotate `inp` with its input model")
                    continue
                field.resolve = _mutation_resolver(method, model, getattr(provider, "rebuilds", True))
            else:
                model = (_annotation(method, "args") or getattr(generated, args_model_name(tn, fn))) if field.args else None
                field.resolve = _field_resolver(method, model)
    for tn, names in attributes.items():
        problems += [f"{tn}.{fn}: declared an attribute but not a field needing a resolver"
                     for fn in sorted(set(names) - set(required.get(tn, ())))]
    if problems:
        raise UnresolvedFields("GraphQL resolvers are not bound:\n  " + "\n  ".join(sorted(problems)))
