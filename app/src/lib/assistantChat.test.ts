import { describe, expect, it } from "vitest";
import {
  bidiSegments,
  chatReducer,
  conversationPayload,
  createSseParser,
  failureFromCode,
  failureFromStatus,
  initialChat,
  sendChat,
  toolLabel,
  type ChatState,
  type Turn,
} from "./assistantChat";

const sse = (event: string, data: unknown) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

describe("createSseParser", () => {
  it("reads whole events and ignores pings", () => {
    const parse = createSseParser();
    const evs = parse(`: ping\n\n${sse("tool", { name: "monthly_totals", arguments: { months: 3 } })}${sse("answer", { text: "₪1,200" })}${sse("done", {})}`);
    expect(evs).toEqual([
      { type: "tool", name: "monthly_totals", arguments: { months: 3 } },
      { type: "answer", text: "₪1,200" },
      { type: "done" },
    ]);
  });

  it("holds an event split across chunks, even mid-delimiter, and handles CRLF", () => {
    const parse = createSseParser();
    const raw = sse("answer", { text: "שלום" }).replace(/\n/g, "\r\n");
    const out = [...raw].flatMap((ch) => parse(ch));
    expect(out).toEqual([{ type: "answer", text: "שלום" }]);
  });

  it("maps error events and skips unknown events or bad JSON", () => {
    const parse = createSseParser();
    expect(parse(`event: weird\ndata: {}\n\nevent: answer\ndata: {oops\n\n${sse("error", { error: "timeout", message: "x" })}`)).toEqual([
      { type: "error", code: "timeout", message: "x" },
    ]);
  });
});

describe("failures", () => {
  it("classifies refusals and stream errors", () => {
    expect(failureFromStatus(503, "assistant_off")).toBe("off");
    expect(failureFromStatus(503, "assistant_busy")).toBe("busy");
    expect(failureFromStatus(503)).toBe("unavailable");
    expect(failureFromStatus(429, "rate_limited")).toBe("rate_limited");
    expect(failureFromStatus(413)).toBe("too_long");
    expect(failureFromStatus(422)).toBe("too_long");
    expect(failureFromCode("timeout")).toBe("timeout");
    expect(failureFromCode("assistant_unavailable")).toBe("unavailable");
  });
});

describe("tool labels", () => {
  it("has Hebrew for the four tools and a fallback", () => {
    for (const n of ["spending_by_category", "monthly_totals", "search_transactions", "snapshot_totals"]) {
      expect(toolLabel(n)).toMatch(/[א-ת]/);
    }
    expect(toolLabel("spending_by_category")).toBe("בודק הוצאות לפי קטגוריה…");
    expect(toolLabel("nope")).toBe("בודק את הנתונים…");
  });
});

describe("conversationPayload", () => {
  it("keeps the last 20 turns and starts with the user", () => {
    const turns: Turn[] = Array.from({ length: 23 }, (_, i) => ({ role: i % 2 === 0 ? "user" : "assistant", content: String(i) }));
    const p = conversationPayload(turns);
    expect(p.length).toBeLessThanOrEqual(20);
    expect(p[0].role).toBe("user");
    expect(p[p.length - 1].content).toBe("22");
  });
});

describe("chatReducer", () => {
  const send = (s: ChatState, text: string) => chatReducer(s, { type: "send", text });

  it("send disables further sends until the reply ends", () => {
    const s1 = send(initialChat, " כמה הוצאנו? ");
    expect(s1.waiting).toBe(true);
    expect(s1.turns).toEqual([{ role: "user", content: "כמה הוצאנו?" }]);
    expect(send(s1, "עוד")).toBe(s1);
    expect(send(initialChat, "   ")).toBe(initialChat);
  });

  it("tool then answer then finish", () => {
    let s = send(initialChat, "שאלה");
    s = chatReducer(s, { type: "tool", name: "snapshot_totals" });
    expect(s.tool).toBe("snapshot_totals");
    s = chatReducer(s, { type: "answer", text: "תשובה" });
    s = chatReducer(s, { type: "finish" });
    expect(s).toMatchObject({ waiting: false, tool: null, failure: null });
    expect(s.turns.map((t) => t.role)).toEqual(["user", "assistant"]);
  });

  it("a failure hands the question back and shows the reason", () => {
    const s = chatReducer(send(initialChat, "שאלה"), { type: "fail", failure: "busy" });
    expect(s).toMatchObject({ waiting: false, turns: [], draft: "שאלה", failure: "busy" });
  });

  it("an abort shows no failure but keeps the question for editing", () => {
    const s = chatReducer(send(initialChat, "שאלה"), { type: "fail", failure: "aborted" });
    expect(s).toMatchObject({ waiting: false, failure: null, draft: "שאלה" });
  });

  it("a failure after earlier answers keeps the transcript", () => {
    let s = send(initialChat, "א");
    s = chatReducer(chatReducer(s, { type: "answer", text: "ב" }), { type: "finish" });
    s = chatReducer(send(s, "ג"), { type: "fail", failure: "timeout" });
    expect(s.turns).toHaveLength(2);
    expect(s.failure).toBe("timeout");
  });

  it("a new send clears the previous failure; reset clears everything", () => {
    const failed = chatReducer(send(initialChat, "א"), { type: "fail", failure: "unavailable" });
    expect(send(failed, "א").failure).toBeNull();
    expect(chatReducer(failed, { type: "reset" })).toEqual(initialChat);
  });
});

