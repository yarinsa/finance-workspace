"""One category system for the ledger: what an expense is, and how it behaves.

Every expense row carries two independent properties:

    category   what it is — one of CATEGORIES, grouped under a GROUP
               (תחבורה → רכב / דלק / תחבורה ציבורית)
    kind       how it behaves — ``fixed`` (קבוע: same or almost the same amount on a
               schedule: rent, loans, Metro Motor) or ``variable`` (משתנה: needed but
               usage-driven, so estimated: fuel, groceries, electricity)

"What is left" is not a kind: it is income minus fixed minus variable, computed by
the budget, never stamped on a row. Non-expenses (income, card-bill settlements,
transfers between our own accounts, savings deposits) carry no kind.

The sources' labels are inputs here, not the taxonomy: RiseUp's per-transaction
``expense`` label (and CAL/Max's sector), the tracking envelope it was placed in (the household's own budget lines,
e.g. עציצים) and whether that envelope is ``fixed`` all feed :func:`stamp`.

Default category, first match wins:
    1. the RiseUp tracking envelope (a deliberate budget line) — TRACKING_ALIASES
    2. a merchant default (MERCHANTS)
    3. the source's own label (RiseUp's ``expense``, CAL/Max's sector) — SOURCE_ALIASES
       (a label that is neither a category nor aliased passes through unchanged, so
       nothing is lost; the digest reports it)
    4. the merchant's most common category elsewhere in the ledger (a recent card-only
       charge at שומשום בר, before RiseUp has seen it)

Default kind (expenses only), first match wins, with its ``kind_source``:
    1. ``merchant``   the merchant default's kind
    2. ``category``   a USAGE_BASED category (electricity, fuel, food, cash) is always
                      variable: a repeated amount there is a coincidence, not a bill
    3. ``recurring``  the same merchant and amount (±5%) on about the same day of the
                      month in ≥3 months around this one (:func:`stamp_recurring`)
    4. ``one_off``    the merchant has a recurring charge and this is not it (a ₪52k
                      loan payoff next to the ₪311 installment; an app bought on the
                      Apple bill): variable, whatever the category's default
    5. ``riseup``     RiseUp placed it in a ``fixed`` envelope
    6. ``category``   the category's default kind
A row in a non-expense category (הכנסות וחיסכון, e.g. a pension deposit) has no kind.

The ledger database layers the household's edits on top in the ``transactions``
view: a manual override (``manual``) beats a merchant rule (``rule``) beats these
defaults. :func:`stamp` is pure and stdlib-only, so the digest gives the same
answer without a database.
"""
from collections import defaultdict

from finance.merchants import merchant_name

FIXED, VARIABLE = "fixed", "variable"
KINDS = (FIXED, VARIABLE)
KIND_LABELS = {FIXED: "קבוע", VARIABLE: "משתנה"}

# key, name — in display order. `income_savings` holds the non-expense categories.
GROUPS = [
    ("housing", "דיור"),
    ("bills", "חשבונות"),
    ("subscriptions", "מנויים"),
    ("transport", "תחבורה"),
    ("food", "אוכל"),
    ("health", "בריאות וטיפוח"),
    ("insurance", "ביטוח"),
    ("home", "בית"),
    ("shopping", "קניות"),
    ("leisure", "פנאי"),
    ("work", "עבודה ולימודים"),
    ("finance", "פיננסים"),
    ("misc", "שונות"),
    ("income_savings", "הכנסות וחיסכון"),
]

