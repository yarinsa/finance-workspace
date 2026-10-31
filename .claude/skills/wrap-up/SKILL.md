---
name: wrap-up
description: Finish a piece of work and its session cleanly: verify, update docs/memory/issues, merge and push, remove temp state, report. Use when the user says wrap up, finish, ship it or close the session.
---

# Wrap up

Leave the repo, the live systems and the knowledge in a state the next person (or session) can pick up
without asking. Work in this order; stop and report at any step that fails instead of papering over it.
Everything outward (merge, push, delete a branch, restart a service, open or edit an issue) follows the
user's go-ahead: ask once with the full list, then do it.

## 1. Verify what you are about to leave behind

- `git status` clean except what you mean to commit; no stray files (`/tmp` scratch is fine, files in the repo are not).
- Run the checks the change touches: `poetry run pytest` (api/sync/data), `cd app && npx tsc -b && pnpm exec vitest run`,
  `poetry run python -m api.codegen.generate --check` and `pnpm codegen:check` after any SDL change.
- Say what you could **not** verify (live service, browser, DB tests that skip without `DATABASE_URL`). Never
  report "works" for a path only a fake exercised.

## 2. Leave no traces in live systems

- Delete throwaway data you created while testing (a test secret in the vault, a scratch tenant, a test row,
  a temp env file, a started container you do not need). Check with the same tool that created it.
- Nothing secret in the repo, a commit, an issue, a doc or a log: names only, never values. Credentials stay
  in `.env` / the vault; generated passwords go to a 0600 file and the user is told where.
- Services you changed are running the merged code (e.g. `docker compose --profile api up -d --build api`,
  worker `launchctl kickstart`), not a stale build. Check health afterwards.

## 3. Keep it maintainable

- **Docs:** update the file that owns the topic (see the table in the root `CLAUDE.md`): the area `CLAUDE.md`,
  `docs/<topic>.md`, the README. Record current state, how to operate it, and the non-obvious facts learned
  (API quirks, ordering traps). Remove statements that are now false; do not leave a plan next to the result.
- **Tests:** a bug fixed has a regression test from the real case (root `CLAUDE.md`, "Bugs → tests").
- **Memory:** update the entry in `~/.claude/projects/-Users-yarinsa-Code-Finance/memory/` that the work
  changes (or add one if a new durable fact is not derivable from the code); keep `MEMORY.md` one line each.
  Household facts the data cannot show go in the gitignored `MEMORY.md` at the repo root.
- **Issues:** update the tracking issue (tick what is done, correct what changed); open one per real gap:
  unverified path, accepted trade-off, pre-existing failure you noticed. Label `tech-debt` for shortcuts.
  No duplicates: `gh issue list` first.

## 4. Ship

1. Commit on the branch with a message that says why. No Claude/AI attribution lines (the user's rule).
2. **Rebase on master first**, then run the tests again if the rebase pulled in anything: master moves while you work.
3. Ask: "merge and push?". On yes, from the main checkout (`/Users/yarinsa/Code/Finance`):
   `git merge --ff-only <branch>`, then check `git log origin/master..master` holds only your commits, then
   `git push origin master`. **No pipes before `&& git push`** (a piped ff failure still pushed once). Untracked
   drafts in the main checkout can block the ff: diff them against the commit before removing.
4. Check the deploy: `gh run list --limit 3` (the app workflow runs only for `app/**`, `infra/deploy.sh`, the
   workflow file). Data changes need `sync-data`; app changes `deploy-app` only if CI did not run.
5. Tell the user the remaining *user-only* steps (Terraform apply, secrets into `.env`, Tailscale, opting a
   tenant in, backups) as a short numbered list.

## 5. Close the session

- Branch and worktree: delete the remote branch only after `git cherry origin/master <branch>` shows it is
  contained (a rebased commit is not an ancestor, so `merge-base --is-ancestor` can say no); the permission system may
  require the user to run the delete or allow it. Remove your own worktree/local branch only when merged.
  **Never touch another session's worktree** (locked ones, other `bridge-*` or named worktrees).
- Final message, short: what shipped (commit), what was verified and how, what was not, issues opened or
  updated (numbers), user steps. No restating of the diff.

## Do not

- Merge, push, restart live services, delete branches or edit issues without the go-ahead.
- Apply Terraform or a live migration (root `CLAUDE.md`).
- Run a credential step the user owns (logins, OTPs, secrets typed into `.env`), except a script the user asked for.
- Leave a "TODO later" only in your head: it is a doc line, a memory, or an issue.
