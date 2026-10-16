"""POST /api/graphql, read side, against the throwaway test database.

The ledger is conftest's: PURCHASE (-123.45, cal, קניות), SALARY (+1000, משכורת),
CARD_BILL (-500, חיובי כרטיס). Each test is a question the dashboard asks.
"""
import pytest

from api.tests.conftest import PURCHASE_URL, WRITE

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


def test_mutations_are_not_served_yet(client):
    q = 'mutation { deleteTag(input: {id: "x"}) { deletedTagId } }'
    status, body = gql(client, q)
    assert status == 400 and "mutation" in body["errors"][0]["message"]


def test_snapshot_is_an_error_not_a_crash(client):
    status, body = gql(client, "{ snapshot { generatedAt } }")
    assert status == 200 and body["errors"][0]["message"].startswith("snapshot")


@pytest.mark.parametrize("body", [b"not json", b'{"variables": {}}', b'{"query": "{", "x": 1}'])
def test_malformed_requests_are_400(client, body):
    r = client.post(GQL, content=body, headers=WRITE)
    assert r.status_code == 400


def test_every_group_entity_connects_to_every_other():
    # a new GroupResolver in ENTITIES needs its root field and an M:M field on each peer in the SDL
    from api.gql.endpoint import SCHEMA
    from api.gql.resolvers import ENTITIES
    for a in ENTITIES:
        assert a.plural in SCHEMA.query_type.fields, a.type_name
        for b in ENTITIES:
            if a is not b:
                field = SCHEMA.type_map[a.type_name].fields.get(b.plural)
                assert field is not None and field.resolve is not None, f"{a.type_name}.{b.plural}"
