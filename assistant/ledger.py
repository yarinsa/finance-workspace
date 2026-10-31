"""Where the assistant's rows come from. Tools only see this interface, so the same tools run on the
digested JSON (CLI, master household) and on the tenant-bound database (API; see api/assistant_ledger.py)."""
import json
from pathlib import Path

from finance.offsets import cashflow_view


class JsonLedger:
    """The digested files of one household directory (no tenancy: the CLI only)."""

    def __init__(self, directory):
        self.dir = Path(directory)

    def rows(self):
        """Ledger rows as spending is counted: paybacks netted against their expense."""
        return cashflow_view(json.loads((self.dir / "transactions.json").read_text())["transactions"])

    def snapshot(self):
        """The net-worth snapshot, or None when it is not available."""
        path = self.dir / "snapshot.json"
        return json.loads(path.read_text()) if path.exists() else None
