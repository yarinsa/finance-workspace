"""POST /api/graphql, read side, against the throwaway test database.

The ledger is conftest's: PURCHASE (-123.45, cal, קניות), SALARY (+1000, משכורת),
CARD_BILL (-500, חיובי כרטיס). Each test is a question the dashboard asks.
"""
import pytest

import ledger
from api.tests.conftest import LEDGER, ME, PURCHASE_URL, WRITE

GQL = "/api/graphql"


def gql(client, query, **variables):
    r = client.post(GQL, json={"query": query, "variables": variables}, headers=WRITE)
    return r.status_code, r.json()


def data(client, query, **variables):
    status, body = gql(client, query, **variables)
    assert status == 200 and "errors" not in body, body
    return body["data"]


TXNS = """query($first: Int, $after: String, $filter: TransactionFilter, $order: TransactionOrder) {
  transactions(first: $first, after: $after, filter: $filter, orderBy: $order) {
    totalCount sum
    pageInfo { hasNextPage hasPreviousPage endCursor }
    edges { cursor node { id date amount absAmount direction description origin sources
                           merchant { name } category { name source } raw { category { name } } } }
  }
}"""


def test_transactions_newest_first_with_typed_money(client):
    conn = data(client, TXNS)["transactions"]
    assert [e["node"]["date"] for e in conn["edges"]] == ["2026-01-15", "2026-01-10", "2026-01-02"]
    assert conn["totalCount"] == 3 and conn["sum"] == "376.55"
    purchase = conn["edges"][0]["node"]
    assert purchase["amount"] == "-123.45" and purchase["absAmount"] == "123.45"
    assert purchase["direction"] == "EXPENSE"
    assert purchase["category"] == {"name": "קניות", "source": "RISEUP"}
    assert purchase["merchant"] == {"name": "חנות לדוגמה"}
    assert purchase["sources"] == ["cal", "riseup"]


def test_cursor_pages_through_without_overlap(client):
    first = data(client, TXNS, first=2)["transactions"]
    assert first["pageInfo"]["hasNextPage"] and not first["pageInfo"]["hasPreviousPage"]
    rest = data(client, TXNS, first=2, after=first["pageInfo"]["endCursor"])["transactions"]
    assert [e["node"]["date"] for e in rest["edges"]] == ["2026-01-02"]
    assert not rest["pageInfo"]["hasNextPage"] and rest["pageInfo"]["hasPreviousPage"]


def test_cursor_survives_its_row_disappearing(client, owner):
    page = data(client, TXNS, first=1)["transactions"]
    owner.execute("DELETE FROM scraped_transactions WHERE txn_date = '2026-01-15'")
    owner.commit()
    rest = data(client, TXNS, after=page["pageInfo"]["endCursor"])["transactions"]
    assert [e["node"]["date"] for e in rest["edges"]] == ["2026-01-10", "2026-01-02"]


def test_expenses_and_incomes_split_by_direction(client):
    q = "{ expenses { totalCount sum } incomes { totalCount sum edges { node { description } } } }"
    d = data(client, q)
    assert d["expenses"] == {"totalCount": 2, "sum": "-623.45"}
    assert d["incomes"]["sum"] == "1000.00"
    assert d["incomes"]["edges"][0]["node"]["description"] == "העברת משכורת"


def test_filter_by_category_id_and_amount_order(client):
    cats = data(client, "{ categories { edges { node { id name } } } }")["categories"]["edges"]
    shopping = next(e["node"]["id"] for e in cats if e["node"]["name"] == "קניות")
    conn = data(client, TXNS, filter={"categoryIds": [shopping]})["transactions"]
    assert [e["node"]["amount"] for e in conn["edges"]] == ["-123.45"]
    ordered = data(client, TXNS, order="AMOUNT_DESC")["transactions"]["edges"]
    assert [e["node"]["absAmount"] for e in ordered] == ["1000.00", "500.00", "123.45"]