describe("bidiSegments", () => {
  const ltr = (t: string) => bidiSegments(t).filter((s) => s.ltr).map((s) => s.text);

  it("isolates amounts, percents and dates", () => {
    expect(ltr("הוצאתם ₪1,234 על אוכל, 12% מההכנסה ב-2026-10.")).toEqual(["₪1,234", "12%", "2026-10"]);
  });
  it("keeps a minus on a stand-alone number but not a hyphen after a Hebrew prefix", () => {
    expect(ltr("יתרה של -₪500")).toEqual(["-₪500"]);
    expect(ltr("ב-11/11 החשבון")).toEqual(["11/11"]);
  });
  it("isolates Latin names and round-trips the text", () => {
    const text = "חיוב של Netflix בסך 49.90 ₪";
    expect(ltr(text)).toEqual(["Netflix", "49.90 ₪"]);
    expect(bidiSegments(text).map((s) => s.text).join("")).toBe(text);
  });
});

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const ch of chunks) c.enqueue(enc.encode(ch));
      c.close();
    },
  });
}

describe("sendChat", () => {
  const turns: Turn[] = [{ role: "user", content: "שלום" }];
  const run = (res: Response | Error) => {
    const seen: string[] = [];
    const f = (async () => {
      if (res instanceof Error) throw res;
      return res;
    }) as unknown as typeof fetch;
    return sendChat(turns, { onTool: (n) => seen.push(`tool:${n}`), onAnswer: (t) => seen.push(`answer:${t}`) }, new AbortController().signal, f).then((r) => ({ r, seen }));
  };

  it("streams tool and answer events", async () => {
    const body = streamOf([sse("tool", { name: "monthly_totals", arguments: {} }), sse("answer", { text: "הנה" }).slice(0, 12), sse("answer", { text: "הנה" }).slice(12), sse("done", {})]);
    const { r, seen } = await run(new Response(body, { status: 200, headers: { "content-type": "text/event-stream" } }));
    expect(r).toBeNull();
    expect(seen).toEqual(["tool:monthly_totals", "answer:הנה"]);
  });

  it("sends the CSRF headers", async () => {
    let init: RequestInit | undefined;
    const f = (async (_u: string, i: RequestInit) => {
      init = i;
      return new Response(streamOf([sse("answer", { text: "x" })]), { status: 200 });
    }) as unknown as typeof fetch;
    await sendChat(turns, { onTool() {}, onAnswer() {} }, new AbortController().signal, f);
    expect((init?.headers as Record<string, string>)["X-Requested-With"]).toBe("finance-app");
    expect(init?.method).toBe("POST");
  });

  it("maps refusals", async () => {
    const json = (status: number, error: string) => new Response(JSON.stringify({ error, message: "" }), { status, headers: { "content-type": "application/json" } });
    expect((await run(json(503, "assistant_off"))).r).toBe("off");
    expect((await run(json(503, "assistant_busy"))).r).toBe("busy");
    expect((await run(json(429, "rate_limited"))).r).toBe("rate_limited");
    expect((await run(new Response("<html>", { status: 503 }))).r).toBe("unavailable");
    expect((await run(new Error("net"))).r).toBe("unavailable");
  });

  it("maps a stream timeout error and a stream that ends with nothing", async () => {
    expect((await run(new Response(streamOf([sse("error", { error: "timeout", message: "" })]), { status: 200 }))).r).toBe("timeout");
    expect((await run(new Response(streamOf([sse("tool", { name: "x", arguments: {} })]), { status: 200 }))).r).toBe("unavailable");
  });

  it("an abort resolves as aborted", async () => {
    const ctl = new AbortController();
    const f = ((_u: string, i: RequestInit) =>
      new Promise((_res, rej) => i.signal?.addEventListener("abort", () => rej(new DOMException("a", "AbortError"))))) as unknown as typeof fetch;
    const p = sendChat(turns, { onTool() {}, onAnswer() {} }, ctl.signal, f);
    ctl.abort();
    expect(await p).toBe("aborted");
  });
});
