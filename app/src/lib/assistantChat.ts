// Client for the local assistant (`POST /api/assistant/chat`, docs/ledger-api.md "Assistant chat").
// Stateless server: the whole conversation is sent each time and lives in memory only. The reply
// is `text/event-stream` over POST (so no EventSource): `parseSse` reads it by hand.
import { unauthenticated } from "./api";
import { tenantHeaders } from "./tenant";

export interface Turn {
  role: "user" | "assistant";
  content: string;
}

/** Server limits: 1-20 turns of at most 2000 characters, the last one the user's. */
export const MAX_TURNS = 20;
export const MAX_CHARS = 2000;
/** Longer than the server's own model timeout, so its `timeout` event normally arrives first. */
export const CLIENT_TIMEOUT_MS = 150_000;

/** Why a chat request did not produce an answer. `off` hides the chat; the others are shown calmly. */
export type ChatFailure = "off" | "busy" | "rate_limited" | "too_long" | "timeout" | "unavailable";

export type ChatEvent =
  | { type: "tool"; name: string; arguments: unknown }
  | { type: "answer"; text: string }
  | { type: "done" }
  | { type: "error"; code: string; message: string };

/** Calm Hebrew for each failure (what happened, what to do). */
export const FAILURE_TEXT: Record<Exclude<ChatFailure, "off">, string> = {
  busy: "העוזר עסוק בשיחה אחרת. אפשר לנסות שוב בעוד רגע.",
  rate_limited: "שלחתם הרבה שאלות בזמן קצר. כדאי לחכות דקה ולנסות שוב.",
  too_long: "השיחה ארוכה מדי. אפשר להתחיל שיחה חדשה.",
  timeout: "התשובה לוקחת יותר זמן מהרגיל. אפשר לנסות שוב.",
  unavailable: "העוזר לא זמין כרגע. אפשר לנסות שוב מאוחר יותר.",
};

/** The four read-only tools, in words: shown while one runs. */
const TOOL_LABELS: Record<string, string> = {
  spending_by_category: "בודק הוצאות לפי קטגוריה…",
  monthly_totals: "בודק סיכומים חודשיים…",
  search_transactions: "מחפש בתנועות…",
  snapshot_totals: "בודק את תמונת המצב…",
};

export function toolLabel(name: string): string {
  return TOOL_LABELS[name] ?? "בודק את הנתונים…";
}

/**
 * Incremental SSE parser. Feed it decoded text chunks as they arrive (a chunk may end mid-event);
 * it returns the events completed so far. Handles LF/CRLF, `:` comment lines (the server's pings),
 * and ignores events it does not know or whose data is not JSON.
 */
export function createSseParser(): (chunk: string) => ChatEvent[] {
  let buffer = "";
  return (chunk) => {
    buffer += chunk;
    const out: ChatEvent[] = [];
    // A trailing CR may be the first half of a CRLF: wait for the next chunk before reading it.
    const held = buffer.endsWith("\r") ? "\r" : "";
    const blocks = buffer.slice(0, buffer.length - held.length).replace(/\r\n?/g, "\n").split("\n\n");
    buffer = (blocks.pop() ?? "") + held;
    for (const block of blocks) {
      const ev = parseBlock(block);
      if (ev) out.push(ev);
    }
    return out;
  };
}