# name, group key, default kind (None: not an expense category)
CATEGORIES = [
    ("שכר דירה", "housing", FIXED),
    ("משכנתא", "housing", FIXED),
    ("ארנונה", "housing", FIXED),
    ("דירה בת ים", "housing", VARIABLE),
    ("חשמל", "bills", VARIABLE),
    ("מים", "bills", VARIABLE),
    ("גז", "bills", VARIABLE),
    ("תקשורת", "bills", FIXED),
    ("תמי 4", "bills", FIXED),
    ("דיגיטל", "subscriptions", FIXED),
    ("RiseUp", "subscriptions", FIXED),
    ("רכב", "transport", VARIABLE),
    ("דלק", "transport", VARIABLE),
    ("תחבורה ציבורית", "transport", VARIABLE),
    ("כלכלה", "food", VARIABLE),
    ("אוכל בחוץ", "food", VARIABLE),
    ("קפה בחוץ", "food", VARIABLE),
    ("אוכל בעבודה", "food", VARIABLE),
    ("אלכוהול", "food", VARIABLE),
    ("בריאות", "health", VARIABLE),
    ("פארמה", "health", VARIABLE),
    ("ספר", "health", VARIABLE),
    ("ספורט", "health", VARIABLE),
    ("wellness", "health", VARIABLE),
    ("ביטוח", "insurance", FIXED),
    ("ביטוח לאומי", "insurance", FIXED),
    ("דברים לבית", "home", VARIABLE),
    ("מוצרי חשמל לבית", "home", VARIABLE),
    ("עציצים", "home", VARIABLE),
    ("גינה", "home", VARIABLE),
    ("קניות", "shopping", VARIABLE),
    ("ביגוד והנעלה", "shopping", VARIABLE),
    ("פנאי", "leisure", VARIABLE),
    ("דייטים", "leisure", VARIABLE),
    ("תיירות", "leisure", VARIABLE),
    ("מתנות", "leisure", VARIABLE),
    ("חדפ מתוכנן", "leisure", VARIABLE),
    ("הוצאות עסק", "work", VARIABLE),
    ("חינוך", "work", VARIABLE),
    ("הלוואה", "finance", FIXED),
    ("עמלות", "finance", FIXED),
    ("מס הכנסה", "finance", VARIABLE),
    ("כללי", "misc", VARIABLE),
    ("מזומן", "misc", VARIABLE),
    ("העברות", "misc", VARIABLE),
    ("משכורת", "income_savings", None),
    ("זיכויים", "income_savings", None),
    ("מילואים", "income_savings", None),
    ("משיכת פקדון", "income_savings", None),
    ("הפקדת מזומן", "income_savings", None),
    ("השקעה וחיסכון", "income_savings", None),
]

# A source's own label (RiseUp's `expense`, CAL/Max's sector) -> category. None = the
# label says how it was paid, not what it is ("תשלומים" = installments), so the
# category comes from elsewhere or stays empty.
SOURCE_ALIASES = {
    # RiseUp
    "תשלומים": None,
    "שיק": None,
    "עמלת דמי כרטיס - בנקים": "עמלות",
    "דמי כרטיס": "עמלות",
    # CAL / Max
    "עסקאות בתשלומים": None,
    "עסקאות רגילות": None,
    "P2P כל היתר": "העברות",
    "טיסות ותיירות": "תיירות",
    "תיירות יוצאת קניות": "תיירות",
    "מזון וצריכה": "כלכלה",
    "מסעדות": "אוכל בחוץ",
    "מסעדות, קפה וברים": "אוכל בחוץ",
    "עיצוב הבית": "דברים לבית",
    "עמלות תעריפון": "עמלות",
    "פנאי, בידור וספורט": "פנאי",
    "רכב ותחבורה": "רכב",
    "תקשורת ומחשבים": "תקשורת",
}

# RiseUp tracking-envelope name -> category. None = too broad to say what it is.
TRACKING_ALIASES = {
    "__saving-hidden-category__": None,
    "תחבורה": None,
    "חופשה ✈️": "תיירות",
}

