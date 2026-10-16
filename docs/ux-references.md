# UX references (Mobbin)

Design references gathered from Mobbin (iOS) for the Plangram dashboard (`app/`).
Use them when designing a new screen: pick the pattern, cite the screen, adapt to
Hebrew RTL and ₪. Mobbin links need a Mobbin login; the Mobbin MCP connector
(`search_screens` / `search_flows`) can pull more.

Gathered 2026-10-16 while choosing the next feature (→ balance runway, below).

## Feature map: what we have vs. what the references show

| Pattern | Status in app | Best references |
|---|---|---|
| Projected daily balance to payday, low-point warning | **Building**: `/runway` (יתרה צפויה) | bunq, Monzo, Quicken, Cash App |
| Safe-to-spend / per-day allowance | **Building**: hero card on `/runway` | Rocket Money, Cleo, Revolut, Quicken |
| Upcoming bills with balance-after per row | **Building**: list on `/runway` | Quicken, Copilot |
| Bills / subscriptions calendar | Not started; natural second view of runway data | Rocket Money, Orbit |
| What-if scenario simulator (sliders → future net worth) | Stub (`/my-plan`, תכנון פלוס) | Wealthfront, Monzo, Stake |
| Loan / prepayment simulator | Not started; pairs with the "הקטנת התשלום" advice in CLAUDE.md | Zopa, Shopee |
| Category budgets with "left to spend" | Not started (RiseUp owns envelopes) | YNAB, Monarch, Copilot, Buddy |

## Patterns worth copying

### Balance projection
- **bunq: Balance Prediction.** Solid line for actual balance, dotted line for the forecast, a tooltip on the low point, and a plain-language warning card under the chart ("you may not make the end of the month"). <https://mobbin.com/screens/f5ca0ce0-971b-4d41-a5e3-d957be27fbec>
- **Monzo: Trends → Balance.** End-of-day balance with a dashed "today" divider and an `EST` label on the projected end balance. <https://mobbin.com/screens/25125eda-5e62-4166-9a68-9b25bcc349b6>
- **Quicken: Projected Cash Flow.** "Today's balance" vs "Projected on <date>", then a list of reminders, each showing **amount + projected balance after it**. This is the clearest way to show a timing deficit. <https://mobbin.com/screens/7bb55ca0-a5c5-4002-86f7-67a3f990d02d>
- **Cash App: 7-day forecast.** A narrative paragraph under bars ("predicted ceiling until something changes"), which shows the value of explaining the number in words. <https://mobbin.com/screens/ff659acb-042c-426c-ab5f-e376c58325c6>
- **Cleo: Balance graph** with a trend line. <https://mobbin.com/screens/df4573d4-353b-4fe4-b97c-e1af054ea5e2>

### Safe to spend
- **Rocket Money.** "$455 left to spend" plus a pill reading "$45/day for 10d"; "Bills $0 left to pay" and "Earnings $310 to earn" tiles; an "At Risk" savings target with a recovery hint ("slow spending to $45/day"). <https://mobbin.com/screens/4df264c7-321a-4c5e-9a46-43bac516a471>
- **Cleo.** In vs Out for the month, "$X until <payday>" and "$Y per day", with Bills Due below. <https://mobbin.com/screens/a252fcfd-1c89-43d2-a090-7c70d5af3c5c>
- **Quicken: Income after bills.** Income − (fixed + savings goals) = available, broken down into Income / Bills / Subscriptions / Transfers / Savings Goals. <https://mobbin.com/screens/4e682c2f-08b1-4776-a0ef-1e901778fc94>
- **Revolut: Budget.** Spent / Upcoming / Left to spend, with ₪/day per allocation. <https://mobbin.com/screens/519ee7b9-37d5-41ca-99d9-729905be9547>

### Recurring bills
- **Copilot: Recurrings.** A "left to pay / paid so far" ring above a this-month list ordered by day, with checkmarks on paid rows. <https://mobbin.com/screens/b4297200-6207-407b-a4b6-53ce337d9c5e>
- **Rocket Money: Calendar.** Merchant logo and amount chip on each due day, with a footer totalling bills vs subscriptions. <https://mobbin.com/screens/0fe3af19-4929-4cff-b324-2929d7ddc5a2>
- **Orbit: Subscription calendar.** Total vs Upcoming header. <https://mobbin.com/screens/954dab6c-e3ed-4104-aae0-e5039bd5012f>
- **Origin: Recurring.** Grouped by frequency (biweekly / monthly / annual / inactive), with an amber "due in 2 days". <https://mobbin.com/screens/3441dd7a-d41e-4406-950a-299684f6dc02>

### What-if / simulators (for `/my-plan`)
- **Wealthfront: Retirement.** A verdict headline ("You're more than covered"), the projection chart, then a "My planned savings" slider with an undo, then editable assumptions. <https://mobbin.com/screens/0687053c-46dd-4469-826e-312cfb03c535>
- **Monzo: How your money could grow.** Deposits line vs projection with a likely-range band, plus a monthly-deposit slider. <https://mobbin.com/screens/a196ebe3-0c04-4b4e-8241-201b961696a7>
- **Stake: Compound interest calculator.** Inline editable values in a sentence ("Projection of $10,000 + $1,000 every month earning 5.5%"). <https://mobbin.com/screens/88680915-5c5d-4d37-9738-a97d4b8453c3>
- **Zopa: Loan options.** Amount + term → monthly payment / APR / total repayable. Good shape for a prepayment simulator. <https://mobbin.com/screens/80cabd17-e5b9-45b4-a688-450445b8bf79>

## Principles we took from them
1. **Lead with one number and a verdict** (safe to spend, short by ₪X), then the chart, then the detail list.
2. **Show balance-after on every upcoming item.** Timing deficits are only visible this way.
3. **Mark the low point and payday on the chart.** Draw the floor (₪0) and the overdraft limit as reference lines. The overdraft is debt capacity, not cash (see the `cashflow-mgmt` skill).
4. **Label confidence.** Inferred items (card bills estimated from last month) get a "משוער" tag. Never show false precision.
5. **Explain in words** under the chart, the way bunq and Cash App do.
