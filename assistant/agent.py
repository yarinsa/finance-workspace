"""Tool-calling loop: the model asks for read-only tools until it can answer."""
import json
from datetime import date

from assistant import llm

MAX_STEPS = 6

SYSTEM = """You are the household's finance assistant. Currency is ILS (₪). Answer in the user's language.
Use the tools for every number; never guess or compute from memory. Money out is negative in transaction rows.
Spending tools already exclude own transfers, card settlements and savings. If a tool returns nothing or an error, say so.
Today is {today}. Be brief."""


def ask(question, toolbox, history=None, chat=llm.chat):
    """Answer one question with `toolbox`; returns (answer, messages). `chat` is injectable for tests."""
    messages = history or [{"role": "system", "content": SYSTEM.format(today=date.today().isoformat())}]
    messages.append({"role": "user", "content": question})
    for _ in range(MAX_STEPS):
        msg = chat(messages, tools=toolbox.schemas())
        messages.append(msg)
        calls = msg.get("tool_calls")
        if not calls:
            return llm.strip_think(msg.get("content")), messages
        for c in calls:
            fn = c["function"]
            args = fn["arguments"]
            content = toolbox.call_json(fn["name"], json.loads(args) if isinstance(args, str) else args)
            messages.append({"role": "tool", "tool_call_id": c.get("id"), "content": content})
    return "I could not finish within the step limit.", messages