def test_node_refetches_every_node_type(client):
    d = data(client, "{ transactions(first: 1) { edges { node { id merchant { id } category { id } } } } }")
    node = d["transactions"]["edges"][0]["node"]
    q = """query($id: ID!) { node(id: $id) { __typename ... on Transaction { amount }
           ... on Merchant { name } ... on Category { name } } }"""
    assert data(client, q, id=node["id"])["node"] == {"__typename": "Transaction", "amount": "-123.45"}
    assert data(client, q, id=node["merchant"]["id"])["node"]["name"] == "חנות לדוגמה"
    assert data(client, q, id=node["category"]["id"])["node"]["name"] == "קניות"


def test_unknown_id_is_null_but_garbage_is_an_error(client):
    q = "query($id: ID!) { node(id: $id) { id } }"
    from api.gql.relay import to_global_id
    assert data(client, q, id=to_global_id("Transaction", "2020-01-01:1.00"))["node"] is None
    status, body = gql(client, q, id="%%%")
    assert body["data"]["node"] is None and "id" in body["errors"][0]["message"]


def test_categories_root_lists_every_category_with_edge_totals(client):
    # only RiseUp rows arrive categorized; the salary gets its category by hand
    client.patch("/api/transactions/2026-01-10/1000.00", json={"category": "משכורת"}, headers=WRITE)
    q = """{ categories(orderBy: TOTAL_DESC) { totalCount edges { totals { count sum } node { name
             merchants { edges { node { name } totals { count sum } } } } } } }"""
    edges = data(client, q)["categories"]["edges"]
    by_name = {e["node"]["name"]: e for e in edges}
    assert by_name["משכורת"]["totals"] == {"count": 1, "sum": "1000.00"}
    assert edges[0]["node"]["name"] == "משכורת"   # largest absolute total first
    shop = by_name["קניות"]["node"]["merchants"]["edges"]
    assert shop == [{"node": {"name": "חנות לדוגמה"}, "totals": {"count": 1, "sum": "-123.45"}}]


def test_merchant_to_category_edge_is_scoped_to_the_merchant(client):
    q = """{ merchants(search: "חנות") { edges { node { name categories { edges { node { name }
             totals { count sum } } } transactions { totalCount } } } } }"""
    m = data(client, q)["merchants"]["edges"][0]["node"]
    assert m["transactions"]["totalCount"] == 1
    assert m["categories"]["edges"] == [{"node": {"name": "קניות"}, "totals": {"count": 1, "sum": "-123.45"}}]


def test_tags_connect_both_ways_with_tagged_at(client):
    assert client.put(PURCHASE_URL + "/tags", json={"tags": ["טיול"]}, headers=WRITE).status_code == 200
    q = """{ tags { edges { totals { count sum } node { name transactions { edges { node {
             tags { edges { taggedAt node { name } } } } } } merchants { totalCount } } } } }"""
    edge = data(client, q)["tags"]["edges"][0]
    assert edge["node"]["name"] == "טיול" and edge["totals"] == {"count": 1, "sum": "-123.45"}
    txn_tag = edge["node"]["transactions"]["edges"][0]["node"]["tags"]["edges"][0]
    assert txn_tag["node"]["name"] == "טיול" and txn_tag["taggedAt"]
    assert edge["node"]["merchants"]["totalCount"] == 1


def test_excluded_rows_hide_unless_asked(client):
    client.patch(PURCHASE_URL, json={"excluded": True}, headers=WRITE)
    assert data(client, "{ transactions { totalCount } }")["transactions"]["totalCount"] == 2
    q = "{ transactions(filter: {includeExcluded: true}) { totalCount } }"
    assert data(client, q)["transactions"]["totalCount"] == 3


def test_override_shows_effective_and_raw_category_and_audit(client):
    client.patch(PURCHASE_URL, json={"category": "מתנות"}, headers=WRITE)
    q = """{ transactions(first: 1) { edges { node { overridden category { name source }
             raw { category { name } } auditLog { totalCount edges { node { field new actor } } } } } } }"""
    node = data(client, q)["transactions"]["edges"][0]["node"]
    assert node["overridden"] and node["category"] == {"name": "מתנות", "source": "USER"}
    assert node["raw"]["category"] == {"name": "קניות"}
    assert node["auditLog"]["edges"][0]["node"] == {"field": "category", "new": "מתנות", "actor": "me@example.com"}


# --- limits and safety -------------------------------------------------------------------

