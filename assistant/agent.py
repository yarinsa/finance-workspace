"""Tool-calling loop: the model asks for read-only tools until it can answer."""
import json
from datetime import date

from assistant import llm

MAX_STEPS = 6

SYSTEM = """You are the household's finance assistant. Currency is ILS (₪). Answer in the user's language.
Use the tools for every number; never guess or compute from memory. Money out is negative in transaction rows.
Spending tools already exclude own transfers, card settlements and savings. If a tool returns nothing or an error, say so.
Today is {today}. Be brief."""


def start(history=None):
    """A fresh conversation: the system prompt, then any prior user/assistant turns."""
    return [{"role": "system", "content": SYSTEM.format(today=date.today().isoformat())}, *(history or [])]


def run(messages, toolbox, chat=llm.chat, should_stop=lambda: False):
    """Advance `messages` (mutated in place) until the model answers. Yields ("tool", {name, arguments})
    before each tool runs, then ("answer", text). Stops quietly when `should_stop()` turns true."""
    for _ in range(MAX_STEPS):
        if should_stop():
            return
        msg = chat(messages, tools=toolbox.schemas())
        messages.append(msg)
        calls = msg.get("tool_calls")
        if not calls:
            yield "answer", llm.strip_think(msg.get("content"))
            return
        for c in calls:
            fn = c["function"]
            args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
            yield "tool", {"name": fn["name"], "arguments": args}
            messages.append({"role": "tool", "tool_call_id": c.get("id"), "content": toolbox.call_json(fn["name"], args)})
    yield "answer", "I could not finish within the step limit."


def ask(question, toolbox, history=None, chat=llm.chat):
    """Answer one question; returns (answer, messages) so the CLI can keep the conversation."""
    messages = history or start()
    messages.append({"role": "user", "content": question})
    answer = next(text for kind, text in run(messages, toolbox, chat) if kind == "answer")
    return answer, messages
