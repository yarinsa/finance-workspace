"""Web Push sender and payload builders (finance/push.py): no network, no Postgres."""
import json
import pytest

from finance import push


class Resp:
    def __init__(self, code):
        self.status_code = code


class Gone(Exception):
    def __init__(self, code):
        self.response = Resp(code)


class FakeConn:
    """Records SQL; `rows` is what the SELECT of subscriptions returns."""
    def __init__(self, rows):
        self.rows, self.sql, self.commits = rows, [], 0

    def execute(self, sql, params=None):
        self.sql.append((sql.split()[0], params))
        return self

    def fetchall(self):
        return self.rows

    def commit(self):
        self.commits += 1


ENV = {"PUSH_VAPID_PRIVATE_KEY": "k", "PUSH_VAPID_SUBJECT": "mailto:me@example.com"}.get
PAYLOAD = {"title": "t", "body": "b", "url": "/syncs", "tag": "x"}


def test_sends_to_every_subscription_and_stamps_success():
    conn, sent = FakeConn([(1, "https://p/1", "pk", "au"), (2, "https://p/2", "pk", "au")]), []
    res = push.send(PAYLOAD, conn=conn, sender=lambda sub, data, key, claims: sent.append((sub["endpoint"], json.loads(data), claims)), env=ENV)
    assert res["sent"] == 2 and res["error"] is None
    assert sent[0] == ("https://p/1", PAYLOAD, {"sub": "mailto:me@example.com"})
    assert [s for s in conn.sql if s[0] == "UPDATE"] == [("UPDATE", (1,)), ("UPDATE", (2,))]


@pytest.mark.parametrize("code", [404, 410])
def test_gone_endpoint_is_deleted_and_others_still_get_it(code):
    conn = FakeConn([(1, "https://p/1", "pk", "au"), (2, "https://p/2", "pk", "au")])

    def sender(sub, data, key, claims):
        if sub["endpoint"].endswith("/1"):
            raise Gone(code)
    res = push.send(PAYLOAD, conn=conn, sender=sender, env=ENV)
    assert res["removed"] == 1 and res["sent"] == 1
    assert ("DELETE", (1,)) in conn.sql


def test_other_failures_keep_the_subscription_and_never_raise():
    conn = FakeConn([(1, "https://p/1", "pk", "au")])

    def sender(*a):
        raise Gone(500)
    res = push.send(PAYLOAD, conn=conn, sender=sender, env=ENV)
    assert res["sent"] == 0 and res["removed"] == 0 and res["error"]
    assert not [s for s in conn.sql if s[0] == "DELETE"]


def test_missing_keys_or_broken_db_do_not_raise():
    assert push.send(PAYLOAD, conn=FakeConn([]), env={}.get)["error"]

    class Broken:
        def execute(self, *a):
            raise RuntimeError("db down")
    assert push.send(PAYLOAD, conn=Broken(), env=ENV)["error"] == "db down"


def note(id_, title="חריגה מהמסגרת", category="PROBLEM"):
    return {"id": id_, "title": title, "detail": "d", "category": category}


class FakeInbox:
    """Stands in for db/inbox.py: `rows` are the notifications, `pushed` the ids marked."""
    def __init__(self, rows):
        self.rows, self.pushed = rows, []

    def unpushed(self, conn, categories, now=None):
        return [r for r in self.rows if r["category"] in categories and r["id"] not in self.pushed]

    def mark_pushed(self, conn, ids, now=None):
        self.pushed += [i for i in ids if any(r["id"] == i for r in self.rows)]
        return len(ids)


def flow(monkeypatch, rows, subscribers=1):
    fake = FakeInbox(rows)
    monkeypatch.setattr(push, "_inbox", lambda: fake)
    got = []
    kw = dict(conn=FakeConn([(i, f"https://p/{i}", "pk", "au") for i in range(subscribers)]), env=ENV,
              sender=lambda sub, data, key, claims: got.append(json.loads(data)))
    return fake, got, kw


def test_one_push_per_item_opening_its_inbox_tab():
    out = push.action_payloads([note("limit-breach:2026-11-03"), note("bill-overdue:מי אביבים:2026-10", category="WARNING")])
    assert [(p["url"], p["tag"]) for p in out] == [
        ("/inbox?tab=problems", "notification-limit-breach:2026-11-03"),
        ("/inbox?tab=warnings", "notification-bill-overdue:מי אביבים:2026-10")]


def test_more_than_three_items_are_grouped_into_the_inbox():
    out = push.action_payloads([note(f"a{i}") for i in range(4)])
    assert len(out) == 1 and out[0]["title"] == "4 פריטים חדשים לטיפול" and out[0]["url"] == "/inbox"


