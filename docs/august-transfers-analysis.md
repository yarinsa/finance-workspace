# August 2026 העברות (transfers) analysis

Analysis only — no code changes made. Source: `data/digested/transactions.json`
(generated_at per the file), cross-checked against `data/leumi/raw/transactions.json`,
`data/discount/raw/userAccountsData.json`, `data/leumi/raw/accounts.json`, and
`data/digest.py`'s existing classifiers.

## 1. Reproducing the ₪21,658 figure

`spending_summary()` in `data/digest.py` (line ~409) sums `by_category` from
**outflows only** (`amt < 0`, not `is_income`, not `internal_transfer` /
`card_bill_payment` / `savings`) — it never nets against inflows in the same
category. Summing exactly that rule over category `העברות` in August reproduces
the reported figure exactly:

| Date | Amount | Description | Origin |
|---|---:|---|---|
| 2026-08-02 | -200 | העברה בBIT | amex |
| 2026-08-05 | -6,800 | הו"ק לעיין ניהול נכסי,לסניף 20-406 | discount |
| 2026-08-07 | -1,000 | PAYBOX | amex |
| 2026-08-07 | -150 | העברה ב BIT בנה"פ | cal |
| 2026-08-09 | -948.53 | פרעון העברות לקרדיט | amex |
| 2026-08-09 | -204.91 | פרעון העברות לקרדיט | amex |
| 2026-08-09 | -2,650.19 | פרעון העברות לקרדיט | amex |
| 2026-08-09 | -5,212.89 | פרעון העברות לקרדיט | amex |
| 2026-08-09 | -1,183.48 | פרעון העברות לקרדיט | amex |
| 2026-08-11 | -600 | העברה לאסף בללי וירין ש בנק 10,ל 10-998-0002593739 | discount |
| 2026-08-12 | -558 | העברה לשובל ששון בנק 10,ל 10-816-0002283168 | discount |
| 2026-08-12 | -450 | העברה לדקלה בלמס בנק 20,ל 20-433-0000225435 | discount |
| 2026-08-18 | -250 | העברה בBIT | amex |
| 2026-08-21 | -1,000 | PAYBOX | amex |
| 2026-08-23 | -450 | הע. לדקלה בלמס בסניף 20-433 | discount |
| **Total** | **21,658.00** | | |

This is the exact set — sum verified to `21658.00`.

## 2. Every 2026-08 row touching העברות / הו"ק / זיכוי / משיכה (full list, 44 rows)

Full list pulled (category == `העברות` OR description matches those keywords),
with current classifier flags:

