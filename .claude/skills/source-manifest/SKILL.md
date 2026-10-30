---
name: source-manifest
description: Manage the sync sources' self-declarations (data/<source>/manifest.json) — add a manifest for a new source, change a source's label, account types, capabilities or connection form (JSON Schema + x-env), extend the allowed values, and keep the registry, digest, app and docs in step. Activate when the user adds or edits a source manifest, changes what a source provides or which .env variables it needs, touches finance/manifest.py or the /syncs connection panel, or asks what the manifests are for.
---

# Source manifests

Each synced source declares itself in `data/<source>/manifest.json`. It is the single place for
what a source *is*; nothing else should keep its own copy of a label, an entity list or an env var.

```json
{
  "name": "cal",                       // must equal the directory name
  "label": "כאל",                      // Hebrew display name
  "account_types": ["credit_card"],    // what it holds (list: Harel = pension + study_fund)
  "capabilities": ["credit_cards", "transactions"],   // normalized entities it emits
  "connection": { "type": "object", "properties": { "CAL_USERNAME": {"type":"string","title":"שם משתמש","x-env":"CAL_USERNAME"}, … }, "required": [...] }
}
```

## Where it lives and who reads it

| Piece | File | Role |
|---|---|---|
| Model + loader | `finance/manifest.py` | `SourceManifest` (pydantic, `extra=forbid`, frozen), `load(name)`, `load_all()`, `.env_vars`. The allowed `AccountType` / `Capability` values are `Literal`s here. |
| Sync registry | `sync/sources.py` | `Source.manifest` / `Source.label`; `LABEL_HE` is built from the manifests. Operational config (port, check strategy, dumps, login group) stays in the registry. |
| Digest | `data/digest.py` | `source_syncs` rows carry `label`, `account_types`, `capabilities`; `snapshot.source_manifests` holds every manifest. |
| App | `app/src/lib/data.ts` (`sourceLabel`, `SourceManifest`), `routes/Syncs.tsx`, `components/ConnectionForm.tsx` | Labels come from the snapshot (fallback: the source id). The connection panel renders `connection` with react-jsonschema-form, **read-only**, lazy-loaded. |
| Tests | `data/tests/test_manifest.py`, `sync/tests/test_sources.py`, `data/tests/test_source_syncs.py` | See below. |

## Rules

- **The form describes, it never collects.** Values stay in the Mac's `.env`; the internet-facing API
  holds no bank credentials (CLAUDE.md "Ledger API"). Don't add a submit path or put a `default`/`const`
  on a field. Collecting values would be a new secret-handling path: ask the user first.
- **`capabilities` are the entities the source's `normalize.py` writes** (the Sources table in CLAUDE.md).
  Change it only when the normalizer changes; the test pins the exact set per source.
- **`connection` fields = the `process.env.*` the scraper reads** (`x-env` names the variable). A
  secret is `writeOnly: true` (the app maps it to a password widget). A source with no login
  stored (Chrome-session sources: more, analyst) has an empty `properties` and a `description` saying so.
  Never list an OTP: the human types it in the app.
- Only `type: "string"` fields with an `x-env`; `required` must name existing properties
  (the model enforces all three).
- Hebrew labels match what the user already sees; renaming one changes the Syncs screen, home actions
  and push text, so say so.

## Workflows

**New source** (after `add-bank-source` scaffolds it): create `data/<name>/manifest.json`; the
parametrized tests in `test_manifest.py` pick it up from `data/*/normalize.py`, so add it to the
expected-capabilities dict there, and to `SCRAPER_DIR` if its scraper dir differs from its name.
Add the `Source(...)` to `sync/sources.py` (label comes from the manifest — do not repeat it).

**Change a field / new account type / new capability:** edit the `Literal` in `finance/manifest.py`,
then the manifest(s), then, if the app should show it, `ENTITY_LABEL` in `Syncs.tsx` (entity names
are the one label map not yet in the manifest). New manifest *keys* need the model first
(`extra=forbid`), then `SourceManifest` in `app/src/lib/data.ts`.

**Change a scraper's env vars:** update `connection` in the same commit; `test_connection_fields_are_the_env_vars_the_scraper_reads` fails if they drift.

## Verify, then ship

```
poetry run pytest data/tests/test_manifest.py data/tests/test_source_syncs.py sync/tests/test_sources.py
cd app && npx tsc --noEmit -p . && npx vitest run     # worktree: symlink/`pnpm install` first
```

Shipping a manifest change is three steps, and the panel only appears after all of them:
merge to master (ff in the main checkout, ask first), restart the worker
(`launchctl kickstart -k gui/$(id -u)/me.yarinsa.finance-worker`, see `sync-dev`), `deploy-app`
runs on push, **then publish data** (`sync-data`) because the app reads `snapshot.source_manifests`.
Skipping the data step leaves the Syncs screen on raw source ids.

## Keep this knowledge current

When a manifest field, allowed value, consumer or rule changes, update in the same commit:
this file, the "Source manifests" section of CLAUDE.md, and `add-bank-source` step 7 if the new-source
steps changed. Planned, not built: submitting connection values (needs the user's sign-off, see Rules).
