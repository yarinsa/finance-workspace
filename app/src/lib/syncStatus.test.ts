import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { __store, __resetSyncStatusForTests, MAX_SSE_ERRORS, SSE_RETRY_MS, type SourceStatus, type SyncStatusDoc } from "./syncStatus";

class FakeEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;
  static instances: FakeEventSource[] = [];
  readyState = 0;
  onerror: (() => void) | null = null;
  handlers: Record<string, (e: MessageEvent) => void> = {};
  closed = false;
  constructor(public url: string, public init?: EventSourceInit) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(name: string, fn: (e: MessageEvent) => void) {
    this.handlers[name] = fn;
  }
  close() {
    this.closed = true;
    this.readyState = 2;
  }
  emit(name: string, data: unknown) {
    this.handlers[name]?.({ data: JSON.stringify(data) } as MessageEvent);
  }
}

const entry = (status: SourceStatus["status"], updated_at: string): SourceStatus => ({
  status,
  message: "",
  step: null,
  total_steps: 5,
  workflow_id: "w",
  run_id: "r",
  started_at: updated_at,
  updated_at,
  last_success_at: null,
  error: null,
});

const snap = (): SyncStatusDoc => ({ updated_at: "2026-10-26T10:00:00Z", sources: { cal: entry("done", "2026-10-26T10:00:00Z") } });

const fakeDoc = Object.assign(new EventTarget(), { hidden: false });
function setHidden(h: boolean) {
  fakeDoc.hidden = h;
  fakeDoc.dispatchEvent(new Event("visibilitychange"));
}

let fetchMock: ReturnType<typeof vi.fn>;
const current = () => FakeEventSource.instances[FakeEventSource.instances.length - 1];

/** Subscribe like useSyncExternalStore does; `act` just flushes microtasks. */
async function subscribeAndRead() {
  const unsub = __store.subscribe(() => {});
  return {
    get: () => __store.get(),
    act: async (fn: () => unknown | Promise<unknown>) => {
      await fn();
      await Promise.resolve();
    },
    unmount: async () => unsub(),
  };
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  fetchMock = vi.fn(async () => ({ ok: true, headers: { get: () => "application/json" }, json: async () => snap() }));
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("document", fakeDoc);
  setHidden(false);
  __resetSyncStatusForTests();
});

afterEach(() => {
  __resetSyncStatusForTests();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("sync status over SSE", () => {
  it("opens the stream with credentials and replaces the doc on snapshot", async () => {
    const r = await subscribeAndRead();
    expect(current().url).toBe("/api/sync/events");
    expect(current().init).toEqual({ withCredentials: true });
    await r.act(async () => current().emit("snapshot", snap()));
    expect(r.get()).toEqual(snap());
    const next = { updated_at: "t2", sources: { leumi: entry("failed", "t2") } };
    await r.act(async () => current().emit("snapshot", next));
    expect(r.get()).toEqual(next);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("merges a source event and bumps updated_at", async () => {
    const r = await subscribeAndRead();
    await r.act(async () => current().emit("snapshot", snap()));
    const e = entry("scraping", "2026-10-26T10:05:00Z");
    await r.act(async () => current().emit("source", { source: "leumi", entry: e }));
    expect(r.get()?.sources.cal.status).toBe("done");
    expect(r.get()?.sources.leumi).toEqual(e);
    expect(r.get()?.updated_at).toBe(e.updated_at);
  });

  it("falls back to polling S3 after 3 errors without a snapshot, and retries SSE", async () => {
    const r = await subscribeAndRead();
    for (let i = 0; i < MAX_SSE_ERRORS; i++) await r.act(async () => current().onerror?.());
    expect(current().closed).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(r.get()).toEqual(snap());
    await r.act(async () => {
      await vi.advanceTimersByTimeAsync(SSE_RETRY_MS);
    });
    expect(FakeEventSource.instances.length).toBe(2);
    // A snapshot ends polling.
    const calls = fetchMock.mock.calls.length;
    await r.act(async () => current().emit("snapshot", snap()));
    await r.act(async () => {
      await vi.advanceTimersByTimeAsync(5 * SSE_RETRY_MS);
    });
    expect(fetchMock.mock.calls.length).toBe(calls);
  });

  it("does not fall back when a snapshot arrives between errors", async () => {
    const r = await subscribeAndRead();
    await r.act(async () => current().onerror?.());
    await r.act(async () => current().onerror?.());
    await r.act(async () => current().emit("snapshot", snap()));
    await r.act(async () => current().onerror?.());
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("falls back at once when the stream is CLOSED", async () => {
    const r = await subscribeAndRead();
    current().readyState = 2;
    await r.act(async () => current().onerror?.());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("closes the stream when the tab is hidden and reopens when visible", async () => {
    const r = await subscribeAndRead();
    const first = current();
    await r.act(async () => setHidden(true));
    expect(first.closed).toBe(true);
    await r.act(async () => setHidden(false));
    expect(FakeEventSource.instances.length).toBe(2);
    expect(current().closed).toBe(false);
  });

  it("closes everything when the last listener goes", async () => {
    const r = await subscribeAndRead();
    const es = current();
    await r.unmount();
    expect(es.closed).toBe(true);
  });
});