function parseBlock(block: string): ChatEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const i = line.indexOf(":");
    const field = i === -1 ? line : line.slice(0, i);
    const value = i === -1 ? "" : line.slice(i + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  let payload: Record<string, unknown> = {};
  if (data.length) {
    try {
      const parsed: unknown = JSON.parse(data.join("\n"));
      if (parsed && typeof parsed === "object") payload = parsed as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  const str = (v: unknown) => (typeof v === "string" ? v : "");
  switch (event) {
    case "tool":
      return { type: "tool", name: str(payload.name), arguments: payload.arguments };
    case "answer":
      return { type: "answer", text: str(payload.text) };
    case "done":
      return { type: "done" };
    case "error":
      return { type: "error", code: str(payload.error), message: str(payload.message) };
    default:
      return null;
  }
}

/** Map an SSE `error` event (or a refusal's error code) onto what the UI shows. */
export function failureFromCode(code: string): ChatFailure {
  switch (code) {
    case "timeout":
      return "timeout";
    case "assistant_off":
      return "off";
    case "assistant_busy":
      return "busy";
    case "rate_limited":
      return "rate_limited";
    default:
      return "unavailable";
  }
}

/** Map a refusal status (before any streaming) onto a failure. `code` is the JSON `error`, if the body had one. */
export function failureFromStatus(status: number, code?: string): ChatFailure {
  if (status === 413 || status === 422) return "too_long";
  if (status === 429) return "rate_limited";
  if (status === 503) return code ? failureFromCode(code) : "unavailable";
  return "unavailable";
}

/** The conversation as the server accepts it: at most 20 turns, starting with the user's. */
export function conversationPayload(turns: Turn[]): Turn[] {
  const tail = turns.slice(-MAX_TURNS);
  const first = tail.findIndex((t) => t.role === "user");
  return first === -1 ? [] : tail.slice(first);
}

/** True when the conversation is at the server's limit and the user should start a new one. */
export function conversationFull(turns: Turn[]): boolean {
  return turns.length >= MAX_TURNS;
}

export interface ChatHandlers {
  onTool(name: string): void;
  onAnswer(text: string): void;
}

/**
 * Send the conversation and stream the reply into `handlers`. Resolves with `null` when an answer
 * arrived, or the failure. A user abort resolves with `"aborted"`. Never throws.
 */
export async function sendChat(
  turns: Turn[],
  handlers: ChatHandlers,
  signal: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): Promise<ChatFailure | "aborted" | null> {
  const ctl = new AbortController();
  let timedOut = false;
  const onAbort = () => ctl.abort();
  if (signal.aborted) return "aborted";
  signal.addEventListener("abort", onAbort);
  const timer = setTimeout(() => {
    timedOut = true;
    ctl.abort();
  }, CLIENT_TIMEOUT_MS);
  try {
    const res = await fetchImpl("/api/assistant/chat", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      signal: ctl.signal,
      headers: {
        "Content-Type": "application/json",
        "X-Requested-With": "finance-app",
        Accept: "text/event-stream",
        ...tenantHeaders(),
      },
      body: JSON.stringify({ messages: conversationPayload(turns) }),
    });
    if (res.status === 401) {
      unauthenticated();
      return "unavailable";
    }
    if (!res.ok || !res.body) {
      let code: string | undefined;
      try {
        code = ((await res.json()) as { error?: string }).error;
      } catch {
        // A gateway page, not our JSON: treated as unavailable.
      }
      return failureFromStatus(res.status, code);
    }
    const parse = createSseParser();
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let answered = false;
    for (;;) {
      const { done, value } = await reader.read();
      const events = parse(done ? decoder.decode() + "\n\n" : decoder.decode(value, { stream: true }));
      for (const ev of events) {
        if (ev.type === "tool") handlers.onTool(ev.name);
        else if (ev.type === "answer") {
          answered = true;
          handlers.onAnswer(ev.text);
        } else if (ev.type === "error") return answered ? null : failureFromCode(ev.code);
      }
      if (done) break;
    }
    return answered ? null : "unavailable";
  } catch {
    if (timedOut) return "timeout";
    if (signal.aborted) return "aborted";
    return "unavailable";
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", onAbort);
  }
}

// --- Conversation state (in memory only) ---------------------------------------------------

export interface ChatState {
  turns: Turn[];
  /** A request is in flight: send is disabled, stop is offered. */
  waiting: boolean;
  /** The tool running now, as a name; null between tools. */
  tool: string | null;
  /** Why the last request failed (shown under the conversation), if it did. */
  failure: Exclude<ChatFailure, "off"> | null;
  /** The text of a turn that got no answer, handed back to the input so nothing typed is lost. */
  draft: string;
}

export type ChatAction =
  | { type: "send"; text: string }
  | { type: "tool"; name: string }
  | { type: "answer"; text: string }
  | { type: "fail"; failure: ChatFailure | "aborted" }
  | { type: "finish" }
  | { type: "reset" };

export const initialChat: ChatState = { turns: [], waiting: false, tool: null, failure: null, draft: "" };

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "send": {
      const text = action.text.trim().slice(0, MAX_CHARS);
      if (state.waiting || !text) return state;
      return { turns: [...state.turns, { role: "user", content: text }], waiting: true, tool: null, failure: null, draft: "" };
    }
    case "tool":
      return state.waiting ? { ...state, tool: action.name } : state;
    case "answer":
      return { ...state, turns: [...state.turns, { role: "assistant", content: action.text }], tool: null };
    case "fail": {
      // The unanswered question goes back to the input; the transcript ends on the last answer.
      const last = state.turns[state.turns.length - 1];
      const unanswered = last?.role === "user";
      return {
        ...state,
        turns: unanswered ? state.turns.slice(0, -1) : state.turns,
        waiting: false,
        tool: null,
        draft: unanswered ? last.content : "",
        failure: action.failure === "aborted" || action.failure === "off" ? null : action.failure,
      };
    }
    case "finish":
      return { ...state, waiting: false, tool: null };
    case "reset":
      return initialChat;
  }
}

