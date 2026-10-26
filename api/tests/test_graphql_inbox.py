"""The notifications inbox over GraphQL: reads, the household's read / snooze / archive state, bulk edits.

Notifications are the digest's "לטיפול" actions (db/inbox.py `sync`); the ids below are real
period-stable ones. The API pool runs as `finance_api`, so every write here also proves the
role's column grants. Inbox writes are not ledger edits: none of them may signal a rebuild.
"""
import datetime as dt

import pytest

import inbox
from api.gql.relay import to_global_id
from api.tests.test_graphql import data, gql

UTC = dt.timezone.utc
NOW = dt.datetime.now(UTC)

LIMIT = {"id": "limit-breach:2026-11-11", "severity": "critical", "category": "PROBLEM", "type": "limitBreach",
         "title": "חריגה מהמסגרת ב-11/11", "detail": "היתרה תרד למינוס ₪11,695", "amount": 1694.74,
         "cta": {"label": "לתוכנית התזרים", "to": "/monthly?view=forecast"},
         "subject": {"kind": "cashflow", "date": "2026-11-11"}}
BUDGET = {"id": "budget-over:פנאי:2026-10", "severity": "high", "category": "WARNING", "type": "budgetOver",
          "title": "חריגה בתקציב פנאי", "detail": "₪1,763 מתוך ₪1,200 (+₪563)", "amount": 563.0,
          "cta": {"label": "לתקציב", "to": "/budgets"},
          "subject": {"kind": "budget", "categories": ["פנאי"], "cycle_start": "2026-10-01"}}
WATER = {"id": "bill-overdue:מי אביבים חיוב תקופת:2026-10", "severity": "medium", "category": "WARNING",
         "type": "billOverdue", "title": "לא נמצא תשלום למי אביבים", "detail": "₪267 · היה צפוי ב-11/10",
         "amount": 266.7, "cta": None,
         "subject": {"kind": "bill", "name": "מי אביבים חיוב תקופת", "due_date": "2026-10-11"}}
APPLE = {"id": "dup:APPLE.COM/BILL CORK IRL:2026-10", "severity": "low", "category": "SUGGESTION",
         "type": "duplicateService", "title": "שירות כפול: APPLE.COM/BILL CORK IRL", "detail": None, "amount": 109.4,
         "cta": {"label": "לבדיקה", "to": "/monthly"},
         "subject": {"kind": "service", "services": ["APPLE.COM/BILL CORK IRL"] * 2}}
STALE = {"id": "stale:discount-business", "severity": "low", "category": "REMINDER", "type": "staleData",
         "title": "נתונים לא עדכניים", "detail": None, "amount": None, "cta": None,
         "subject": {"kind": "sync", "sources": ["discount-business"]}}
VALIDATION = {"id": "validation:salary:2026-10", "severity": "critical", "category": "PROBLEM",
              "type": "validationFailed", "title": "המשכורת לא הגיעה", "detail": None, "amount": None, "cta": None,
              "subject": None}
REFUND = {"id": "offset:2026-01-20:23.45", "severity": "low", "category": "SUGGESTION", "type": "offsetSuggestion",
          "title": "החזר חנות לדוגמה", "detail": None, "amount": 23.45, "cta": None,
          "subject": {"kind": "transaction", "date": "2026-01-15", "abs_amount": "123.45"}}
ALL = [LIMIT, BUDGET, WATER, APPLE, STALE, VALIDATION]


def gid(action):
    return to_global_id("Notification", action["id"])


@pytest.fixture
def inbox_rows(owner):
    inbox.sync(owner, [*ALL, REFUND], now=NOW - dt.timedelta(hours=1))
    owner.commit()


LIST = """query($filter: NotificationFilter, $first: Int, $after: String) {
  notifications(first: $first, after: $after, filter: $filter) {
    totalCount pageInfo { hasNextPage endCursor }
    edges { cursor node { __typename id type category severity title readAt } } } }"""
UPDATE = """mutation($id: ID!, $read: Boolean, $snooze: DateTime) {
  updateNotification(input: {id: $id, read: $read, snoozedUntilAt: $snooze, clientMutationId: "m1"}) {
    clientMutationId notification { id readAt snoozedUntilAt archivedAt } } }"""


def titles(conn):
    return [e["node"]["title"] for e in conn["edges"]]


