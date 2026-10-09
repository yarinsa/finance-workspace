---
description: Re-scrape a bank/card/aggregator source (you log in manually in Chrome), then digest.
argument-hint: [cal | amex | discount-account | discount-business | discount-mortgage | leumi | harel | riseup]
---

Refresh raw source data by driving a logged-in Chrome over CDP. Delegates to the
**finance-refresh** skill.

Source: $ARGUMENTS

- If a source is named, activate its refresh skill (`<source>-refresh`) and follow
  its flow. **You never type the user's credentials** — the user logs in themselves
  in the visible Chrome window.
- If `$ARGUMENTS` is empty, list the available sources and ask which to refresh (or
  offer to walk through several, one at a time — each needs its own manual login).
- Refreshing opens a browser and re-scrapes: it is the **confirm-first** tier.
- After a successful scrape, offer to run `/finance-digest` to rebuild the digests.