# (needle, category, kind) — needle is a prefix of the space-normalized description,
# or anywhere in it when it starts with "*". kind None = decided by the usual rules.
MERCHANTS = [
    ("מטרו", "רכב", None),                  # Metro Motor: the motorcycle; its installments recur
    ("איתוראן", "רכב", FIXED),
    ("פז ", "דלק", None),                   # "פז " not "פזגז": that is the gas bill
    ("דור אלון", "דלק", None),
    ("סונול", "דלק", None),
    ("דלק ", "דלק", None),
    ("טן ", "דלק", None),
    ("אלון כביש", "דלק", None),
    ("*ניהול נכסי", "שכר דירה", FIXED),
    ("*שטראוס מים", "תמי 4", FIXED),
    ("גורביץ מרק", "ספר", FIXED),           # the barber, monthly
    ("ליברה", "ביטוח", FIXED),
    ("ישיר-ביטוח", "ביטוח", None),
    ("הפול", "רכב", None),                  # compulsory car insurance (ביטוח חובה)
    ("הפניקס", "ביטוח", FIXED),
    ("קרן הוכשטיין", "הלוואה", FIXED),
    ("בן חיים אד", "הוצאות עסק", FIXED),     # the business's accountant
    ("מחסני חשמל", "מוצרי חשמל לבית", None),
    ("שקם אלקטריק", "מוצרי חשמל לבית", None),
    ("ח.י אלקטרוניקה", "מוצרי חשמל לבית", None),
    ("חיוב לכרטיס ויזה", "מוצרי חשמל לבית", None),
    ("אל על", "תיירות", None),
    ("*ELAL", "תיירות", None),
    ("אושר עד", "כלכלה", None),
    ("נספרסו", "כלכלה", None),
    ("ישראג'ט", "תיירות", None),
    ("קינג אקספרס", "תיירות", None),
    ("WOLT", "אוכל בחוץ", None),
    ("לאקי צ'קן", "אוכל בחוץ", None),
    ("AWS", "דיגיטל", None),
    ("ANTHROPIC", "דיגיטל", None),
    ("CURSOR", "דיגיטל", None),
    ("SUPERHUMAN", "דיגיטל", None),
    ("WWW.PERPLEXITY", "דיגיטל", None),
    ("*דמי כרטיס", "עמלות", None),
    ("*משיכת יתר", "הלוואה", VARIABLE),     # overdraft interest: follows the balance
    ("תשלום מס במקור", "מס הכנסה", None),
    ("משיכת מזומן", "מזומן", None),
    ("הראל פנסיה", "השקעה וחיסכון", None),
]

# Amount follows usage: only a merchant default, a rule or a manual edit makes these fixed.
USAGE_BASED = {"חשמל", "מים", "גז", "דלק", "כלכלה", "אוכל בחוץ", "קפה בחוץ", "אוכל בעבודה",
               "אלכוהול", "מזומן"}

CATEGORY_KIND = {name: kind for name, _, kind in CATEGORIES}
CATEGORY_GROUP = {name: group for name, group, _ in CATEGORIES}
GROUP_NAME = dict(GROUPS)
GROUP_KEY = {name: key for key, name in GROUPS}

# Debt service: loans and the mortgage. Fixed, but repaid, not cut — the budget's
# "הלוואות וחיסכון" block, a bill of kind "loan", the "committed" lever.
DEBT_CATEGORIES = {"הלוואה", "משכנתא"}

# A source label that says the charge is one installment of a purchase (CAL/Max's
# "עסקאות בתשלומים", RiseUp's "תשלומים"): it ends by itself, whatever was bought.
INSTALLMENT_LABELS = {"תשלומים", "עסקאות בתשלומים"}

# How a fixed expense can be cut — the "what can I cut?" review (cashflow.fixed_expenses).
# key, label, ease, what to do about it — in review order: cheapest wins first,
# committed debt last.
LEVERS = [
    ("fees", "עמלות", "trivial", "לבקש ויתור מהבנק / חברת האשראי"),
    ("subscriptions", "מנויים", "easy", "לבטל מה שלא בשימוש ומה שכפול"),
    ("bills", "חשבונות ושירותים", "moderate", "להשוות ספקים ולמקח מחדש"),
    ("installments", "תשלומים ורכישות", "wait", "מסתיימים מעצמם — לא לפתוח חדשים"),
    ("committed", "דיור והלוואות", "committed", "פירעון מוקדם / מחזור — לא קיצוץ"),
    ("other", "אחר", "moderate", "לבדוק אם עדיין נחוץ"),
]
# group key -> lever key; a category in CATEGORY_LEVER overrides its group. A group
# not listed (food, home, shopping, leisure, work, misc) is "other".
GROUP_LEVER = {
    "housing": "committed", "bills": "bills", "subscriptions": "subscriptions",
    "transport": "bills", "health": "bills", "insurance": "bills", "finance": "committed",
}
CATEGORY_LEVER = {"עמלות": "fees", "ארנונה": "bills", "מס הכנסה": "other"}
_LEVER = {key: (key, label, ease, text) for key, label, ease, text in LEVERS}

