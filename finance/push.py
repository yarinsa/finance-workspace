"""Web Push from the Mac: send a notification to every installed PWA that subscribed.

The ledger API only stores subscriptions (insert/delete, role finance_api). Sending needs the
VAPID *private* key, which lives only in the Mac's `.env` (PUSH_VAPID_PRIVATE_KEY,
PUSH_VAPID_PUBLIC_KEY, PUSH_VAPID_SUBJECT) and is never given to the API container. This module
connects with the owner DATABASE_URL, stamps `last_success_at` and deletes endpoints the push
service reports gone (404/410).

Everything public here NEVER raises: a push failure must not fail a sync.

A payload is `{"title", "body", "url", "tag"}`; the service worker (app/src/sw.ts) shows it and
opens `url` on tap. The pure builders (`action_payloads`, `summary_payload`, ...) are separate
from the sending so they are testable without a database or network.
"""
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent.parent
SENT_FILE = REPO / "data" / "push" / "sent.json"   # gitignored with the rest of data/
CASHFLOW = REPO / "data" / "digested" / "cashflow.json"
TRANSACTIONS = REPO / "data" / "digested" / "transactions.json"

TZ = ZoneInfo("Asia/Jerusalem")
EVENING_HOUR = 21          # the 22:00 run; a late start still counts
GROUP_ABOVE = 3            # more new actions than this become one grouped push
SENT_KEEP_DAYS = 60
GONE = (404, 410)

log = logging.getLogger("finance_push")


def env_value(name, env_file=REPO / ".env"):
    """`name` from the environment, else from .env (read literally)."""
    value = os.environ.get(name)
    if value:
        return value
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("'\"") or None
    return None


def shekel(x):
    return f"₪{abs(round(float(x or 0))):,.0f}"


# --- sending -----------------------------------------------------------------------------

def _webpush(subscription, data, private_key, claims):
    from pywebpush import webpush
    return webpush(subscription_info=subscription, data=data, vapid_private_key=private_key,
                   vapid_claims=claims, ttl=12 * 3600)


def _status_of(exc):
    return getattr(getattr(exc, "response", None), "status_code", None)


def send(payloads, *, conn=None, sender=None, env=env_value):
    """Push each payload (a dict, or a list of them) to every subscription.

    Returns {"sent": n deliveries, "removed": n dead endpoints, "subscriptions": n, "error": str|None}.
    `conn` (psycopg, owner) and `sender(subscription, data, private_key, claims)` are injectable
    for tests. Never raises."""
    out = {"sent": 0, "removed": 0, "subscriptions": 0, "error": None}
    try:
        payloads = [payloads] if isinstance(payloads, dict) else list(payloads or [])
        if not payloads:
            return out
        private_key, subject = env("PUSH_VAPID_PRIVATE_KEY"), env("PUSH_VAPID_SUBJECT")
        if not private_key or not subject:
            out["error"] = "PUSH_VAPID_PRIVATE_KEY / PUSH_VAPID_SUBJECT not set"
            return out
        own = conn is None
        if own:
            import psycopg
            url = env("DATABASE_URL")
            if not url:
                out["error"] = "DATABASE_URL not set"
                return out
            conn = psycopg.connect(url, connect_timeout=5)
        try:
            rows = conn.execute("SELECT id, endpoint, p256dh, auth FROM push_subscriptions ORDER BY id").fetchall()
            out["subscriptions"] = len(rows)
            for sid, endpoint, p256dh, auth in rows:
                sub = {"endpoint": endpoint, "keys": {"p256dh": p256dh, "auth": auth}}
                alive = True
                for payload in payloads:
                    try:
                        (sender or _webpush)(sub, json.dumps(payload, ensure_ascii=False), private_key,
                                             {"sub": subject})
                        out["sent"] += 1
                        conn.execute("UPDATE push_subscriptions SET last_success_at = now() WHERE id = %s", (sid,))
                    except Exception as e:   # one bad endpoint must not stop the rest
                        if _status_of(e) in GONE:
                            conn.execute("DELETE FROM push_subscriptions WHERE id = %s", (sid,))
                            out["removed"] += 1
                            alive = False
                        else:
                            log.warning("push to subscription %s failed: %s", sid, e)
                            out["error"] = str(e)[:200]
                    if not alive:
                        break
            conn.commit()
        finally:
            if own:
                conn.close()
    except Exception as e:
        log.warning("push failed: %s", e)
        out["error"] = str(e)[:200]
    return out


# --- payload builders --------------------------------------------------------------------

def login_payloads(dead_by_group, label_he):
    """One push per login group. `dead_by_group` is {group: [source, ...]}."""
    return [{"title": "נדרשת התחברות", "body": f"{', '.join(label_he[s] for s in members)} — התחבר כדי להמשיך בסנכרון",
             "url": "/syncs", "tag": f"login-{group}"} for group, members in dead_by_group.items()]


