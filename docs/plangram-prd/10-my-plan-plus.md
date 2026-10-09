# PRD 10 — "התוכנית שלי / Plus" (my-plan)

> Reverse-engineered from Plangram's `/my-plan` route.
> Hebrew (RTL), ILS (₪).
> Evidence: `captures/route-my-plan.yml`, `captures/route-my-plan.png`.
> **Status: NOT CAPTURABLE on the free tier — documented as a known gap.**

## 1. Summary

`/my-plan` is Plangram's **interactive scenario / what-if planning** surface — the
Plus-tier "תכנון פלוס" feature the rest of the app keeps pointing at (the nav has a
`תכנון פלוס` item; the Timeline and other pages upsell to `/plus-signup`). In the
captured (free) account this route rendered as a **single empty `<iframe>` with no
text content** — the entire `route-my-plan.yml` accessibility tree is:

```yaml
- iframe [ref=e3]:
```

i.e. the planning UI is embedded in a paywalled iframe that did not load any
content for a non-Plus user. We therefore **cannot reverse-engineer its anatomy or
data bindings from the captures** — this PRD documents what it is, why it is blank,
and what capturing it would require.

> Note: `/my-plan` is *also* the prefix for the plan-entity editor routes that **do**
> render in the free tier — `/my-plan/income`, `/my-plan/expense`, `/my-plan/goals`,
> `/my-plan/assets`, `/my-plan/debt` (visible in the nav of `route-metrics.yml` /
> `route-timeline.yml`). Those entity editors are separate, capturable, and out of
> scope here; this PRD is specifically about the **bare `/my-plan` Plus iframe**.

## 2. What it likely contains (inferred, unverified)

From the surrounding nav labels (`תכנון פלוס`, "סימולציית פלנגרם"), the
`/plus-signup` upsell copy, and the `scenario_schema` in
`captures/cashflow-schema.json`, the feature is almost certainly an **interactive
scenario simulator**: edit assumptions and watch the whole projection (Cashflow,
Networth, Timeline, Metrics) recompute.

Editable inputs strongly implied by `scenario_schema`:

```jsonc
{
  "id", "name",
  "retirementAge", "partnerRetirementAge",   // drag retirement earlier/later
  "globalEmergencyFund",                      // target emergency-fund size (₪)
  "globalInheritanceFund",                    // target inheritance to leave (₪)
  "netWorthAtRetirement",                     // computed output of the sim
  "isConservativeForecast",                   // toggle return assumptions
  "inflationRate",
  "isDefault", "updatedDate"
}
```

The free tier exposes exactly **one** scenario (`top_level.n_scenarios: 1`,
`currentScenarioId`); Plus likely unlocks **multiple named scenarios** plus the
ability to author/compare them (the `scenarios` array). Expected interactions:

- Edit `retirementAge` / `partnerRetirementAge` and re-run the life-path projection.
- Adjust `inflationRate` and `isConservativeForecast` to stress-test the forecast.
- Set `globalEmergencyFund` / `globalInheritanceFund` targets that feed the
  goal-compliance metrics (PRD 08 §6 footnotes 3–4).
- Create / clone / compare multiple scenarios side by side; read
  `netWorthAtRetirement` as the headline output of each.

All of the above is **inference from schema + nav copy only** — none of it is
confirmed against a rendered DOM, because the iframe was empty.

## 3. Why we can't capture it

- The route is **Plus-gated**: the planning UI loads inside an iframe that stays
  empty for a free account, and the app routes free users to `/plus-signup`.
- Capturing the real anatomy/data bindings would require an **active Plus
  subscription**, then re-running the DOM + screenshot capture against `/my-plan`
  (and likely watching the network for a scenario-edit/recompute endpoint).
- **Action item:** acquire Plus, re-capture `/my-plan` (DOM + screenshots +
  the scenario read/write API calls), then write the real PRD.

## 4. Mapping to our data

We already hold the raw materials to *build* a scenario simulator even though we
can't see Plangram's:

- **`data/projection.py`** already runs a forward net-worth projection over
  `snapshot.json` with assumptions in `projection.CONFIG` (`current_age`,
  `retirement_age=67`, `end_age=90`, `real_return=0.04`). Our "scenario" is today a
  **hardcoded config**, not an editable entity.
- To match Plus we would promote `CONFIG` into an **editable scenario object**
  (the `scenario_schema` shape above), let the user change `retirementAge` /
  `inflationRate` / fund targets, and re-emit `cashflow.json` + the timeline. This
  is the natural home for the emergency-fund and inheritance targets that PRD 08's
  goal-compliance metrics need.

**Gap:** no scenario-authoring/persistence layer yet (single hardcoded scenario);
no multi-scenario compare. Both are net-new for us, independent of capturing
Plangram's exact UI.

## 5. Implementation plan (suggested)

This is intentionally brief — the feature is unverified.

1. **Defer until Plus-captured.** Do not reverse-engineer the UI from guesses.
2. **Meanwhile**, promote `projection.CONFIG` → a persisted, editable scenario
   object matching `scenario_schema`; expose `retirementAge`, `inflationRate`,
   `isConservativeForecast`, `globalEmergencyFund`, `globalInheritanceFund`.
3. On edit, re-run `projection.py` + `cashflow.py` and refresh the dependent
   screens (Cashflow, Networth, Timeline, Metrics).
4. **Multi-scenario** (clone / name / compare, `netWorthAtRetirement` per scenario)
   is a later phase — only after we've seen Plangram's real layout.

## 6. Open questions

- **Acquire Plus to capture?** Worth a subscription to reverse-engineer the real
  simulator UI, or build our own from the projection engine and skip parity?
- **Persistence** — where do user-edited scenarios live (a `scenarios.json`
  alongside the digested outputs)? Single household, so likely a local file.
- **Recompute cost** — is the projection cheap enough to re-run live on every slider
  drag, or do we debounce / recompute on "apply"?
- **Scope of editability** — mirror Plangram's full scenario field set, or expose
  only the few assumptions that meaningfully move our (simpler) projection?