RECURRING_WINDOW = 3      # months either side of the row
RECURRING_MIN_MONTHS = 3  # distinct months with the same merchant and amount
RECURRING_TOLERANCE = 0.05
RECURRING_DAY_SPREAD = 5  # days of month either side (a subscription bills on its day)


def is_expense(rec):
    """Money out that is spending: not income, a card-bill settlement, a transfer
    between our own accounts or a savings deposit."""
    return (float(rec.get("amount") or 0) < 0 and not rec.get("is_income")
            and not (rec.get("card_bill_payment") or rec.get("internal_transfer") or rec.get("savings")))


def _norm(s):
    return " ".join((s or "").split())


def merchant_default(description):
    """(category, kind) of the first MERCHANTS needle matching, else (None, None)."""
    d = _norm(description)
    for needle, category, kind in MERCHANTS:
        if (d.find(needle[1:]) >= 0) if needle.startswith("*") else d.startswith(needle):
            return category, kind
    return None, None


def _alias(table, label):
    label = (label or "").strip()
    if not label:
        return None
    return table.get(label, label)


def default_category(rec):
    """The category before any human edit (see the module docstring for the order)."""
    tracking = _alias(TRACKING_ALIASES, rec.get("budget_category"))
    if tracking:
        return tracking
    category, _ = merchant_default(rec.get("description"))
    return category or _alias(SOURCE_ALIASES, rec.get("source_category"))


def label_category(description=None, source_label=None):
    """Category of something outside the ledger — a RiseUp fixed envelope's payee
    and ``expense`` label, a forecast line: merchant default > source label."""
    category, _ = merchant_default(description)
    return category or _alias(SOURCE_ALIASES, source_label)


def tracking_category(name):
    """A RiseUp tracking envelope's name as a category, or as a group name when the
    envelope is a whole group (תחבורה); None for a hidden/empty envelope."""
    name = (name or "").strip()
    if not name or name.startswith("__"):
        return None
    return _alias(TRACKING_ALIASES, name) or (name if name in GROUP_KEY else None)


def ledger_categories(ledger):
    """{merchant: category} from each merchant's latest categorised ledger row — the
    category after the household's edits, for labels that are not ledger rows."""
    out, seen = {}, {}
    for t in ledger:
        m, c, d = t.get("merchant") or merchant_name(t.get("description")), t.get("category"), t.get("date") or ""
        if c and d >= seen.get(m, ""):
            out[m], seen[m] = c, d
    return out


def group_of(category):
    """The group name of a category (רכב -> תחבורה), or None."""
    group = CATEGORY_GROUP.get(category)
    return GROUP_NAME[group] if group else None


def lever(category, source_category=None):
    """(key, label, ease, lever) of the LEVERS entry for a fixed expense: an
    installment of a purchase (by its source label, in a category that is not a
    standing bill — Metro Motor, an appliance; not the ליברה premium) waits it out,
    else category > group > other."""
    if source_category in INSTALLMENT_LABELS and CATEGORY_KIND.get(category, VARIABLE) == VARIABLE:
        return _LEVER["installments"]
    key = CATEGORY_LEVER.get(category) or GROUP_LEVER.get(CATEGORY_GROUP.get(category), "other")
    return _LEVER[key]


def bill_kind(category):
    """The bills screen's pill: ``loan`` (debt service), ``subscription`` (group
    מנויים) or a plain ``bill``."""
    if category in DEBT_CATEGORIES:
        return "loan"
    if CATEGORY_GROUP.get(category) == "subscriptions":
        return "subscription"
    return "bill"