def test_page_size_is_capped(client):
    status, body = gql(client, "{ transactions(first: 500) { totalCount } }")
    assert "first" in body["errors"][0]["message"]


def test_writes_without_csrf_headers_are_refused(client):
    r = client.post(GQL, json={"query": "{ categories { totalCount } }"})
    assert r.status_code == 403


def test_introspection_is_off_outside_dev(client):
    status, body = gql(client, "{ __schema { types { name } } }")
    assert status == 400 and "introspection" in body["errors"][0]["message"].lower()


def test_deep_queries_are_refused(client):
    nest = "transactions { edges { node { merchant { categories { edges { node { %s } } } } } } }"
    q = "{ " + (nest % (nest % (nest % "name"))) + " }"
    status, body = gql(client, q)
    assert status == 400 and "deeper" in body["errors"][0]["message"]


def test_snapshot_is_an_error_not_a_crash(client):
    status, body = gql(client, "{ snapshot { generatedAt } }")
    assert status == 200 and body["errors"][0]["message"].startswith("snapshot")


@pytest.mark.parametrize("body", [b"not json", b'{"variables": {}}', b'{"query": "{", "x": 1}'])
def test_malformed_requests_are_400(client, body):
    r = client.post(GQL, content=body, headers=WRITE)
    assert r.status_code == 400


# Pairs related directly (1:M) rather than through transactions: a goal's horizon is one object.
ONE_SIDED = {("Goal", "horizons")}


def test_every_group_entity_connects_to_every_other():
    # a new GroupResolver in ENTITIES needs its root field and an M:M field on each peer in the SDL
    from api.gql.endpoint import SCHEMA
    from api.gql.resolvers import ENTITIES
    for a in ENTITIES:
        assert a.plural in SCHEMA.query_type.fields, a.type_name
        for b in ENTITIES:
            if a is not b and (a.type_name, b.plural) not in ONE_SIDED:
                field = SCHEMA.type_map[a.type_name].fields.get(b.plural)
                assert field is not None and field.resolve is not None, f"{a.type_name}.{b.plural}"


# --- mutations ---------------------------------------------------------------------------

from api.gql.relay import to_global_id  # noqa: E402

PURCHASE_ID = to_global_id("Transaction", "2026-01-15:123.45")

UPDATE = """mutation($input: UpdateTransactionInput!) { updateTransaction(input: $input) {
  clientMutationId transaction { id category { name source } note excluded horizon { key } overridden } } }"""


def test_update_transaction_sets_fields_audits_and_signals_one_rebuild(client, owner, rebuilder):
    out = data(client, UPDATE, input={"id": PURCHASE_ID, "clientMutationId": "m1",
                                      "category": "מתנות", "note": "יום הולדת", "horizon": "NEAR"})
    p = out["updateTransaction"]
    assert p["clientMutationId"] == "m1"
    assert p["transaction"] == {"id": PURCHASE_ID, "category": {"name": "מתנות", "source": "USER"},
                                "note": "יום הולדת", "excluded": False, "horizon": {"key": "NEAR"},
                                "overridden": True}
    fields = {r[0] for r in owner.execute("SELECT field FROM override_audit")}
    assert fields == {"category", "note", "horizon"}
    assert rebuilder.signals == 1


def test_null_clears_a_field_and_an_absent_field_is_untouched(client):
    data(client, UPDATE, input={"id": PURCHASE_ID, "category": "מתנות", "note": "x"})
    t = data(client, UPDATE, input={"id": PURCHASE_ID, "note": None})["updateTransaction"]["transaction"]
    assert t["note"] is None and t["category"]["name"] == "מתנות"


def test_update_with_nothing_to_change_is_an_error_and_no_rebuild(client, rebuilder):
    status, body = gql(client, UPDATE, input={"id": PURCHASE_ID})
    assert "at least one" in body["errors"][0]["message"] and rebuilder.signals == 0


def test_unknown_transaction_and_wrong_id_type_are_errors(client, rebuilder):
    status, body = gql(client, UPDATE, input={"id": to_global_id("Transaction", "2020-01-01:1.00"), "note": "x"})
    assert body["errors"][0]["message"] == "no such transaction"
    status, body = gql(client, UPDATE, input={"id": to_global_id("Tag", "1"), "note": "x"})
    assert "not a Transaction" in body["errors"][0]["message"]
    assert rebuilder.signals == 0