def test_most_severe_first_then_newest_with_typed_subtypes(client, inbox_rows):
    conn = data(client, LIST)["notifications"]
    assert conn["totalCount"] == 7
    assert [(e["node"]["__typename"], e["node"]["severity"]) for e in conn["edges"][:2]] == \
        [("CashflowNotification", "CRITICAL"), ("GenericNotification", "CRITICAL")]
    assert [e["node"]["category"] for e in conn["edges"][2:4]] == ["WARNING", "WARNING"]
    assert {e["node"]["__typename"] for e in conn["edges"]} == {
        "CashflowNotification", "GenericNotification", "BudgetNotification", "BillNotification",
        "ServiceNotification", "SyncNotification", "TransactionNotification"}
    first = conn["edges"][0]["node"]
    assert first["type"] == "limitBreach" and first["readAt"] is None


def test_filter_by_category_and_unread_count(client, inbox_rows):
    d = data(client, LIST, filter={"category": ["WARNING", "REMINDER"]})["notifications"]
    assert titles(d) == [BUDGET["title"], WATER["title"], STALE["title"]]
    count = "query($c: [NotificationCategory!]) { notificationsUnreadCount(category: $c) }"
    assert data(client, count)["notificationsUnreadCount"] == 7
    assert data(client, count, c=["PROBLEM"])["notificationsUnreadCount"] == 2
    assert data(client, count, c=["INFO"])["notificationsUnreadCount"] == 0


def test_cursor_paging_is_stable(client, inbox_rows):
    one = data(client, LIST, first=3)["notifications"]
    rest = data(client, LIST, first=10, after=one["pageInfo"]["endCursor"])["notifications"]
    assert one["pageInfo"]["hasNextPage"] and not rest["pageInfo"]["hasNextPage"]
    assert len(one["edges"]) + len(rest["edges"]) == 7
    assert not set(titles(one)) & set(titles(rest))


def test_read_roundtrip_and_unread_count(client, inbox_rows, rebuilder):
    d = data(client, UPDATE, id=gid(STALE), read=True)["updateNotification"]
    assert d["clientMutationId"] == "m1" and d["notification"]["readAt"] is not None
    assert data(client, LIST, filter={"unread": True})["notifications"]["totalCount"] == 6
    assert data(client, LIST, filter={"unread": False})["notifications"]["totalCount"] == 1
    d = data(client, UPDATE, id=gid(STALE), read=False)["updateNotification"]
    assert d["notification"]["readAt"] is None
    assert rebuilder.signals == 0   # not ledger data


def test_snoozing_hides_until_it_lapses_and_marks_unread(client, inbox_rows):
    data(client, UPDATE, id=gid(STALE), read=True)
    until = (NOW + dt.timedelta(days=1)).isoformat()
    d = data(client, UPDATE, id=gid(STALE), snooze=until)["updateNotification"]["notification"]
    assert d["readAt"] is None and d["snoozedUntilAt"] is not None
    assert STALE["title"] not in titles(data(client, LIST)["notifications"])
    assert STALE["title"] in titles(data(client, LIST, filter={"includeSnoozed": True})["notifications"])
    # a null clears the snooze
    data(client, "mutation($id: ID!) { updateNotification(input: {id: $id, snoozedUntilAt: null}) "
                 "{ notification { id } } }", id=gid(STALE))
    assert STALE["title"] in titles(data(client, LIST)["notifications"])


def test_archive_and_unarchive(client, inbox_rows, rebuilder):
    arch = """mutation($id: ID!) { archiveNotification(input: {id: $id}) { notification { archivedAt } } }"""
    un = """mutation($id: ID!) { unarchiveNotification(input: {id: $id}) { notification { archivedAt } } }"""
    assert data(client, arch, id=gid(WATER))["archiveNotification"]["notification"]["archivedAt"] is not None
    assert WATER["title"] not in titles(data(client, LIST)["notifications"])
    assert WATER["title"] in titles(data(client, LIST, filter={"includeArchived": True})["notifications"])
    assert data(client, un, id=gid(WATER))["unarchiveNotification"]["notification"]["archivedAt"] is None
    assert data(client, LIST)["notifications"]["totalCount"] == 7
    assert rebuilder.signals == 0


def test_resolved_items_are_hidden_unless_asked_for(client, owner, inbox_rows):
    inbox.sync(owner, [LIMIT])   # everything else went away
    owner.commit()
    assert titles(data(client, LIST)["notifications"]) == [LIMIT["title"]]
    d = data(client, LIST, filter={"includeResolved": True})["notifications"]
    assert d["totalCount"] == 7


