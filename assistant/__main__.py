"""`poetry run python -m assistant "how much did I spend on food last month?"` or no args for a chat."""
import os
import sys
from pathlib import Path

from assistant import agent
from assistant.ledger import JsonLedger
from assistant.tools import Toolbox

DIGESTED = os.environ.get("FINANCE_DIGESTED_DIR", Path(__file__).resolve().parents[1] / "data" / "digested")


def main():
    toolbox = Toolbox(JsonLedger(DIGESTED))
    if len(sys.argv) > 1:
        print(agent.ask(" ".join(sys.argv[1:]), toolbox)[0])
        return
    history = None
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if q:
            answer, history = agent.ask(q, toolbox, history)
            print(answer)


main()
