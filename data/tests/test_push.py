"""Web Push sender and payload builders (finance/push.py): no network, no Postgres."""
import json
from datetime import datetime, timezone

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


def action(id_, title="חריגה מהמסגרת", cta=("x", "/monthly?view=forecast")):
    return {"id": id_, "title": title, "detail": "d", "cta": {"label": cta[0], "to": cta[1]} if cta else None}


def test_one_push_per_item_with_link_or_overview():
    out = push.action_payloads([action("limit-breach:2026-11-03"), action("stale:cal", cta=None)])
    assert [(p["url"], p["tag"]) for p in out] == [
        ("/monthly?view=forecast", "action-limit-breach:2026-11-03"), ("/overview", "action-stale:cal")]


def test_more_than_three_items_are_grouped():
    out = push.action_payloads([action(f"a{i}") for i in range(4)])
    assert len(out) == 1 and out[0]["title"] == "4 פריטים חדשים לטיפול" and out[0]["url"] == "/overview"


def test_only_ids_not_pushed_before_are_announced(tmp_path):
    cf, sent = tmp_path / "cashflow.json", tmp_path / "push" / "sent.json"
    cf.write_text(json.dumps({"actions": [action("a"), action("b")]}))
    now = datetime(2026, 10, 26, tzinfo=timezone.utc)
    got = []
    sender = lambda sub, data, key, claims: got.append(json.loads(data)["tag"])  # noqa: E731
    kw = dict(cashflow=cf, sent_path=sent, now=now, conn=FakeConn([(1, "https://p/1", "pk", "au")]), sender=sender, env=ENV)
    push.push_new_actions(**kw)
    assert got == ["action-a", "action-b"]
    cf.write_text(json.dumps({"actions": [action("a"), action("b"), action("c")]}))
    got.clear()
    push.push_new_actions(**{**kw, "conn": FakeConn([(1, "https://p/1", "pk", "au")])})
    assert got == ["action-c"]


def test_items_stay_unsent_when_nobody_is_subscribed(tmp_path):
    cf, sent = tmp_path / "cashflow.json", tmp_path / "sent.json"
    cf.write_text(json.dumps({"actions": [action("a")]}))
    push.push_new_actions(cashflow=cf, sent_path=sent, conn=FakeConn([]), env=ENV)
    assert push.load_sent(sent) == {}


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
