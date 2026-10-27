"""Assets no scraper sees (the apartment), through `finance.tables.Asset`.

Shared by data/digest.py (reads them into `snapshot.totals`) and the ledger API
(`assetCreate` / `assetUpdate`). Every function takes an open psycopg connection;
writes commit. Values are typed in by hand for now (`valuation_source` 'manual').

    .venv/bin/python db/asset_store.py list
    .venv/bin/python db/asset_store.py set-property VALUE [LABEL]    # create or update the apartment
"""
import datetime as dt
import sys
from decimal import Decimal

from sqlmodel import select

from finance.tables import Asset
from ledger import orm_session

KINDS = ("property",)
SOURCES = ("manual", "estimate")
EDITABLE = ("label", "value", "valued_at", "valuation_source")


def _asset(a):
    return {"id": a.id, "kind": a.kind, "label": a.label, "value": float(a.value),
            "valued_at": a.valued_at.isoformat(), "valuation_source": a.valuation_source,
            "updated_at": a.updated_at.isoformat() if a.updated_at else None}


def _apply(a, fields):
    for k, v in fields.items():
        if k not in EDITABLE:
            raise ValueError(f"not an asset field: {k}")
        if k == "value":
            if v is None or Decimal(str(v)) < 0:
                raise ValueError("value must be a non-negative amount")
            v = Decimal(str(v))
        elif k == "valuation_source" and v not in SOURCES:
            raise ValueError(f"valuation_source must be one of {SOURCES}")
        elif k in ("label", "valued_at") and v is None:
            raise ValueError(f"{k} cannot be cleared")
        setattr(a, k, v)


def all_assets(conn):
    """Every asset, oldest first."""
    with orm_session(conn) as s:
        return [_asset(a) for a in s.exec(select(Asset).order_by(Asset.id)).all()]


def get_asset(conn, asset_id):
    with orm_session(conn) as s:
        a = s.get(Asset, asset_id)
        return _asset(a) if a else None


def create_asset(conn, kind, label, value, valued_at=None, valuation_source="manual"):
    """Add an asset; `valued_at` defaults to today. Returns it."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    a = Asset(kind=kind, label=label, value=Decimal("0"), valued_at=valued_at or dt.date.today())
    _apply(a, {"value": value, "valuation_source": valuation_source})
    with orm_session(conn) as s:
        s.add(a)
        s.commit()
        s.refresh(a)
        return _asset(a)


def update_asset(conn, asset_id, **fields):
    """Change an asset's label/value/valued_at/valuation_source; None if it does not exist.
    A new value without a date is dated today (it is a fresh valuation)."""
    if "value" in fields and "valued_at" not in fields:
        fields["valued_at"] = dt.date.today()
    with orm_session(conn) as s:
        a = s.get(Asset, asset_id)
        if not a:
            return None
        _apply(a, fields)
        a.updated_at = dt.datetime.now(dt.timezone.utc)
        s.commit()
        s.refresh(a)
        return _asset(a)


def main(argv):
    from ledger import connect
    with connect() as conn:
        if argv[:1] == ["list"]:
            for a in all_assets(conn):
                print(f"{a['id']:>3}  {a['kind']:<9} {a['label']:<20} {a['value']:>14,.2f}  {a['valued_at']}  {a['valuation_source']}")
        elif argv[:1] == ["set-property"] and len(argv) >= 2:
            label = argv[2] if len(argv) > 2 else "דירה"
            mine = next((a for a in all_assets(conn) if a["kind"] == "property"), None)
            a = (update_asset(conn, mine["id"], value=argv[1], label=label) if mine
                 else create_asset(conn, "property", label, argv[1]))
            print(f"{a['label']}: {a['value']:,.2f} ({a['valued_at']})")
        else:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
