# Local assistant (proof of concept)

A tool-calling assistant that runs on a local open model (Qwen via Ollama) over the digested ledger. Nothing leaves the Mac.

```
poetry run python -m assistant "כמה הוצאתי באוקטובר לפי קטגוריה?"   # one question
poetry run python -m assistant                                      # chat
```

## How it is wired
- `assistant/llm.py` — OpenAI-compatible client. **The model is config**: `ASSISTANT_BASE_URL` (default Ollama `localhost:11434/v1`) and `ASSISTANT_MODEL`. Any server that speaks `/chat/completions` works.
- `assistant/tools.py` — a `Toolbox` of read-only tools (`spending_by_category`, `monthly_totals`, `search_transactions`, `snapshot_totals`) bound to a ledger backend; the model never reads raw dumps and never re-derives `kind`/`category`. Spending excludes own transfers, card settlements and savings, and nets offsets. Model-supplied arguments are validated (`YYYY-MM`) and results capped (50 rows, 24 months); errors come back as data.
- `assistant/ledger.py` — the backend interface (`rows()`, `snapshot()`). `JsonLedger` reads the digested files (CLI, master household only). `api/assistant_ledger.py::DbLedger` wraps the API's tenant-bound `Ledger` loader, so the chat endpoint sees only the caller's tenant (`api/tests/test_assistant_isolation.py`). `snapshot_totals` is offered only when the backend has a snapshot: the API does not serve one yet, so it is absent from the DB backend.
- `assistant/agent.py` — the tool loop (max 6 steps), strips `<think>` blocks.
- Data dir: `FINANCE_DIGESTED_DIR` (a worktree has no `data/digested`; point it at the main checkout).

## Running the model
Standalone Ollama binary in `~/.local/ollama/` (Homebrew install failed). `./ollama serve`, then `./ollama pull gemma4:26b` (~16 GB). Compared 2026-11-01 on three real questions: same numbers as Qwen3-30B-A3B-instruct, but Gemma had clean Hebrew and the full debt breakdown while Qwen leaked an Arabic-script word. The plain `qwen3:30b` reasons for a minute on a one-line prompt.

## In the dashboard (API + chat)
`POST /api/assistant/chat` (contract: docs/ledger-api.md) runs the same tools on the caller's tenant. The API container reaches
Ollama as `host.docker.internal:11434` (verified: it works while Ollama listens on `127.0.0.1` only; keep it there, Ollama has no auth).
To turn it on, the user does these outward steps:
1. `infra/ollama.sh` — Ollama as a login LaunchAgent (`--off` removes it). Stop any manual `ollama serve` first.
2. `.env`: `FINANCE_API_ASSISTANT_URL=http://host.docker.internal:11434/v1` (+ optional `FINANCE_API_ASSISTANT_MODEL`).
3. `docker compose --profile api up -d --build api` from the main checkout, once this branch is merged.
Unset URL = the assistant is off (503 `assistant_off`) and the UI hides the chat. Kill switch: `infra/ollama.sh --off` or clear the URL.

## Not done yet
Read-only. No dashboard chat sheet yet, no writes, no net-worth/debt answers (the API does not serve `snapshot`), no evals beyond the unit tests.
