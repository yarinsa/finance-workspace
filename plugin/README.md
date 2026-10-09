# finance-copilot

**Let Claude be the UI for your personal finances.** Instead of a dashboard app,
this Claude Code plugin scrapes your Israeli banks/cards/aggregator, digests
everything into one deduped ledger + a net-worth snapshot, and answers money
questions straight from chat.

Currency is ILS (₪). Hebrew categories throughout.

## What you get

| Command | Does |
|---|---|
| `/finance [question]` | Ask anything — spending, cashflow, net worth, debt, savings, goals, forecast, retirement. Empty → an overview. |
| `/finance-refresh [source]` | Re-scrape a source. You log in manually in Chrome; credentials are never typed for you. |
| `/finance-digest [--no-normalize]` | Rebuild digested outputs from already-scraped data (no login). |
| `/finance-goal …` | View/set goals — emergency-fund / inheritance / retirement targets, add/edit/remove personal goals. |

Plus the underlying skills: a `finance` query skill, a `finance-refresh`
dispatcher, per-source refresh skills (cal, amex, discount ×3, leumi, harel,
riseup), `add-bank-source`, and `playwright-cli`.

## Install

```
/plugin marketplace add <owner>/finance-copilot
/plugin install finance-copilot
```

Then set up your **private** data + config (never committed):

```
cp config/.env.example .env
cp config/finance.config.example.json finance.config.json   # optional
export FINANCE_DATA_DIR=/path/to/your/private/finance-data   # or set data_dir in config
pip install -r requirements.txt   # pipeline deps (stdlib-mostly; pytest for tests)
npm i -g @anthropic/playwright-cli # + a Chromium for the scrapers
```

First run:

```
/finance-refresh          # walk through each source, logging in yourself
/finance-digest           # build the ledger + snapshot + cashflow/forecast/goals
/finance "how am I doing?" # ask away
```

## Data & privacy

The plugin ships **code only**. Your financial data and any secrets stay in your
own `FINANCE_DATA_DIR` and local `.env` — the plugin's `.gitignore` refuses to
track `.env`, `finance.config.json`, `MEMORY.md`, `data/`, and `*.xlsx`.

The refresh skills use **manual browser login** — no passwords are stored or typed
by the plugin. The optional `israeli-bank` MCP (which does hold credentials) is
**not** part of this plugin; run it privately if you want automated auth.

## How it works

```
<source>/raw/  --(<source>/normalize.py)-->  <source>/normalized/*.json
                                                     |
                                            scripts/digest.py
                                                     |
        digested/{transactions,snapshot,cashflow,forecast,goals}.json  ← the finance skill reads these
```

`scripts/_paths.py` resolves your data dir (`$FINANCE_DATA_DIR` → `finance.config.json`
→ `./data`). Everything downstream is read-only over scraped data and safe to re-run.

## Roadmap

- **Phase 2 — MCP tools** for "any AI" portability: `get_cashflow`, `get_goals`,
  `set_goal`, `run_digest`, … wrapping the same scripts.