def test_clear_override_returns_to_raw_values(client):
    data(client, UPDATE, input={"id": PURCHASE_ID, "category": "מתנות", "excluded": True})
    q = """mutation($id: ID!) { clearTransactionOverride(input: {id: $id}) {
           transaction { overridden excluded category { name } } } }"""
    t = data(client, q, id=PURCHASE_ID)["clearTransactionOverride"]["transaction"]
    assert t == {"overridden": False, "excluded": False, "category": {"name": "קניות"}}


SET_TAGS = """mutation($id: ID!, $tags: [String!]!) { setTransactionTags(input: {id: $id, tags: $tags}) {
  transaction { tags { totalCount edges { node { id name } } } } } }"""


def test_set_tags_replaces_the_set_and_creates_unknown_tags(client, owner):
    data(client, SET_TAGS, id=PURCHASE_ID, tags=["טיול", "החזר"])
    conn = data(client, SET_TAGS, id=PURCHASE_ID, tags=[" טיול "])["setTransactionTags"]["transaction"]["tags"]
    assert [e["node"]["name"] for e in conn["edges"]] == ["טיול"]
    audit = owner.execute("SELECT old, new FROM override_audit WHERE field = 'tags' ORDER BY id").fetchall()
    assert audit == [(None, "החזר"), (None, "טיול"), ("החזר", None)]


def test_blank_tag_name_is_a_validation_error(client):
    status, body = gql(client, SET_TAGS, id=PURCHASE_ID, tags=["  "])
    assert "tag name" in body["errors"][0]["message"]


def test_update_and_delete_tag(client):
    tag_id = data(client, SET_TAGS, id=PURCHASE_ID, tags=["טיול"])[
        "setTransactionTags"]["transaction"]["tags"]["edges"][0]["node"]["id"]
    q = """mutation($id: ID!) { updateTag(input: {id: $id, name: "חופשה", color: "#ff8800"}) {
           tag { id name color } } }"""
    assert data(client, q, id=tag_id)["updateTag"]["tag"] == {"id": tag_id, "name": "חופשה", "color": "#ff8800"}
    q = "mutation($id: ID!) { deleteTag(input: {id: $id}) { deletedTagId } }"
    assert data(client, q, id=tag_id)["deleteTag"]["deletedTagId"] == tag_id
    assert data(client, "{ tags { totalCount } }")["tags"]["totalCount"] == 0


def test_rename_to_a_taken_name_is_refused(client):
    data(client, SET_TAGS, id=PURCHASE_ID, tags=["א", "ב"])
    edges = data(client, "{ tags(orderBy: NAME_ASC) { edges { node { id } } } }")["tags"]["edges"]
    q = 'mutation($id: ID!) { updateTag(input: {id: $id, name: "ב"}) { tag { name } } }'
    status, body = gql(client, q, id=edges[0]["node"]["id"])
    assert "already exists" in body["errors"][0]["message"]


def test_two_mutations_in_one_request_run_in_order_and_signal_once(client, rebuilder):
    q = f"""mutation {{ a: updateTransaction(input: {{id: "{PURCHASE_ID}", note: "1"}}) {{ transaction {{ note }} }}
                     b: updateTransaction(input: {{id: "{PURCHASE_ID}", note: "2"}}) {{ transaction {{ note }} }} }}"""
    d = data(client, q)
    assert (d["a"]["transaction"]["note"], d["b"]["transaction"]["note"]) == ("1", "2")
    assert rebuilder.signals == 1


def test_mutations_need_the_csrf_headers(client, rebuilder):
    r = client.post(GQL, json={"query": UPDATE, "variables": {"input": {"id": PURCHASE_ID, "note": "x"}}})
    assert r.status_code == 403 and rebuilder.signals == 0


# --- horizons and goals ------------------------------------------------------------------

CREATE_GOAL = """mutation($input: CreateGoalInput!) { createGoal(input: $input) {
  clientMutationId goal { id slug description amount endDate interval repetitions rise horizon { key } } } }"""