```
2026-08-02  -200.00  העברה בBIT                              amex      cat=העברות   flags: none
2026-08-02  -870.00  הו"ק לירין ששון,לסניף 10-806            discount  cat=העברות   internal_transfer=True
2026-08-02   210.00  העברה מירין ששון,...משיכה לחשבון בנק    discount  cat=העברות   internal_transfer=True, income=True
2026-08-02  3400.00  הו"ק מבללי אסף,מסניף 11-034              discount  cat=העברות   income=True, flags: none
2026-08-03     8.25  מענק בנק לאומי                            leumi     cat=העברות   income=True
2026-08-03   323.26  מענק בנק לאומי                            leumi     cat=העברות   income=True
2026-08-04 -2500.00  העברה לששון ירין                         discount  cat=העברות   internal_transfer=True
2026-08-05 -6800.00  הו"ק לעיין ניהול נכסי,לסניף 20-406       discount  cat=העברות   flags: none  (RENT — real expense)
2026-08-05  1844.42  העברה לפיגור                              leumi     cat=העברות   income=True
2026-08-05  1507.00  העברה לפיגור                              leumi     cat=None     income=True
2026-08-05   337.40  העברה לפיגור                              leumi     cat=None     income=True
2026-08-06  2124.00  העברה מדרורית מלינרסקי,10-816-0330-...   discount  cat=כללי     income=True (3rd-party refund)
2026-08-07 -1000.00  PAYBOX                                    amex      cat=העברות   flags: none
2026-08-07  -150.00  העברה ב BIT בנה"פ                        cal       cat=העברות   flags: none
2026-08-07   400.00  העברה מירין ששון,...                     discount  cat=העברות   internal_transfer=True, income=True
2026-08-07   450.00  העברה מירין ששון,...                     discount  cat=העברות   internal_transfer=True, income=True
2026-08-09  1000.00  מפייבוקס שלי-י                            leumi     cat=העברות   income=True
2026-08-09    40.00  העברה מירין ששון,...                     discount  cat=העברות   internal_transfer=True, income=True
2026-08-09    75.00  העברה מירין ששון,...                     discount  cat=העברות   internal_transfer=True, income=True
2026-08-09  -948.53  פרעון העברות לקרדיט                       amex      cat=העברות   flags: none (AMEX installment billing)
2026-08-09  -204.91  פרעון העברות לקרדיט                       amex      cat=העברות   flags: none
2026-08-09 -2650.19  פרעון העברות לקרדיט                       amex      cat=העברות   flags: none
2026-08-09 -5212.89  פרעון העברות לקרדיט                       amex      cat=העברות   flags: none
2026-08-09 -1183.48  פרעון העברות לקרדיט                       amex      cat=העברות   flags: none
2026-08-10  -452.00  הו"ק לששון ירין,לסניף 11-034             discount  cat=העברות   internal_transfer=True
2026-08-11  -600.00  העברה לאסף בללי וירין ש בנק 10,10-998...  discount  cat=העברות   flags: none
2026-08-12  1600.00  זיכוי מייד699                            leumi     cat=זיכויים  income=True
2026-08-12  -558.00  העברה לשובל ששון בנק 10,10-816-...       discount  cat=העברות   flags: none
2026-08-12  1300.00  העברה מבללי אסף                          discount  cat=העברות   income=True
2026-08-12  -450.00  העברה לדקלה בלמס בנק 20,20-433-...       discount  cat=העברות   flags: none
2026-08-14  9507.00  משיכה מפיקדון נזיל יומי+                 discount  cat=משיכת פקדון  internal_transfer=True, income=True
2026-08-14  8900.00  משיכה מפיקדון נזיל יומי+                 discount  cat=משיכת פקדון  internal_transfer=True, income=True
2026-08-14   450.00  העברה מירין ששון,...                     discount  cat=העברות   internal_transfer=True, income=True
2026-08-16    41.00  העברה מירין ששון,...                     discount  cat=העברות   internal_transfer=True, income=True
2026-08-17  4200.00  משיכה מפיקדון נזיל יומי+                 discount  cat=משיכת פקדון  internal_transfer=True, income=True
2026-08-18  -300.00  העברה לאקסלנס ניהול השק בנק 12,...        discount  cat=השקעה וחיסכון  savings=True
2026-08-18  -250.00  העברה בBIT                                amex      cat=העברות   flags: none
2026-08-19   300.00  משיכה מפיקדון נזיל יומי+                 discount  cat=משיכת פקדון  internal_transfer=True, income=True
2026-08-21 -1000.00  PAYBOX                                    amex      cat=העברות   flags: none
2026-08-21   450.00  העברה מירין ששון,...                     discount  cat=העברות   internal_transfer=True, income=True
2026-08-23  1000.00  מפייבוקס שלי-י                            leumi     cat=העברות   income=True
2026-08-23  -450.00  הע. לדקלה בלמס בסניף 20-433              discount  cat=העברות   flags: none
2026-08-25   400.00  הו"ק מבללי אסף,מסניף 11-034               discount  cat=העברות   income=True
```

Note: the `2026-08-02 -870 הו"ק לירין ששון,לסניף 10-806` row is already tagged
`internal_transfer=True` because `10-806` is already in `OWN_ACCOUNT_HINTS` —
this existing rule is working correctly for this particular row.

