"""POST /api/assistant/chat: the household's questions to the local model, answered from the caller's tenant.

Stateless: the client sends the conversation each time (kept in memory in the app, v1). The reply is a
Server-Sent Events stream: `tool` as each read-only tool runs, then one `answer` and `done`, or an
`error`. The ledger is loaded once through the request's tenant-bound connection and the connection is
released before the slow model calls start, so a chat never holds one of the pool's few connections.
Contract: docs/ledger-api.md."""
import asyncio
import logging
import threading
import time
from collections import defaultdict, deque
from functools import partial
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from assistant import agent, llm
from assistant.ledger import StaticLedger
from assistant.tools import Toolbox

from .assistant_ledger import DbLedger
from .errors import ApiError
from .sse import END, sse

log = logging.getLogger("finance_api")

MAX_BODY = 16 * 1024
MAX_MESSAGES = 20
MAX_CHARS = 2000
MAX_CHATS = 2             # one local GPU
PER_MINUTE = 20
DEADLINE_SECONDS = 120
PING_SECONDS = 15         # CloudFront's origin read timeout is 30 s
TICK_SECONDS = 1


class ChatMessage(BaseModel):
    """Only user/assistant turns come from the client: it can never inject system or tool messages."""
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=MAX_CHARS)

    @field_validator("content")
    @classmethod
    def not_blank(cls, v):
        if not v.strip():
            raise ValueError("content is blank")
        return v


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messages: list[ChatMessage] = Field(min_length=1, max_length=MAX_MESSAGES)

    @field_validator("messages")
    @classmethod
    def ends_with_user(cls, v):
        if v[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return v


class RateLimit:
    """Sliding window per user, in memory (one API process)."""

    def __init__(self, per_minute=PER_MINUTE, clock=time.monotonic):
        self.per_minute, self.clock = per_minute, clock
        self.hits = defaultdict(deque)

    def allow(self, user):
        now, hits = self.clock(), self.hits[user]
        while hits and now - hits[0] > 60:
            hits.popleft()
        if len(hits) >= self.per_minute:
            return False
        hits.append(now)
        return True


def default_chat(settings):
    return partial(llm.chat, base_url=settings.assistant_base_url, model=settings.assistant_model, timeout=90)


class Slot:
    """One of the few concurrent chats. The worker frees it when it ends; `cleanup` (the response's
    background task) frees it only if the stream never started, so a client that vanished early leaks nothing."""

    def __init__(self, st):
        self.st, self.started, self.freed = st, False, False

    def release(self):
        if not self.freed:
            self.freed = True
            self.st.assistant_chats -= 1

    def cleanup(self):
        if not self.started:
            self.release()


def admit(st, user):
    """Refuse before streaming starts; returns the taken `Slot`."""
    if not st.settings.assistant_base_url:
        raise ApiError(503, "assistant_off", "the assistant is not configured")
    if not st.assistant_rate.allow(user):
        raise ApiError(429, "rate_limited", "too many questions, try again in a minute")
    if st.assistant_chats >= st.assistant_max_chats:
        raise ApiError(503, "assistant_busy", "the assistant is answering other questions, try again shortly")
    st.assistant_chats += 1
    return Slot(st)


async def stream(request, st, body, db, slot):
    """The SSE frames for one chat. `db` is `api.app.db`; `slot` is freed when the worker ends."""
    slot.started = True
    loop = asyncio.get_running_loop()
    queue, stop = asyncio.Queue(), threading.Event()
    messages = agent.start([m.model_dump() for m in body.messages])
    deadline = loop.time() + st.assistant_deadline

    def put(item):
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def work():
        try:
            with db(request) as conn:
                rows = DbLedger(conn).rows()
            toolbox = Toolbox(StaticLedger(rows))
            for kind, data in agent.run(messages, toolbox, chat=st.assistant_chat, should_stop=stop.is_set):
                put((kind, {"text": data} if kind == "answer" else data))
        except ApiError as e:
            put(("error", {"error": e.code, "message": e.message}))
        except Exception:
            log.exception("assistant chat failed")
            put(("error", {"error": "assistant_unavailable", "message": "the assistant could not answer right now"}))
        finally:
            loop.call_soon_threadsafe(slot.release)
            put(END)

    loop.run_in_executor(None, work)
    try:
        yield "retry: 5000\n\n"
        next_ping = loop.time() + st.assistant_ping
        while True:
            now = loop.time()
            if now >= deadline:
                stop.set()
                yield sse("error", {"error": "timeout", "message": "the assistant took too long"})
                return
            if await request.is_disconnected():
                stop.set()
                return
            try:
                item = await asyncio.wait_for(queue.get(), timeout=max(0.01, min(TICK_SECONDS, next_ping - now, deadline - now)))
            except asyncio.TimeoutError:
                if loop.time() >= next_ping:
                    next_ping = loop.time() + st.assistant_ping
                    yield ": ping\n\n"
                continue
            if item is END:
                yield sse("done", {})
                return
            yield sse(*item)
            if item[0] == "error":
                return
    finally:
        stop.set()
