"""The daily position history (`finance.tables.PositionSnapshot`), one row per date.

data/history.py records today's row on every digest and reads the whole series back
into `cashflow.json` -> `history.positions`. Takes an open psycopg connection; writes commit.
"""
import datetime as dt
from decimal import Decimal

from sqlmodel import select

from finance.tables import PositionSnapshot
from ledger import orm_session

FIELDS = ("cash", "card_debt", "consumer_loans", "mortgage", "savings", "property", "net_worth")


def _row(p):
    return {"date": p.date.isoformat(),
            **{k: (None if getattr(p, k) is None else float(getattr(p, k))) for k in FIELDS}}


def record(conn, day, **values):
    """Upsert the position of `day` (a later digest the same day overwrites it)."""
    with orm_session(conn) as s:
        p = s.exec(select(PositionSnapshot).where(PositionSnapshot.date == day)).first() or PositionSnapshot(date=day, **{k: Decimal(0) for k in FIELDS})
        for k in FIELDS:
            v = values.get(k)
            setattr(p, k, None if v is None else Decimal(str(round(v, 2))))
        p.recorded_at = dt.datetime.now(dt.timezone.utc)
        s.add(p)
        s.commit()


def series(conn):
    """Every recorded day, oldest first."""
    with orm_session(conn) as s:
        return [_row(p) for p in s.exec(select(PositionSnapshot).order_by(PositionSnapshot.date)).all()]
