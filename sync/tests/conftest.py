"""Put sync/ on sys.path so tests can `import activities`, `import workflows`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # repo root: finance.push


import dataclasses

import pytest


@pytest.fixture(autouse=True)
def guard_database_writes(monkeypatch):
    """Prevent all tests from accidentally writing to the real Postgres database.

    By default, makes _database_url() return None and replaces _db_upsert_status with
    a function that raises AssertionError. Tests that intentionally exercise the DB
    path can override this by:
    - Monkeypatching _database_url to return a test URL
    - Monkeypatching _db_upsert_status directly
    """
    import activities

    # Block _database_url() from returning a real URL
    monkeypatch.setattr(activities, "_database_url", lambda: None)

    # Replace _db_upsert_status with a guard that fails loudly if called
    def guarded_upsert(url, source, entry):
        raise AssertionError(
            f"test tried to write to real Postgres: _db_upsert_status(url={url!r}, source={source!r}). "
            "Tests must explicitly monkeypatch _database_url() or _db_upsert_status to use the database."
        )

    monkeypatch.setattr(activities, "_db_upsert_status", guarded_upsert)


@pytest.fixture
def chrome_harel(monkeypatch):
    """Harel as it was before it went headless (Chrome on 9227, playwright-cli, check_sessions.sh):
    no real source uses that path any more, but the Chrome/tab/attach code still has to work."""
    import sources

    src = dataclasses.replace(
        sources.get("harel"), name="chrome-harel", check=sources.SESSIONS, playwright=True,
        chrome="harel", tab_key="harel", login_url="https://www.harel-group.co.il/",
        dumps=(("refresh/scripts/harel/dump.sh", "{session}"),))
    monkeypatch.setitem(sources.SOURCES, src.name, src)
    return src