def test_only_unpushed_problems_and_warnings_are_announced(monkeypatch):
    rows = [note("a"), note("b", category="WARNING"), note("stale:cal", "נתונים לא עדכניים", "REMINDER"),
            note("tip", category="SUGGESTION"), note("fyi", category="INFO")]
    fake, got, kw = flow(monkeypatch, rows)
    assert push.push_new_actions(sent_file=None, **kw) == "2 new, 2 delivered"
    assert [g["tag"] for g in got] == ["notification-a", "notification-b"]
    assert fake.pushed == ["a", "b"]
    got.clear()
    assert push.push_new_actions(sent_file=None, **{**kw, "conn": FakeConn([(1, "https://p/1", "pk", "au")])}) == "no new items"
    assert got == []


def test_items_stay_unpushed_when_nobody_is_subscribed(monkeypatch):
    fake, got, kw = flow(monkeypatch, [note("a")], subscribers=0)
    push.push_new_actions(sent_file=None, **kw)
    assert fake.pushed == []


def test_legacy_sent_file_marks_existing_ids_then_is_renamed(monkeypatch, tmp_path):
    sent = tmp_path / "sent.json"
    sent.write_text(json.dumps({"ids": {"a": "2026-10-20T00:00:00+00:00", "gone": "2026-10-20T00:00:00+00:00"}}))
    fake, got, kw = flow(monkeypatch, [note("a"), note("b")])
    push.push_new_actions(sent_file=sent, **kw)
    assert [g["tag"] for g in got] == ["notification-b"]     # "a" was announced before the deploy
    assert fake.pushed == ["a", "b"]
    assert not sent.exists() and (tmp_path / "sent.json.migrated").exists()


def test_missing_database_returns_an_error_status(monkeypatch):
    monkeypatch.setattr(push, "_inbox", lambda: FakeInbox([]))
    assert push.push_new_actions(sent_file=None, env={}.get).startswith("error:")


def test_summary_mentions_and_marks_reminders_and_suggestions(monkeypatch, tmp_path):
    cf, tx = tmp_path / "cashflow.json", tmp_path / "transactions.json"
    cf.write_text(json.dumps({"runway": {"start_balance": 4200.4, "safe_to_spend": 300}}))
    tx.write_text(json.dumps({"transactions": []}))
    fake, got, kw = flow(monkeypatch, [note("stale:cal", "נתונים לא עדכניים", "REMINDER"),
                                       note("tip", category="SUGGESTION"), note("a")])
    push.push_daily_summary(cashflow=cf, transactions=tx, today="2026-10-26", **kw)
    assert got[0]["body"].endswith("· 2 הצעות ותזכורות חדשות באינבוקס")
    assert fake.pushed == ["stale:cal", "tip"]      # the PROBLEM waits for push_new_actions


def test_summary_without_inbox_items_is_unchanged():
    assert "אינבוקס" not in push.summary_payload({"start_balance": 100}, 5)["body"]
    assert push.summary_payload(None, 5, 1)["body"] == "הוצאות היום ₪5 · הצעה או תזכורת חדשה באינבוקס"


def test_summary_counts_only_real_spending_today():
    ledger = [
        {"date": "2026-10-26", "amount": -120.0, "description": "סופר"},
        {"date": "2026-10-26", "amount": -500.0, "description": "כאל", "card_bill_payment": True},
        {"date": "2026-10-26", "amount": 900.0, "description": "משכורת", "is_income": True},
        {"date": "2026-10-25", "amount": -50.0, "description": "אתמול"},
    ]
    assert push.spent_on("2026-10-26", ledger) == 120.0
    p = push.summary_payload({"start_balance": 4200.4, "safe_to_spend": -300}, 120.0)
    assert p["body"] == "יתרה ₪4,200 · הוצאות היום ₪120 · פנוי להוצאה -₪300" and p["url"] == "/overview"


def test_only_the_evening_run_sends_the_summary():
    assert push.is_evening_run("2026-10-26T19:00:00+00:00")       # 22:00 Jerusalem (UTC+3)
    assert not push.is_evening_run("2026-10-26T03:20:00+00:00")   # 06:20


def test_generated_keys_work_with_py_vapid():
    import importlib.util
    import sys
    from pathlib import Path
    from py_vapid import Vapid
    spec = importlib.util.spec_from_file_location("push_keys", Path(push.REPO) / "sync" / "push_keys.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    private, public = mod.generate()
    v = Vapid.from_string(private)
    assert len(public) == 87 and v.public_key is not None
