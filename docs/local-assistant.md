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

## Live state (2026-11-01)
On: Ollama runs as the `me.finance.ollama` LaunchAgent, `.env` sets the URL and `FINANCE_API_ASSISTANT_MODEL=gemma4:26b`, the dashboard shows the chat button (`app/src/components/assistant/`). Only `gemma4:26b` is installed; Qwen3-30B was removed after the comparison above.
Trap: the API image copies only the packages listed in `api/Dockerfile` and `api/Dockerfile.dockerignore`. `api/assistant_chat.py` imports `assistant/`, so both files list it; a new top-level package the API imports needs both lines, or the container crash-loops on start. Run the new image once before swapping it in.

## Not done yet
Read-only. No writes, no net-worth/debt answers through the API (it does not serve `snapshot`), no eval set beyond the unit tests, and no availability flag: the button shows until the first `assistant_off` reply (an `assistant` flag on `/api/health` would hide it from the start).