def failure_payload(source, name, status, error=None):
    rejected = status == "rejected"
    body = f"{name}: " + ("הנתונים נדחו בבדיקה" if rejected else "הסנכרון נכשל")
    if error:
        body += f" — {str(error).strip().splitlines()[0][:120]}"
    return {"title": "הנתונים נדחו" if rejected else "הסנכרון נכשל", "body": body,
            "url": "/syncs", "tag": f"sync-{status}-{source}"}


def action_payloads(new_actions):
    """One push per new לטיפול item; a single grouped push when there are more than GROUP_ABOVE."""
    if not new_actions:
        return []
    if len(new_actions) > GROUP_ABOVE:
        return [{"title": f"{len(new_actions)} פריטים חדשים לטיפול",
                 "body": " · ".join(a["title"] for a in new_actions[:3]) + " ועוד",
                 "url": "/overview", "tag": "actions"}]
    return [{"title": a["title"], "body": a.get("detail") or "",
             "url": (a.get("cta") or {}).get("to") or "/overview", "tag": f"action-{a['id']}"}
            for a in new_actions]


def spent_on(day, ledger):
    """₪ of real spending dated `day` (ISO), counted as the cashflow screens do: offsets netted,
    card-bill settlements / transfers / savings / income excluded."""
    import sys
    for p in (REPO / "data", REPO):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import spending
    from finance import offsets
    return round(sum(-float(t["amount"]) for t in offsets.cashflow_view(ledger)
                     if str(t.get("date", ""))[:10] == day and spending.classify(t) == "spend"), 2)


def summary_payload(runway, spent):
    parts = []
    if runway and runway.get("start_balance") is not None:
        bal = float(runway["start_balance"])
        parts.append(f"יתרה {'-' if bal < 0 else ''}{shekel(bal)}")
    parts.append(f"הוצאות היום {shekel(spent)}")
    safe = (runway or {}).get("safe_to_spend")
    if safe is not None:
        parts.append(f"פנוי להוצאה {'-' if safe < 0 else ''}{shekel(safe)}")
    return {"title": "סיכום יומי", "body": " · ".join(parts), "url": "/overview", "tag": "daily-summary"}


def is_evening_run(started_iso):
    """True when the workflow started in the 22:00 slot (Asia/Jerusalem), not the 06:20 one."""
    t = datetime.fromisoformat(started_iso)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(TZ).hour >= EVENING_HOUR


# --- already-pushed ids ------------------------------------------------------------------

def load_sent(path=SENT_FILE):
    try:
        return dict(json.loads(Path(path).read_text()).get("ids", {}))
    except (OSError, ValueError, AttributeError):
        return {}


def save_sent(ids, now, path=SENT_FILE):
    cutoff = (now - timedelta(days=SENT_KEEP_DAYS)).isoformat()
    kept = {k: v for k, v in ids.items() if v >= cutoff}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"ids": kept}, ensure_ascii=False, indent=1))
    tmp.replace(path)


def new_actions(actions, sent):
    return [a for a in actions or [] if a.get("id") and a["id"] not in sent]


def push_new_actions(*, cashflow=CASHFLOW, sent_path=SENT_FILE, now=None, **kw):
    """Push the לטיפול items not pushed before. Ids are marked sent only when at least one
    device got the push, so enabling notifications later still announces what is open.
    Returns a short status string. Never raises."""
    try:
        now = now or datetime.now(timezone.utc)
        actions = json.loads(Path(cashflow).read_text()).get("actions") or []
        sent = load_sent(sent_path)
        fresh = new_actions(actions, sent)
        if not fresh:
            return "no new items"
        res = send(action_payloads(fresh), **kw)
        if res["sent"]:
            stamp = now.isoformat()
            save_sent({**sent, **{a["id"]: stamp for a in fresh}}, now, sent_path)
        return f"{len(fresh)} new, {res['sent']} delivered"
    except Exception as e:
        log.warning("action push failed: %s", e)
        return f"error: {e}"[:200]


def push_daily_summary(*, cashflow=CASHFLOW, transactions=TRANSACTIONS, today=None, **kw):
    """Balance, spent today and safe-to-spend. Never raises."""
    try:
        today = today or datetime.now(TZ).date().isoformat()
        runway = json.loads(Path(cashflow).read_text()).get("runway")
        ledger = json.loads(Path(transactions).read_text()).get("transactions", [])
        res = send(summary_payload(runway, spent_on(today, ledger)), **kw)
        return f"{res['sent']} delivered"
    except Exception as e:
        log.warning("daily summary push failed: %s", e)
        return f"error: {e}"[:200]