// --- Availability ---------------------------------------------------------------------------
// The backend has no probe endpoint. The chat is offered, and the first `assistant_off` hides it
// for the rest of the browser session (sessionStorage; a new session tries once more).

const OFF_KEY = "plangram_assistant_off";
const listeners = new Set<() => void>();
let off = readOff();

function readOff(): boolean {
  try {
    return typeof sessionStorage !== "undefined" && sessionStorage.getItem(OFF_KEY) === "1";
  } catch {
    return false;
  }
}

export function assistantOff(): boolean {
  return off;
}

export function markAssistantOff(): void {
  off = true;
  try {
    sessionStorage.setItem(OFF_KEY, "1");
  } catch {
    // Storage blocked: the flag lasts until the page reloads.
  }
  for (const l of listeners) l();
}

export function subscribeAssistant(l: () => void): () => void {
  listeners.add(l);
  return () => void listeners.delete(l);
}

/** Test hook: forget the off flag. */
export function resetAssistantOff(): void {
  off = false;
  try {
    sessionStorage.removeItem(OFF_KEY);
  } catch {
    // ignore
  }
  for (const l of listeners) l();
}

// --- Answer text, bidi-safe -----------------------------------------------------------------

export interface Segment {
  text: string;
  /** Render inside a left-to-right isolate (numbers, amounts, Latin words). */
  ltr: boolean;
}

// An amount/number/percent/date (optionally signed, with ₪ either side) or a Latin word run.
const SIGN = String.raw`(?:(?<![\p{L}\d])[-−])?`;
const LTR_RUN = new RegExp(
  `${SIGN}(?:₪\\s?)?\\d[\\d,.:/-]*\\d(?:\\s?[%₪])?|${SIGN}(?:₪\\s?)?\\d(?:\\s?[%₪])?|[A-Za-z][A-Za-z0-9_.&'-]*(?:\\s[A-Za-z][A-Za-z0-9_.&'-]*)*`,
  "gu",
);

/** Split an answer line so each number, amount or Latin run can be wrapped in `<bdi dir="ltr">`. */
export function bidiSegments(text: string): Segment[] {
  const out: Segment[] = [];
  let at = 0;
  for (const m of text.matchAll(LTR_RUN)) {
    if (m.index > at) out.push({ text: text.slice(at, m.index), ltr: false });
    out.push({ text: m[0], ltr: true });
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push({ text: text.slice(at), ltr: false });
  return out;
}