## 3. The Leumi -> Discount salary flow — found, but NOT via the העברות category

Checked `data/leumi/raw/transactions.json` directly (`HistoryTransactionsItems`).
The raw Leumi feed for early August shows:

```
09/08/2026   26144.00  True   העברת משכורת       <- salary lands at Leumi
10/08/2026  -22100.00  False  העברת משכורת_י     <- Leumi -> Discount sweep (note the _י suffix)
```

In the digested ledger, the corresponding rows are:

```
2026-08-09  26144.00  העברת משכורת          leumi     cat=משכורת  income=True   (real income)
2026-08-10  22100.00  בנק לאומי,משכורת       discount  cat=משכורת  income=True   (⚠ same money, arriving at Discount)
```

**This is not in category העברות at all — RiseUp categorizes both legs as
`משכורת` (salary), not `העברות`.** That's why it doesn't show up in the
₪21,658 breakdown, but it IS inflating the ₪97,908 August income figure.

**Does the pair survive as two rows, or collapse via dedup?** It survives as
**two separate rows** — the negative Leumi leg (-22,100 on 10/08) and the
positive Discount leg (+22,100, dated 08-10 in the digested ledger, both same
date) do NOT collapse under the `(date, abs(amount))` dedup key, because in the
digested ledger **only the positive Discount-side arrival exists** — the
negative Leumi-side outflow (`העברת משכורת_י`, -22,100) does not appear in
`transactions.json` at all for August. (It's possible RiseUp itself excludes/
nets this leg on the Leumi side, since RiseUp is the higher-priority copy per
`CLAUDE.md`'s dedup rules, or the raw Leumi negative leg simply wasn't picked
up as a RiseUp "actual".) Either way, net effect: **the ₪22,100 forwarded
salary is currently counted once as income (`בנק לאומי,משכורת`, discount,
+22,100) with no offsetting entry** — i.e. it inflates `total_income` by the
full ₪22,100, on top of the ₪26,144 real salary already counted at Leumi.

For comparison, June's raw Leumi feed shows the OTHER known sweep phrase:
```
04/06/2026  -50000.00  False  העברה דיגיטל   <- matches existing OWN_TRANSFER_DESCRIPTIONS
```
This confirms `OWN_TRANSFER_DESCRIPTIONS = ["העברה דיגיטל"]` is a real, previously
-observed pattern — but it is a **different description string** than August's
`העברת משכורת_י` / `בנק לאומי,משכורת`. **No row in the entire ledger currently
contains "העברה דיגיטל"** — that rule is currently dead code against the live
data (0 matches checked across all months), because the sweep description
varies by month/mechanism (ad hoc "העברה דיגיטל" vs. payroll-linked
"העברת משכורת_י").

## 4. Classification of each remaining (non-internal-tagged) העברות row

### CONFIDENT INTERNAL (own money, own accounts)

- **2026-08-10 `בנק לאומי,משכורת` +22,100 (discount, cat=משכורת)** — the
  Leumi→Discount salary-forwarding leg identified above. Not currently tagged
  `internal_transfer`. **This is the single highest-value miscount found.**
- Rows already correctly tagged (`internal_transfer=True`) and excluded: the
  `העברה מירין ששון,...משיכה לחשבון בנק` roster (small Bit/Hapoalim withdrawals
  back to own bank, ₪40–450 each), `הו"ק לירין ששון,לסניף 10-806` (-870),
  `העברה לששון ירין` (-2500, business↔personal sweep), `הו"ק לששון ירין,לסניף
  11-034` (-452), and the `משיכה מפיקדון` deposit-withdrawal rows. These already
  work as designed — no change needed.

### CONFIDENT EXTERNAL (real third-party payment/income)

- **`הו"ק לעיין ניהול נכסי,לסניף 20-406` -6,800** — RENT, per `CLAUDE.md`
  household notes. Real expense, correctly left uncategorized as internal.
