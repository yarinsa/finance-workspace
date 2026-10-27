# PRD 11 — Goals editor (עריכת יעדים)

> **Native feature** (not reverse-engineered from Plangram). Plangram edits goals
> on a separate `/my-plan/goals` profile route (referenced in
> [04-goals.md](04-goals.md) §2, §4a); this PRD specifies *our* thin author/edit
> surface for the user-owned store. Hebrew (RTL), ILS (₪).

## 1. Summary

The Goals screen ([04-goals.md](04-goals.md)) is **read-only** — it renders
`data/digested/goals.json`. The underlying data lives in the user-owned store
`data/goals/goals.json` and today the only way to change it is **hand-editing JSON
then running `python3 data/goals.py`**. This PRD adds the missing **write path**:
set the two plan targets, and add / edit / delete personal goals — without touching
JSON by hand.

It deliberately splits into two independently shippable layers:

1. **CLI** — a small `argparse` surface on `data/goals.py` (or a sibling) that
   mutates the store and re-digests in one step. Ships first; zero new infra.
2. **In-app editor** — an `/goals/edit` (or inline-edit) React surface. Needs a
   tiny write-back mechanism because the app is currently a static reader (§5).

## 2. Goals & non-goals

**Goals**
- Set `emergency_fund_target`, `inheritance_target`, and (optional)
  `retirement_target` from outside a text editor.
- Add / edit / delete a personal goal (`description`, `amount`, `end_date`, and the
  recurring fields `interval`/`repetitions`/`rise`).
- Re-run the digest automatically after any mutation so `goals.json` stays current.
- Validate input (amount > 0, valid ISO date, unique id) before writing.

**Non-goals (for v1)**
- The probabilistic `% סיכוי` model — still deferred (PRD 04 §4b).
- Per-asset funding (`from_asset_id`) wiring — blocked on asset capture (PRD 07);
  keep the field editable but unused.
- Multi-user / auth. Single household, single store.
- Undo history beyond a single `.bak` written before each mutation.

## 3. Data model (unchanged store)

Same `data/goals/goals.json` schema from [04-goals.md](04-goals.md) §6 — this PRD
only adds mutation, not new fields:

```jsonc
{
  "emergency_fund_target": 0,    // ₪
  "inheritance_target": 0,       // ₪
  "retirement_target": 0,        // ₪ (optional; 0 ⇒ derive from projection)
  "goals": [
    { "id", "description", "amount", "start_date", "end_date",
      "interval", "repetitions", "rise", "from_asset_id" }
  ]
}
```

Mutation rules:
- **`id`** auto-generated from a slug of `description` + year if omitted; must stay
  unique. Editing matches on `id`.
- Writing is **atomic**: write to `goals.json.tmp`, then rename; keep one `.bak`.
- Every successful mutation ends by invoking `goals.main()` to refresh the digest.

## 4. CLI surface (Layer 1 — ship first)

```
python3 data/goals.py --set-emergency 60000
python3 data/goals.py --set-inheritance 1000000
python3 data/goals.py --set-retirement 2500000
python3 data/goals.py --add "רכב חדש" --amount 80000 --by 2027-12-31 \
                      [--interval yearly --repetitions 3 --rise 0.03]
python3 data/goals.py --edit car-2027 --amount 90000
python3 data/goals.py --remove car-2027
python3 data/goals.py --list
```

- No flags → behaves exactly as today (digest only), so existing usage is intact.
- Any mutating flag → apply to the store, then re-digest, then print the changed
  rows. `--list` prints current targets + goals with ids.
- Validation errors exit non-zero with a Hebrew-or-English message, no partial write.

## 5. In-app editor (Layer 2)

The app is a static reader (Vite imports `@digested/*.json`); it has no write path.
Options, cheapest first:

| Approach | How | Trade-off |
|---|---|---|
| **A. CLI only, app read-only** | Editor button deep-links to docs / shows the CLI command | zero infra; not really "in-app" |
| **B. Tiny dev write-server** | A small Node/Express (or Vite middleware) `POST /api/goals` that writes the store + runs `goals.py` | one process; local-only, fine for a single-household tool |
| **C. Tauri / file API** | Native file write | heavier than warranted |

**Recommended: B** (superseded: built on the ledger API, see §6). A `vite` dev-server plugin exposing `GET/POST /api/goals`
(read store, write store + re-digest) keeps everything in one `pnpm dev`. The
`/goals` screen gains an **edit mode**: inline target fields + an "add goal" form +
per-card edit/delete. On save → `POST` → re-digest → re-fetch `goals.json`.

UI (RTL), on top of the existing read-only cards:
```
יעדים כללים            [ ✎ עריכה ]
  קרן חירום   [ 60000 ₪ ]
  הורשה       [ 1000000 ₪ ]
  פרישה       [        ₪ ]  (ריק ⇒ נגזר מהתחזית)

יעדים אישיים           [ + הוספת יעד ]
  ┌ רכב חדש        ✎  🗑 ┐
  │ ₪80,000 · עד 31/12/2027 │
  └──────────────────────────┘
```
Add/edit form fields: `description`, `amount`, `end_date` (date picker),
collapsible "מתקדם" for `interval`/`repetitions`/`rise`.

## 6. Implementation plan

**Phase 1 — CLI (no new infra)** — ✅ **done**
1. ✅ `argparse` on `data/goals.py`: `--set-emergency/-inheritance/-retirement`,
   `--add … --amount … --by …`, `--edit`, `--remove`, `--list`. No flags = digest only.
2. ✅ `load_store()` / `save_store()` with atomic write (`.tmp`→rename) + `.bak`;
   random-suffixed `slug_id`; validation (amount > 0, ISO date, unique id).
   Invalid input → `argparse` error, exit 2, **no partial write**.
3. ✅ Every run re-digests via `main()`. Tests in `data/tests/test_goals.py`
   (`TestStoreMutations`): add / edit amount / remove / reject bad amount / bad
   date / duplicate + unknown id.

**Phase 2 — In-app editor** — implemented on the ledger API (not the Vite dev server)
4. The three general targets moved into Postgres `plan_targets` (`db/goal_store.py`
   `get_targets` / `set_targets`; `goal_store.py import` copies the JSON values once) and are
   exposed over GraphQL: query `planTargets`, mutation `planTargetsUpdate`. Personal goals
   were already in the `goals` table (`goalCreate` / `goalUpdate` / `goalDelete`, REST
   `/api/goals`). Every mutation signals a ledger rebuild, whose digest reads both from the DB
   (`data/goals.py`), so `goals.json` stays current. See `docs/ledger-api.md`.
5. `/goals` edit mode: target inputs + add/edit/delete form; optimistic save then
   re-fetch. Reuse the existing cards for display.
6. Guard: with the Mac off the API is unreachable and the UI falls back to the static JSON,
   read-only (the ledger API's usual kill switch); no dev-only gating needed.

## 7. Open questions

- **Write path** — resolved: the ledger API (approach B's job, without the dev-only server).
- **Recurring goals in the digest** — `interval`/`repetitions`/`rise` are stored but
  `goals.py` doesn't yet expand them into multiple dated occurrences. Expand on
  read, or defer until the per-goal probability model lands?
- **id stability** — slug-from-description risks collisions on rename. Use a short
  random id instead and never derive from text?
- **Validation locale** — Hebrew error messages in the UI; English in the CLI, or
  Hebrew in both?
