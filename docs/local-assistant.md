# Local assistant (proof of concept)

A tool-calling assistant that runs on a local open model (Qwen via Ollama) over the digested ledger. Nothing leaves the Mac.

```
poetry run python -m assistant "כמה הוצאתי באוקטובר לפי קטגוריה?"   # one question
poetry run python -m assistant                                      # chat
```

## How it is wired
- `assistant/llm.py` — OpenAI-compatible client. **The model is config**: `ASSISTANT_BASE_URL` (default Ollama `localhost:11434/v1`) and `ASSISTANT_MODEL`. Any server that speaks `/chat/completions` works.
- `assistant/tools.py` — read-only tools (`spending_by_category`, `monthly_totals`, `search_transactions`, `snapshot_totals`) over `data/digested/`; the model never reads raw dumps and never re-derives `kind`/`category`. Spending excludes own transfers, card settlements and savings, and nets offsets.
- `assistant/agent.py` — the tool loop (max 6 steps), strips `<think>` blocks.
- Data dir: `FINANCE_DIGESTED_DIR` (a worktree has no `data/digested`; point it at the main checkout).

## Running the model
Standalone Ollama binary in `~/.local/ollama/` (Homebrew install failed). `./ollama serve`, then `./ollama pull qwen3:30b-a3b-instruct-2507-q4_K_M` (~18 GB, non-thinking: the plain `qwen3:30b` reasons for a minute on a one-line prompt).

## Not done yet
Read-only and CLI-only. No API endpoint or dashboard panel (those need the tenant/auth layers and a GraphQL schema), no writes, no evals beyond the unit tests, and Ollama does not start on login.