- **`הו"ק מבללי אסף` / `העברה מבללי אסף` (+3,400, +1,300, +400)** — named
  third party ("בללי אסף"), real inbound transfers (rent-share/reimbursement
  from a roommate or similar) — real income.
- **`העברה לאסף בללי וירין ש בנק 10,ל 10-998-0002593739` -600** — named
  third party, real outbound payment.
- **`העברה לשובל ששון בנק 10,ל 10-816-0002283168` -558** — "שובל ששון" shares
  the household surname but is **not** in `OWN_NAMES` (`ירין ששון` / `ששון
  ירין`) — this is a different family member, a real external payment. Do
  **not** widen the name match to "ששון" alone or this becomes a false
  internal-transfer.
- **`העברה לדקלה בלמס בנק 20,ל 20-433-0000225435` -450 (×2, incl. the
  `הע.` abbreviated variant on 08-23)** — named third party, real recurring
  outbound payment.
- **`פרעון העברות לקרדיט` (5 rows, -948.53/-204.91/-2650.19/-5212.89/-1183.48,
  amex)** — per the prompt's known fact, this is AMEX installment-billing
  clearing language (bank settling card installments), not a household-to-
  household transfer. These represent real card spend already reflected
  elsewhere in the ledger's amex purchase rows — but that's a **card-bill
  double-count question**, not an internal-transfer question, and is out of
  scope for this analysis (would need `is_card_bill_payment` review, which
  currently only fires on `BANK_ORIGINS`, not `amex` origin itself).
- **`מענק בנק לאומי` (+8.25, +323.26)** — small bank grants/bonuses, real
  (tiny) income.
- **`זיכוי מייד699` +1,600, `מפייבוקס שלי-י` +1,000 ×2** — Bit/PayBox
  inbound settlements; treated as real income absent evidence they're a
  self-transfer (no own-account marker, no own-name marker).

### AMBIGUOUUS

- **`PAYBOX` -1,000 (×2, amex)** and **`העברה בBIT` -200/-250 (amex)** and
  **`העברה ב BIT בנה"פ` -150 (cal)** — these are peer-to-peer app transfers
  with no counterparty name in the description at all. Could be a genuine
  payment to a friend/vendor, or could be the household moving money to
  itself via Bit/PayBox on a different device/account. **Missing evidence**:
  the counterparty phone number or name that Bit/PayBox normally attaches
  isn't present in this description field — would need the raw amex/cal dump
  to check for a fuller description string, or the RiseUp UI's own labeling.
  Treated as external (not tagged internal) for the ₪21,658, and I have **no
  positive evidence to reclassify them** — but confidence is lower than the
  named-third-party rows above.

## 5. Corrected August figures excluding the confirmed internal row

Current (as currently computed by the same rule `spending_summary` uses,
applied to August only — `internal_transfer`/`card_bill_payment`/`savings`
rows excluded, matches the headline the user quoted):

```
Income:  ₪97,908.33
Spend:   ₪70,952.06
Net:     ₪26,956.27
```

Excluding only the one CONFIDENT INTERNAL row identified in §3
(`בנק לאומי,משכורת`, discount, +22,100.00, 2026-08-10):

```
Income (adjusted):  97,908.33 - 22,100.00 = ₪75,808.33
Spend (unchanged):                          ₪70,952.06
Net (adjusted):      75,808.33 - 70,952.06 = ₪4,856.27
```

**The August net swings from +₪26,956 to +₪4,856** once the double-counted
salary-forwarding leg is removed. The ₪21,658 העברות spend total is untouched
by this fix (that row is in the `משכורת` category, not `העברות`) — it was
never the source of the double-count; the income side was.

Of the ₪21,658 העברות outflow itself, after the CONFIDENT/AMBIGUOUS split
above:
- Real external spend confirmed: rent -6,800, third-party payments (-600,
  -558, -450×2), AMEX installment clearing (-948.53, -204.91, -2650.19,
  -5212.89, -1183.48) = **~₪18,608** solidly real.
