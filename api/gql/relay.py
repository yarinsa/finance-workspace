"""Relay plumbing as Pydantic types: global IDs, cursors, connection args and pages.

Validation and decoding happen in the types, so a resolver receives typed values:
`GlobalId` decodes to a (type name, key) pair, `Cursor` decodes to a sort-key tuple,
and `ConnectionArgs` bounds `first`/`last`. `validated` turns any ValidationError into
a GraphQLError naming the bad argument.

A cursor is the item's sort key, a tuple of ints and strings unique per item, in a
list sorted ascending by that key. Resuming after a row that has since vanished
(an edit, a re-import) still lands in the right place.
"""
import base64
import bisect
import json
from typing import Annotated, Any, Callable, NamedTuple

from graphql import GraphQLError
from pydantic import (AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer,
                      ValidationError, model_validator)
from pydantic.alias_generators import to_camel

DEFAULT_PAGE = 50
MAX_PAGE = 200


def _encode(s):
    return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")


def _decode(s):
    try:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        raise ValueError("not a valid opaque value") from None


class NodeRef(NamedTuple):
    type_name: str
    key: str


def to_global_id(type_name, key):
    return _encode(f"{type_name}:{key}")


def _parse_global_id(v):
    if isinstance(v, NodeRef):
        return v
    type_name, sep, key = _decode(str(v)).partition(":")
    if not sep or not type_name:
        raise ValueError("malformed id")
    return NodeRef(type_name, key)


GlobalId = Annotated[NodeRef, BeforeValidator(_parse_global_id),
                     PlainSerializer(lambda r: to_global_id(*r), return_type=str)]


def node_id_of(type_name):
    """A GlobalId that must name `type_name`, e.g. `node_id_of("Tag")`."""
    def check(ref):
        if ref.type_name != type_name:
            raise ValueError(f"id is not a {type_name}")
        return ref
    return Annotated[GlobalId, AfterValidator(check)]


def encode_cursor(key):
    return _encode(json.dumps(list(key), ensure_ascii=False, separators=(",", ":")))


def _parse_cursor(v):
    if isinstance(v, tuple):
        return v
    try:
        key = json.loads(_decode(str(v)))
    except json.JSONDecodeError:
        raise ValueError("malformed cursor") from None
    if not isinstance(key, list):
        raise ValueError("malformed cursor")
    return tuple(key)


Cursor = Annotated[tuple, BeforeValidator(_parse_cursor), PlainSerializer(encode_cursor, return_type=str)]


class _GraphQLModel(BaseModel):
    """camelCase on the wire, snake_case in Python."""
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid",
                              arbitrary_types_allowed=True)


class ConnectionArgs(_GraphQLModel):
    first: int | None = Field(default=None, ge=0, le=MAX_PAGE)
    after: Cursor | None = None
    last: int | None = Field(default=None, ge=0, le=MAX_PAGE)
    before: Cursor | None = None

    @model_validator(mode="after")
    def default_page(self):
        if self.first is None and self.last is None:
            self.first = DEFAULT_PAGE
        return self


class PageInfo(_GraphQLModel):
    has_next_page: bool
    has_previous_page: bool
    start_cursor: str | None
    end_cursor: str | None


class Connection(_GraphQLModel):
    """A page. `edges` are dicts (node, cursor, plus edge fields such as `totals`)."""
    edges: list[dict[str, Any]]
    page_info: PageInfo
    total_count: int


def validated(model, args, keep_null=False):
    """`model` built from resolver `args`; a ValidationError becomes a GraphQLError.

    For query arguments an explicit null means "use the default"; mutation inputs pass
    `keep_null`, where null means "clear this field"."""
    if not keep_null:
        args = {k: v for k, v in args.items() if v is not None}
    try:
        return model.model_validate(args)
    except ValidationError as e:
        err = e.errors()[0]
        where = ".".join(str(p) for p in err["loc"])
        raise GraphQLError(f"{where}: {err['msg']}" if where else err["msg"]) from None


def paginate(edges, sort_key: Callable[[dict], tuple], args: ConnectionArgs) -> Connection:
    """A connection over `edges` (dicts with at least "node"), sorted ascending by `sort_key`.

    Follows the Relay algorithm: slice by `after`/`before`, then take `first` from the
    front or `last` from the back. `hasNextPage`/`hasPreviousPage` say whether anything
    exists beyond the page."""
    keys = [sort_key(e) for e in edges]
    start = bisect.bisect_right(keys, args.after) if args.after else 0
    end = max(start, bisect.bisect_left(keys, args.before) if args.before else len(edges))
    if args.first is not None:
        end = min(end, start + args.first)
    if args.last is not None:
        start = max(start, end - args.last)
    page = [{**e, "cursor": encode_cursor(keys[i])} for i, e in zip(range(start, end), edges[start:end])]
    return Connection(
        edges=page, total_count=len(edges),
        page_info=PageInfo(has_previous_page=start > 0, has_next_page=end < len(edges),
                           start_cursor=page[0]["cursor"] if page else None,
                           end_cursor=page[-1]["cursor"] if page else None))