def default_kind(rec, category):
    """(kind, kind_source) before any human edit; (None, None) for a non-expense."""
    if not is_expense(rec):
        return None, None
    _, kind = merchant_default(rec.get("description"))
    if kind:
        return kind, "merchant"
    if category in CATEGORY_GROUP and CATEGORY_KIND[category] is None:
        return None, None
    if category in USAGE_BASED:
        return VARIABLE, "category"
    if rec.get("recurring"):
        return FIXED, "recurring"
    if rec.get("one_off"):
        return VARIABLE, "one_off"
    if rec.get("budget_type") == "fixed":
        return FIXED, "riseup"
    return CATEGORY_KIND.get(category) or VARIABLE, "category"


def _month(rec):
    y, m = rec["date"][:7].split("-")
    return int(y) * 12 + int(m) - 1


def _day_gap(a, b):
    """Days between two days of the month, wrapping (the 30th and the 2nd are 3 apart)."""
    d = abs(a - b)
    return min(d, 30 - d)


def stamp_recurring(ledger):
    """Set ``recurring`` on expense rows whose merchant charged about the same amount
    (±5%, at least ₪2) on about the same day of the month (±5) in ≥3 distinct months
    within 3 months either side, no more than about once a month. The day keeps a
    frequent merchant's coincidental repeat (a ₪29 Wolt order) from looking scheduled.
    Every other charge of a merchant that does recur is marked ``one_off``."""
    by_merchant = defaultdict(list)
    for t in ledger:
        if is_expense(t) and len(t.get("date") or "") >= 10:
            by_merchant[merchant_name(t.get("description"))].append(
                (_month(t), int(t["date"][8:10]), abs(float(t["amount"])), t))
    for rows in by_merchant.values():
        for month, day, amount, t in rows:
            tol = max(amount * RECURRING_TOLERANCE, 2)
            same = [(m, d) for m, d, a, _ in rows
                    if abs(m - month) <= RECURRING_WINDOW and abs(a - amount) <= tol]
            on_day = {m for m, d in same if _day_gap(d, day) <= RECURRING_DAY_SPREAD}
            # about once a month: same-amount charges on any day, not just this one
            if len(on_day) >= RECURRING_MIN_MONTHS and len(same) <= len({m for m, _ in same}) + 1:
                t["recurring"] = True
            else:
                t.pop("recurring", None)
        recurs = any(t.get("recurring") for *_, t in rows)
        for *_, t in rows:
            if recurs and not t.get("recurring"):
                t["one_off"] = True
            else:
                t.pop("one_off", None)


def stamp(ledger):
    """Stamp every ledger row with ``merchant``, ``source_category`` (RiseUp's raw
    label), ``category``, ``category_group``, ``kind`` and ``kind_source``, in place.

    Idempotent: re-stamping a stamped row gives the same answer (the raw label is
    kept in ``source_category``). Returns the set of category names that are not in
    CATEGORIES (source labels nobody mapped yet), for the digest to report."""
    stamp_recurring(ledger)
    for t in ledger:
        if "source_category" not in t:
            t["source_category"] = t.get("category")
        t["merchant"] = merchant_name(t.get("description"))
    own = [default_category(t) for t in ledger]
    seen = defaultdict(lambda: defaultdict(int))
    for t, category in zip(ledger, own):
        if category:
            seen[t["merchant"]][category] += 1
    usual = {m: min(c, key=lambda n: (-c[n], n)) for m, c in seen.items()}
    unknown = set()
    for t, category in zip(ledger, own):
        category = category or usual.get(t["merchant"])
        t["category"] = category
        group = CATEGORY_GROUP.get(category)
        t["category_group"] = GROUP_NAME[group] if group else None
        if category and category not in CATEGORY_GROUP:
            unknown.add(category)
        t["kind"], t["kind_source"] = default_kind(t, category)
        for k in ("source_category", "category", "category_group", "kind", "kind_source"):
            if t[k] is None:
                del t[k]
    return unknown
