---
name: graphql-schema
description: Change the Ledger API GraphQL surface schema-first (api/schema/*.graphql, codegen, Pydantic binding, resolvers). Use for any new field, query, mutation or enum, or when test_codegen.py / test_graphql_schema.py fails.
---

# GraphQL schema (SDL-first) and its codegen

**The SDL is the source of truth.** `api/schema/*.graphql` defines the API's shape; Python and
(later) TypeScript are generated from it or checked against it. Never go code-first, never
hand-edit `api/gql/generated/`.

| Layer | File | Enforced by |
|---|---|---|
| API shape | `api/schema/*.graphql` | `graphql-core` `build_schema` (`api/schema_bindings.load_schema`) |
| Enums, inputs, `<Type><Field>Args` | `api/gql/generated/inputs.py` (generated) | `api/tests/test_codegen.py` (`--check`) |
| Validation rules on inputs | `api/gql/inputs.py` (subclasses the generated bases) | `api/tests/test_graphql*.py` |
| Object type ⇄ data model | `api/schema_bindings.py` `BINDINGS` | `api/tests/test_graphql_schema.py` |
| Resolver contracts | `api/gql/generated/resolvers.py` (generated) | `api/tests/test_codegen.py` (`--check`) |
| App operation/variable types | `app/src/__generated__/` (relay-compiler, gitignored; built by `pnpm dev/build/test`) | `pnpm codegen:check`, `tsc -b` |
| Resolvers, bound by name | `api/gql/resolvers.py` + `api/gql/binding.py` (`bind_all`) | startup, `api/tests/test_graphql_binding.py` |

## Workflow

1. **Edit the SDL** in the right `api/schema/<area>.graphql`. Follow the house style: Relay
   `Node` ids and connections, mutations named `<entity><Verb>` taking one `…Input` with
   `clientMutationId` and returning a payload.
2. **Regenerate both sides:** `poetry run python -m api.codegen.generate` (check only: `--check`)
   and, in `app/`, `pnpm codegen` (check: `pnpm codegen:check`). Fix any `tsc -b` error it surfaces.
3. **New object type?** Add a `Binding` in `api/schema_bindings.py` (model, `renames`,
   `resolved`, `hidden`, `never_null`) or list it in `STRUCTURAL`. A field that maps to a
   model field needs **no resolver** — the default resolver reads it in snake_case.
4. **Rules, not shape, go in `api/gql/inputs.py`:** subclass the generated model and add only
   validators, `node_id_of("Type")` id narrowing, length/range limits, `Patch` semantics. If a
   hand model must differ from the SDL, say why in one comment.
5. **Resolvers** for exactly the fields the generated contract (`generated/resolvers.py`, one
   Protocol per type) lists: all Query/Mutation fields, fields with arguments, global `id`s and
   `resolved` fields. Add a method `resolve_<snake_field>` to the owning class in `resolvers.py`
   (`(self, obj, info[, args: Model])`; a mutation is `(self, inp: InputModel, info)` returning the
   payload thunk) and register the class in `RESOLVERS`. A required field read straight off the
   parent row (no logic) goes in `ATTRIBUTES` instead. `bind_all` fails `build()` at startup
   listing every required field with neither. Annotating `args` with a hand subclass (e.g.
   `TransactionArgs`) validates through it; without one the generated `<Type><Field>Args` is used.
6. **Data model changed too?** Use the `schema-change` skill (models.py / tables.py / Alembic).
7. **Test:** `poetry run pytest api` (DB tests skip without `DATABASE_URL`; never point them at
   the live DB). Commit the SDL, the generated file and the code together.

## Rules that stay true

- The API process has no power: role `finance_api` (overrides, audit, inbox read-state only),
  CSRF headers on every write, edge-auth + `X-Origin-Secret`. A new mutation must not need more.
- `tenant_id` is never exposed or accepted; the tenant is the request's (`Binding` hides it).
- Ledger mutations signal `LedgerRebuildWorkflow`; inbox mutations do **not**.
- New sync actions are GraphQL mutations, not REST endpoints (see `sync-dev`).
- Enums whose runtime values are lowercase (`AssetKind`, `HorizonKey`, `GoalInterval`,
  `TenantRole`, `TenantStatus`) are converted in `bind`; their Python side stays hand-written
  (`Literal`s / `AssetKind`), the generated enums mirror the SDL names only.

## When a test fails

- `test_codegen` stale → you edited the SDL without regenerating. Run step 2.
- `test_every_object_type_is_bound_or_structural` → step 3.
- `test_sdl_fields_map_to_model_fields` → rename in `renames`, mark `resolved`, or add the
  model field (`schema-change`).
- `test_model_fields_are_exposed_or_hidden` → expose it in the SDL or add to `hidden`.
- Non-null SDL field on an optional model field → make it nullable, or `never_null` if the
  resolver guarantees a value.

## Maintaining the generator (`api/codegen/generate.py`)

Pure function of `load_schema()`; output must be deterministic (sorted, dependency-ordered).
Scalars: `Date`→`dt.date`, `DateTime`→`dt.datetime`, `Money`→`Decimal`, `ID`→`GlobalId`,
`JSON`→`Any`; a new custom scalar needs a mapping there. Nullable args with an SDL default are
emitted non-null with that default (`relay.validated` treats explicit null as "use default").
After changing the generator, regenerate and diff `generated/`; behaviour of the hand
subclasses must not change.

## Client (app/)

Phase 3 reused the Relay compiler the app already ran instead of adding `@graphql-codegen`: it reads
`api/schema/*.graphql` and emits a typed artifact per `graphql` document (types for variables, response and
enums; scalars `Money`/`Date`/`DateTime`→`string`, `JSON`→`unknown` in `app/relay.config.json`). Every
operation is a `graphql` tag: Relay hooks for screens, and `graphqlRequest<opQuery>(DOC, vars)` (in
`app/src/lib/relay.ts`) for the inbox, tenant admin and sync retry, which live outside Relay's store.
Name operations `<moduleName><Thing>Query|Mutation`. Enums carry a `"%future added value"` arm; narrow
it (`Exclude<…>`) where the UI needs the closed set. Never hand-write a response/variables type.

## Roadmap

Phases 1 (generated inputs), 2 (generated resolver contracts + `bind_all`) and 3 (typed client operations,
above) have landed. Open server-side gaps are tracked in GitHub issue #60.
