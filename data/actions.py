"""The "לטיפול" (to-handle) list for the home page.

Pure function over the already-built cashflow blocks (runway, bills, budgets,
fixed_expenses) and the snapshot's sync list; reads and writes nothing. Each
action carries an id that is stable for its period (cycle / month / date) so a
per-device dismiss sticks until the situation changes.

Action shape: {id, severity, title, detail, cta: {label, to} | null, amount}.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import freshness

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
MIN_BUDGET_PLAN = 50      # skip RiseUp's ₪1 placeholder envelopes
MAX_BUDGET_ITEMS = 3
CARD_WINDOW_DAYS = 14


def shekel(x):
    """₪5,969 — no decimals, absolute value."""
    return f"₪{abs(round(float(x or 0))):,.0f}"


def _dm(iso):
    d = date.fromisoformat(str(iso)[:10])
    return f"{d.day}/{d.month}"


def _action(id_, severity, title, detail, cta=None, amount=None):
    return {
        "id": id_, "severity": severity, "title": title, "detail": detail,
        "cta": {"label": cta[0], "to": cta[1]} if cta else None,
        "amount": round(float(amount), 2) if amount is not None else None,
    }


def _runway_actions(runway):
    out = []
    if not runway:
        return out
    breach = runway.get("first_limit_breach")
    if breach:
        low = min((d["balance"] for d in runway.get("days", []) if d["date"] >= breach),
                  default=None)
        if low is None:
            low = (runway.get("low_point") or {}).get("balance", 0)
        detail = f"היתרה תרד למינוס {shekel(low)} — מעבר למסגרת {shekel(runway.get('overdraft_limit'))}"
        buffer = [b for b in runway.get("liquid_buffer") or [] if (b.get("balance") or 0) > 0]
        total = sum(b["balance"] for b in buffer)
        if total > 0:
            detail += f" · אפשר להעביר {shekel(total)} מ{buffer[0]['label']}"
        overshoot = abs(low) - (runway.get("overdraft_limit") or 0)
        out.append(_action(f"limit-breach:{breach}", "critical", f"חריגה מהמסגרת ב-{_dm(breach)}",
                           detail, ("לתוכנית התזרים", "/runway"), max(overshoot, 0)))
    safe = runway.get("safe_to_spend")
    if safe is not None and safe < 0:
        payday = (runway.get("next_payday") or {}).get("date") or runway.get("as_of", "")
        out.append(_action(f"short-until-payday:{payday}", "high",
                           f"חסרים {shekel(safe)} עד המשכורת",
                           "הוצאות קבועות צפויות לעבור את היתרה לפני המשכורת הבאה",
                           ("לתוכנית התזרים", "/runway"), abs(safe)))
    return out


def _budget_actions(budgets):
    if not budgets:
        return []
    month = str(budgets.get("cycle_start", ""))[:7]
    over = [c for c in budgets.get("categories", [])
            if c.get("over") and (c.get("planned") or 0) >= MIN_BUDGET_PLAN]
    over.sort(key=lambda c: c["spent"] - c["planned"], reverse=True)
    out = []
    for c in over[:MAX_BUDGET_ITEMS]:
        extra = c["spent"] - c["planned"]
        out.append(_action(f"budget-over:{c['name']}:{month}", "high", f"חריגה בתקציב {c['name']}",
                           f"{shekel(c['spent'])} מתוך {shekel(c['planned'])} (+{shekel(extra)})",
                           ("לתקציב", "/budgets"), extra))
    rest = over[MAX_BUDGET_ITEMS:]
    if rest:
        extra = sum(c["spent"] - c["planned"] for c in rest)
        out.append(_action(f"budget-over-more:{month}", "medium", ("עוד קטגוריה בחריגה" if len(rest) == 1 else f"עוד {len(rest)} קטגוריות בחריגה"),
                           ", ".join(c["name"] for c in rest) + f" · +{shekel(extra)}",
                           ("לתקציב", "/budgets"), extra))
    return out


def _bill_actions(bills):
    out = []
    for b in (bills or {}).get("items", []):
        if b.get("status") != "overdue":
            continue
        out.append(_action(f"bill-overdue:{b['name']}:{str(b['due_date'])[:7]}", "medium",
                           f"לא נמצא תשלום ל{b['name']}",
                           f"{shekel(b['amount'])} · היה צפוי ב-{_dm(b['due_date'])}",
                           ("לחשבונות", "/monthly"), b["amount"]))
    return out


def _card_actions(runway, as_of):
    end = (as_of + timedelta(days=CARD_WINDOW_DAYS)).isoformat()
    by_date = defaultdict(list)
    for e in (runway or {}).get("events", []):
        if e.get("kind") == "card" and as_of.isoformat() <= e["date"] <= end:
            by_date[e["date"]].append(e)
    out = []
    for d, evs in by_date.items():
        total = -sum(e["amount"] for e in evs)
        issuers = ", ".join(f"{e['name'].split(',')[0]} {shekel(e['amount'])}" for e in evs)
        out.append(_action(f"card-bills:{d}", "medium", f"חיובי אשראי {shekel(total)} ב-{_dm(d)}",
                           issuers, ("לתוכנית התזרים", "/runway"), total))
    return out


GENERIC_DUP_REASON = "אותו ספק כמה פעמים"


def _duplicate_actions(fixed):
    """One action per duplicated service.

    A named reason (e.g. two international-call plans) groups items across
    merchants; the generic "same vendor several times" reason groups by merchant
    and is skipped when only one row matched (nothing to compare).
    """
    if not fixed:
        return []
    month = fixed.get("month", "")
    groups = defaultdict(list)
    for g in fixed.get("groups", []):
        for it in g.get("items", []):
            if it.get("duplicate"):
                reason = it.get("duplicate_reason")
                key = reason if reason and reason != GENERIC_DUP_REASON else it["name"]
                groups[key].append(it)
    out = []
    for key, items in groups.items():
        if key == items[0]["name"] and len(items) < 2:
            continue
        total = sum(i["amount"] for i in items)
        names = " + ".join(f"{i['name']} {shekel(i['amount'])}" for i in items)
        out.append(_action(f"dup:{key}:{month}", "low", f"שירות כפול: {key}",
                           names if key != items[0]["name"] else
                           f"{GENERIC_DUP_REASON} · " + " + ".join(shekel(i["amount"]) for i in items),
                           ("לבדיקה", "/monthly"), total))
    return out


def _stale_actions(syncs, as_of):
    """One action naming every source past its freshness target plus grace.

    `as_of` may be a date (taken as noon that day) or a datetime. Sources with no
    target (RiseUp) are skipped; the id is the sorted list of overdue sources so
    a dismiss sticks until the set changes.
    """
    now = as_of if isinstance(as_of, datetime) else datetime.combine(as_of, time(12))
    late = []
    for s in syncs or []:
        if s.get("source") not in freshness.TARGETS:
            continue
        try:
            row = freshness.classify(s["source"], s["last_synced"], now)
        except (KeyError, ValueError, TypeError):
            continue
        if row["state"] == "overdue":
            late.append(row)
    if not late:
        return []
    late.sort(key=lambda r: r["source"])
    detail = ", ".join(
        f"{r['source']} ({freshness.fmt_span(r['age'])}, יעד {freshness.fmt_span(r['target'])}, "
        f"באיחור {freshness.fmt_span(freshness.lateness(r))})" for r in late)
    return [_action("stale:" + ",".join(r["source"] for r in late), "low", "נתונים לא עדכניים",
                    detail, ("לסנכרונים", "/syncs"))]


def build_actions(runway, bills, budgets, fixed_expenses, syncs, as_of, validation=()):
    """Prioritised to-handle list: critical -> low, then amount descending.

    `validation` is data/validate.py's `validation_actions()` output, already in
    action shape; it is merged in as-is.
    """
    actions = (_runway_actions(runway) + _budget_actions(budgets) + _bill_actions(bills)
               + _card_actions(runway, as_of) + _duplicate_actions(fixed_expenses)
               + _stale_actions(syncs, as_of) + list(validation))
    actions.sort(key=lambda a: (SEVERITY_ORDER[a["severity"]], -(a["amount"] or 0)))
    return actions
