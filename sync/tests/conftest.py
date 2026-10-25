"""Put sync/ on sys.path so tests can `import activities`, `import workflows`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


import dataclasses

import pytest


@pytest.fixture
def chrome_harel(monkeypatch):
    """Harel as it was before it went headless (Chrome on 9227, playwright-cli, check_sessions.sh):
    no real source uses that path any more, but the Chrome/tab/attach code still has to work."""
    import sources

    src = dataclasses.replace(
        sources.get("harel"), name="chrome-harel", check=sources.SESSIONS, playwright=True,
        chrome="harel", tab_key="harel", login_url="https://www.harel-group.co.il/",
        dumps=(("harel-refresh/scripts/dump.sh", "{session}"),))
    monkeypatch.setitem(sources.SOURCES, src.name, src)
    return src
