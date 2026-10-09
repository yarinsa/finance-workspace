---
description: Ask anything about your money — spending, cashflow, net worth, debt, savings, goals, forecast, retirement.
argument-hint: [question]
---

Answer the user's finance question using the **finance** skill.

Question: $ARGUMENTS

- If a question was given, route it: map it to the right digest(s) per the finance
  skill's digest→question map, read from `<data_dir>/digested/`, and answer in plain
  language (₪ ILS, Hebrew categories glossed, state freshness).
- If `$ARGUMENTS` is empty, give a quick **overview**: current net worth and debt
  from `snapshot.json`, this month's `today{income,expense,net}` and the top
  `metrics[]` from `cashflow.json`, and whether the snapshot is stale.
- Reads auto-run. Never mutate anything from this command.