- Ambiguous P2P (Bit/PayBox, no counterparty) -1,000×2, -200, -250, -150 =
  **₪2,600** with unresolved counterparty — likely real but not provable from
  this description field alone.
- No further CONFIDENT INTERNAL amount to subtract from the ₪21,658 itself —
  the internal component of August's transfers is entirely on the income side
  (the ₪22,100 salary-forward), not hiding inside the ₪21,658 outflow total.

## 6. Recommended classifier rule (conservative)

**Extend `is_internal_transfer` in `data/digest.py` (~line 73) with a new,
narrowly-scoped check for the payroll self-transfer**, rather than widening
`OWN_ACCOUNT_HINTS` or `OWN_NAMES` (which already correctly catch the
account-number and name cases — that machinery isn't broken).

Proposed addition:

```python
# The salary-forwarding leg: Leumi receives payroll ("העברת משכורת"), then
# forwards most of it to Discount same/next-business-day. The bank descriptions
# name this specific mechanism, not a generic "transfer" or "היקש"/counterparty:
#   Leumi side (outflow):  "העברת משכורת_י"   (note the _י suffix vs. inbound "העברת משכורת")
#   Discount side (inflow): "בנק לאומי,משכורת"  (RiseUp-categorized arrival, names Leumi as counterparty)
# Matching on these EXACT description strings, not on amount or category, so a
# real external payment described merely as "משכורת" from a different employer/
# counterparty is not caught by accident.
SALARY_FORWARD_DESCRIPTIONS = ["העברת משכורת_י", "בנק לאומי,משכורת"]
```

and add `any(p in desc for p in SALARY_FORWARD_DESCRIPTIONS)` to
`is_internal_transfer`'s checks.

**Durable marker assessment: WEAK, not strong.** I looked for an account-number
marker (the ask in the prompt) and **did not find one** — the Discount-side
arrival row (`בנק לאומי,משכורת`) has **no account number in its description at
all** in this ledger (confirmed: raw `data/discount/raw/transactions.json` does
not even contain this transaction — it only exists via RiseUp's aggregation,
so there's no raw Discount field to inspect for an account number). The only
signal is:
1. The counterparty name string "בנק לאומי" combined with category `משכורת` on
   the Discount side, and
2. The `_י` suffix on the Leumi-side outflow description.

Both are **text-pattern matches on RiseUp/bank free-text descriptions**, not
structural account-ID matches — the same class of signal `OWN_TRANSFER_
DESCRIPTIONS` already uses for `"העברה דיגיטל"`, just a second, month-specific
phrase for the same mechanism. I could not find the household's actual Discount
account number appearing anywhere in the transfer descriptions checked (§3
account list: 10-806 = Leumi branch, 11-034 = a third party's branch, 10-816 /
20-433 / 10-998 = other named third parties; none is `0123444499` or `034`,
the real Discount account per `data/discount/raw/userAccountsData.json`).

**False-positive risk (explicit):** wrongly tagging a real external payment as
internal *hides real spending* — worse than leaving a self-transfer visible as
apparent double-income. The two proposed strings are specific enough
(`_י` suffix, exact "בנק לאומי,משכורת" phrase pairing counterparty+category)
that they should not catch a third-party payment. But because they are
**free-text patterns that could change wording in a future RiseUp
categorization pass or bank template change**, this rule needs to be
**re-verified against each new month's dump** rather than trusted blindly —
same caveat that already applies to `OWN_TRANSFER_DESCRIPTIONS`. If a future
month shows this sweep under yet another phrase (as June's "העברה דיגיטל"
already differs from August's "העברת משכורת_י"), the rule will silently miss
it and re-inflate income by the swept amount again — it will NOT catch future
variants automatically. Recommend treating this as a recurring monthly audit
item (check `data/leumi/raw/transactions.json` for any large same-week
Leumi-out / Discount-in pair) rather than assuming one hardcoded phrase list
solves it permanently.
