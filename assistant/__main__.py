"""`poetry run python -m assistant "how much did I spend on food last month?"` or no args for a chat."""
import sys

from assistant import agent


def main():
    if len(sys.argv) > 1:
        print(agent.ask(" ".join(sys.argv[1:]))[0])
        return
    history = None
    while True:
        try:
            q = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if q:
            answer, history = agent.ask(q, history)
            print(answer)


main()
