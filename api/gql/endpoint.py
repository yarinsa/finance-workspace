"""POST /api/graphql: parse, validate (with depth and introspection limits), execute.

Same gates as the REST routes: the origin secret (app-wide), the session (`current_user`)
and the CSRF headers on every request, since a GraphQL POST may carry a mutation.
Resolvers run in a thread on one pooled connection per request.
"""
import json
import logging

from graphql import (ExecutionResult, FieldNode, FragmentSpreadNode, GraphQLError, InlineFragmentNode,
                     OperationType, ValidationRule, execute, parse, specified_rules, validate)
from graphql.validation import NoSchemaIntrospectionCustomRule
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .ledger import Ledger
from .resolvers import build, default_resolver

log = logging.getLogger("finance_api")

MAX_DEPTH = 14   # a Merchant -> categories -> transactions -> merchant walk is ~12 levels deep
SCHEMA = build()


class Request(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    query: str = Field(max_length=8000)
    variables: dict | None = None
    operation_name: str | None = Field(default=None, alias="operationName")


def depth_limit(max_depth):
    class DepthLimit(ValidationRule):
        """Rejects operations nested deeper than `max_depth` fields (fragments followed)."""

        def enter_operation_definition(self, node, *_):
            if self._depth(node.selection_set, 0, set()) > max_depth:
                self.report_error(GraphQLError(f"query is nested deeper than {max_depth} levels", node))

        def _depth(self, selection_set, depth, seen):
            if selection_set is None:
                return depth
            deepest = depth
            for sel in selection_set.selections:
                if isinstance(sel, FieldNode):
                    deepest = max(deepest, self._depth(sel.selection_set, depth + 1, seen))
                elif isinstance(sel, InlineFragmentNode):
                    deepest = max(deepest, self._depth(sel.selection_set, depth, seen))
                elif isinstance(sel, FragmentSpreadNode) and sel.name.value not in seen:
                    frag = self.context.get_fragment(sel.name.value)
                    if frag:
                        deepest = max(deepest, self._depth(frag.selection_set, depth, seen | {sel.name.value}))
            return deepest
    return DepthLimit


def _error(e: GraphQLError):
    """An error safe to send: resolver crashes are logged and masked."""
    if e.original_error is not None and not isinstance(e.original_error, GraphQLError):
        log.error("resolver error", exc_info=e.original_error)
        return {"message": "internal error", "path": e.path}
    return e.formatted


def run(body: bytes, conn, user, allow_introspection=False):
    """(status, response dict) for a GraphQL request body."""
    try:
        req = Request.model_validate_json(body)
    except ValidationError as e:
        return 400, {"errors": [{"message": f"bad request: {e.errors()[0]['msg']}"}]}
    try:
        doc = parse(req.query)
    except GraphQLError as e:
        return 400, {"errors": [e.formatted]}
    rules = [*specified_rules, depth_limit(MAX_DEPTH)]
    if not allow_introspection:
        rules.append(NoSchemaIntrospectionCustomRule)
    errors = validate(SCHEMA, doc, rules)
    if errors:
        return 400, {"errors": [e.formatted for e in errors]}
    ops = [d for d in doc.definitions if getattr(d, "operation", None) is not None]
    op = next((d for d in ops if req.operation_name in (None, d.name and d.name.value)), None)
    if op is not None and op.operation != OperationType.QUERY:
        return 400, {"errors": [{"message": f"{op.operation.value} operations are not served yet"}]}
    result = execute(SCHEMA, doc, variable_values=req.variables, operation_name=req.operation_name,
                     context_value={"ledger": Ledger(conn), "user": user}, field_resolver=default_resolver)
    if not isinstance(result, ExecutionResult):
        raise RuntimeError("resolvers must be synchronous")
    out = {"data": result.data}
    if result.errors:
        out["errors"] = [_error(e) for e in result.errors]
    json.dumps(out, default=str)   # fail here, not in the response, if a resolver returned junk
    return 200, out