def test_bulk_mark_read_archive_and_snooze_only_touch_visible_items(client, inbox_rows, rebuilder):
    read = """mutation($c: [NotificationCategory!]) { markAllNotificationsRead(input: {category: $c, clientMutationId: "b"})
      { clientMutationId count } }"""
    assert data(client, read, c=["WARNING"])["markAllNotificationsRead"] == {"clientMutationId": "b", "count": 2}
    assert data(client, read)["markAllNotificationsRead"]["count"] == 5   # the other five are still unread
    snooze = """mutation($t: DateTime!, $c: [NotificationCategory!]) {
      snoozeAllNotifications(input: {snoozedUntilAt: $t, category: $c}) { count } }"""
    until = (NOW + dt.timedelta(hours=3)).isoformat()
    assert data(client, snooze, t=until, c=["SUGGESTION"])["snoozeAllNotifications"]["count"] == 2
    assert data(client, LIST)["notifications"]["totalCount"] == 5
    archive = "mutation { archiveAllNotifications(input: {}) { count } }"
    assert data(client, archive)["archiveAllNotifications"]["count"] == 5
    assert data(client, LIST)["notifications"]["totalCount"] == 0
    count = "{ notificationsUnreadCount }"
    assert data(client, count)["notificationsUnreadCount"] == 0
    assert rebuilder.signals == 0


def test_node_refetches_any_subtype_and_fragments_select_subject_fields(client, inbox_rows):
    q = """query($id: ID!) { node(id: $id) { id ... on Notification { title }
      ... on BudgetNotification { budgetCategories cycleStart }
      ... on CashflowNotification { date }
      ... on BillNotification { billName dueDate }
      ... on ServiceNotification { services }
      ... on SyncNotification { sources } } }"""
    assert data(client, q, id=gid(BUDGET))["node"] == {
        "id": gid(BUDGET), "title": BUDGET["title"], "budgetCategories": ["פנאי"], "cycleStart": "2026-10-01"}
    assert data(client, q, id=gid(LIMIT))["node"]["date"] == "2026-11-11"
    assert data(client, q, id=gid(WATER))["node"]["billName"] == "מי אביבים חיוב תקופת"
    assert data(client, q, id=gid(WATER))["node"]["dueDate"] == "2026-10-11"
    assert data(client, q, id=gid(APPLE))["node"]["services"] == ["APPLE.COM/BILL CORK IRL"] * 2
    assert data(client, q, id=gid(STALE))["node"]["sources"] == ["discount-business"]
    assert data(client, q, id=to_global_id("Notification", "nope"))["node"] is None


def test_fields_amount_cta_and_timestamps(client, inbox_rows):
    q = """query($id: ID!) { node(id: $id) { ... on Notification { amount detail cta { label to }
                                             createdAt updatedAt resolvedAt } } }"""
    n = data(client, q, id=gid(LIMIT))["node"]
    assert n["amount"] == "1694.74" and n["cta"] == {"label": "לתוכנית התזרים", "to": "/monthly?view=forecast"}
    assert n["createdAt"] and n["updatedAt"] and n["resolvedAt"] is None
    n = data(client, q, id=gid(STALE))["node"]
    assert n["amount"] is None and n["cta"] is None and n["detail"] is None


def test_a_transaction_notification_points_at_its_ledger_row(client, inbox_rows):
    q = """query($id: ID!) { node(id: $id) { ... on TransactionNotification { transaction { date amount } } } }"""
    assert data(client, q, id=gid(REFUND))["node"]["transaction"] == {"date": "2026-01-15", "amount": "-123.45"}


def test_a_ledger_edit_still_signals_a_rebuild(client, inbox_rows, rebuilder):
    # the flag is per resolver: only the inbox opts out
    from api.tests.test_graphql import PURCHASE_ID
    data(client, 'mutation($id: ID!) { updateTransaction(input: {id: $id, note: "x"}) { transaction { note } } }',
         id=PURCHASE_ID)
    assert rebuilder.signals == 1


def test_bad_input_is_a_graphql_error(client, inbox_rows):
    status, body = gql(client, UPDATE, id=gid(STALE))
    assert "send read and/or snoozedUntilAt" in body["errors"][0]["message"]
    status, body = gql(client, UPDATE, id=to_global_id("Notification", "nope"), read=True)
    assert "no such notification" in body["errors"][0]["message"]
    status, body = gql(client, UPDATE, id=to_global_id("Tag", "1"), read=True)
    assert "id is not a Notification" in body["errors"][0]["message"]
    status, body = gql(client, UPDATE, id=gid(STALE), snooze="tomorrow")
    assert "not an ISO 8601 timestamp" in body["errors"][0]["message"]