def _goal(client, **over):
    inp = {"description": "קרן חירום", "amount": "30000", "endDate": "2027-06-30", "horizon": "NEAR", **over}
    return data(client, CREATE_GOAL, input=inp)["createGoal"]["goal"]


def test_horizons_root_lists_the_fixed_three_in_position_order(client):
    q = "{ horizons { totalCount edges { node { key name targetPct } totals { count } } } }"
    conn = data(client, q)["horizons"]
    assert conn["totalCount"] == 3
    assert [e["node"]["key"] for e in conn["edges"]] == ["CURRENT", "NEAR", "FUTURE"]


def test_create_goal_with_typed_money_and_a_horizon(client, rebuilder):
    g = _goal(client)
    assert g["description"] == "קרן חירום" and g["amount"] == "30000.00" and g["rise"] == "0.00"
    assert g["endDate"] == "2027-06-30" and g["horizon"] == {"key": "NEAR"} and g["repetitions"] == 1
    assert rebuilder.signals == 1


def test_assigning_a_transaction_to_a_goal_shows_on_goal_and_horizon(client):
    g = _goal(client)
    data(client, UPDATE, input={"id": PURCHASE_ID, "goalId": g["id"], "horizon": "NEAR"})
    q = """query($id: ID!) { node(id: $id) { ... on Goal { transactions { totalCount sum }
           horizon { goals { edges { node { description } totals { count sum } } } } } } }"""
    node = data(client, q, id=g["id"])["node"]
    assert node["transactions"] == {"totalCount": 1, "sum": "-123.45"}
    assert node["horizon"]["goals"]["edges"] == [{"node": {"description": "קרן חירום"},
                                                  "totals": {"count": 1, "sum": "-123.45"}}]
    q = "{ transactions(filter: {goalIds: [\"%s\"]}) { totalCount } }" % g["id"]
    assert data(client, q)["transactions"]["totalCount"] == 1


def test_assigning_an_unknown_goal_is_an_error(client):
    status, body = gql(client, UPDATE, input={"id": PURCHASE_ID, "goalId": to_global_id("Goal", "999")})
    assert body["errors"][0]["message"] == "no such goal"


def test_update_goal_and_refuse_clearing_required_fields(client):
    g = _goal(client)
    q = """mutation($input: UpdateGoalInput!) { updateGoal(input: $input) { goal { amount interval horizon { key } } } }"""
    out = data(client, q, input={"id": g["id"], "amount": "35000.50", "interval": "YEARLY", "horizon": None})
    assert out["updateGoal"]["goal"] == {"amount": "35000.50", "interval": "YEARLY", "horizon": None}
    status, body = gql(client, q, input={"id": g["id"], "description": None})
    assert "cannot be cleared" in body["errors"][0]["message"]


def test_delete_goal_unassigns_its_transactions(client):
    g = _goal(client)
    data(client, UPDATE, input={"id": PURCHASE_ID, "goalId": g["id"]})
    q = "mutation($id: ID!) { deleteGoal(input: {id: $id}) { deletedGoalId } }"
    assert data(client, q, id=g["id"])["deleteGoal"]["deletedGoalId"] == g["id"]
    t = data(client, "query($id: ID!) { node(id: $id) { ... on Transaction { goal { id } overridden } } }",
             id=PURCHASE_ID)["node"]
    assert t == {"goal": None, "overridden": False}   # the override held only the goal, so it is pruned


def test_transaction_by_key_finds_the_row_the_static_json_knows(client):
    q = "query($d: Date!, $a: Money!) { transactionByKey(date: $d, absAmount: $a) { id amount } }"
    assert data(client, q, d="2026-01-15", a="123.45")["transactionByKey"] == {"id": PURCHASE_ID, "amount": "-123.45"}
    assert data(client, q, d="2026-01-15", a="9.99")["transactionByKey"] is None


# --- offsets (קיזוז) ---------------------------------------------------------------

REFUND = {"date": "2026-01-20", "amount": 23.45, "description": "חנות לדוגמה", "origin": "cal",
          "is_income": True, "sources": ["cal"]}
FRIEND = {"date": "2026-01-18", "amount": 50.0, "description": "מפייבוקס ש", "origin": "discount",
          "is_income": True, "sources": ["discount"]}
FRIEND_ID = to_global_id("Transaction", "2026-01-18:50.00")
SALARY_ID = to_global_id("Transaction", "2026-01-10:1000.00")

OFFSETS = """query($id: ID!) { node(id: $id) { ... on Transaction {
  amount netAmount offsetAmount offsetsManual isRoundTrip
  offsets { amount kind transaction { date description } }
  offsetCandidates { totalCount edges { node { date amount } } } } } }"""
LINK = """mutation($p: ID!, $e: ID!, $amount: Money) {
  linkOffset(input: {paybackId: $p, expenseId: $e, amount: $amount}) {
    payback { netAmount offsetsManual } expense { netAmount offsets { amount kind } } } }"""
UNLINK = """mutation($p: ID!, $e: ID!) { unlinkOffset(input: {paybackId: $p, expenseId: $e}) {
    payback { offsetsManual offsets { amount } } expense { netAmount } } }"""
RESET = """mutation($p: ID!) { resetOffsets(input: {paybackId: $p}) { payback { offsetsManual } } }"""


@pytest.fixture
def with_paybacks(owner):
    from finance import offsets
    rows = offsets.suggest([dict(t) for t in [*LEDGER, REFUND, FRIEND]])   # what the digest stores
    ledger.load(owner, rows)
    owner.commit()


def test_an_auto_refund_shows_on_the_purchase_with_its_net(client, with_paybacks):
    t = data(client, OFFSETS, id=PURCHASE_ID)["node"]
    assert (t["netAmount"], t["offsetAmount"], t["offsetsManual"]) == ("-100.00", "23.45", False)
    assert t["offsets"] == [{"amount": "23.45", "kind": "REFUND",
                             "transaction": {"date": "2026-01-20", "description": "חנות לדוגמה"}}]
    # the refund is used up, so the friend's Bit and the salary are what's left to pick from
    assert [e["node"]["date"] for e in t["offsetCandidates"]["edges"]] == ["2026-01-18", "2026-01-10"]


def test_link_a_friends_bit_to_dinner_then_unlink_and_reset(client, owner, rebuilder, with_paybacks):
    # As the household, a friend's ₪50 paid back part of the ₪123.45 purchase.
    d = data(client, LINK, p=FRIEND_ID, e=PURCHASE_ID)["linkOffset"]
    assert d["payback"] == {"netAmount": "0.00", "offsetsManual": True}
    assert d["expense"]["netAmount"] == "-50.00"
    assert sorted(o["kind"] for o in d["expense"]["offsets"]) == ["MANUAL", "REFUND"]
    assert owner.execute("SELECT expense_date::text, amount::text FROM transaction_offsets").fetchall() \
        == [("2026-01-15", "50.00")]
    audit = owner.execute("SELECT actor, field, old, new FROM override_audit WHERE field = 'offsets'").fetchall()
    assert audit == [(ME, "offsets", "auto", [{"date": "2026-01-15", "abs_amount": "123.45", "amount": "50.00"}])]

    d = data(client, UNLINK, p=FRIEND_ID, e=PURCHASE_ID)["unlinkOffset"]
    assert d["payback"] == {"offsetsManual": True, "offsets": []}       # decided: offsets nothing
    assert d["expense"]["netAmount"] == "-100.00"
    assert data(client, RESET, p=FRIEND_ID)["resetOffsets"]["payback"] == {"offsetsManual": False}
    assert rebuilder.signals == 3


def test_link_amounts_are_checked_against_what_is_left(client, with_paybacks):
    status, body = gql(client, LINK, p=FRIEND_ID, e=PURCHASE_ID, amount="60.00")
    assert "at most ₪50.00" in body["errors"][0]["message"]
    status, body = gql(client, LINK, p=SALARY_ID, e=FRIEND_ID)
    assert "must be money out" in body["errors"][0]["message"]
    data(client, LINK, p=FRIEND_ID, e=PURCHASE_ID, amount="20.00")
    d = data(client, LINK, p=FRIEND_ID, e=PURCHASE_ID, amount="30.00")["linkOffset"]   # replaces, not adds
    assert d["payback"]["netAmount"] == "20.00"
