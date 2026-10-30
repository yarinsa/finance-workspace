import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiOffline, getHealth, getTransaction, ledgerKey, listTransactions, patchTransaction, resetTransaction } from "./api";
import { getAppStatus, setAppStatus } from "./appStatus";
import { buildPatch } from "./editPatch";
import { graphqlRequest } from "./relay";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

const fetchMock = vi.fn();
const assign = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  assign.mockReset();
  setAppStatus({ sessionExpired: false });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("location", { href: "https://app.test/overview", assign });
});
afterEach(() => vi.unstubAllGlobals());

describe("ledgerKey", () => {
  it("formats the absolute amount to two decimals", () => {
    expect(ledgerKey({ date: "2026-01-15", amount: -123.4 })).toEqual({ date: "2026-01-15", abs_amount: "123.40" });
    expect(ledgerKey({ date: "2026-01-15", amount: 7 }).abs_amount).toBe("7.00");
    expect(ledgerKey({ date: "2026-01-15T00:00:00", amount: -0.005 + 0.1 }).date).toBe("2026-01-15");
  });
});

describe("error mapping", () => {
  it("a 401 never navigates: it goes offline and raises the re-login banner", async () => {
    fetchMock.mockResolvedValue(json({ error: "unauthenticated" }, 401));
    await expect(getHealth()).rejects.toBeInstanceOf(ApiOffline);
    await expect(getHealth()).rejects.toBeInstanceOf(ApiOffline);
    expect(assign).not.toHaveBeenCalled();
    expect(getAppStatus().sessionExpired).toBe(true);
  });

  // The inbox badge's POST /api/graphql on a cold open of the installed iOS app with an
  // expired session navigated to /overview?login=1, left the app's scope and froze it.
  it("a 401 on the inbox's GraphQL call does not navigate either", async () => {
    fetchMock.mockResolvedValue(json({ error: "unauthenticated" }, 401));
    await expect(graphqlRequest({ params: { name: "InboxNotifications", text: "query InboxNotifications { notifications { edges { node { id } } } }" } } as never, {})).rejects.toBeInstanceOf(ApiOffline);
    expect(assign).not.toHaveBeenCalled();
    expect(getAppStatus().sessionExpired).toBe(true);
  });

  it.each([502, 503, 504])("treats %i as offline", async (status) => {
    fetchMock.mockResolvedValue(json({ error: "x" }, status));
    await expect(getHealth()).rejects.toBeInstanceOf(ApiOffline);
  });

  it("treats a network error as offline", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(getHealth()).rejects.toBeInstanceOf(ApiOffline);
  });

  it("treats an index.html fallback as offline", async () => {
    fetchMock.mockResolvedValue(new Response("<!doctype html>", { status: 200, headers: { "content-type": "text/html" } }));
    await expect(getHealth()).rejects.toBeInstanceOf(ApiOffline);
  });

  it("surfaces API errors with their code", async () => {
    fetchMock.mockResolvedValue(json({ error: "not_found", message: "no such row" }, 404));
    await expect(getTransaction({ date: "2026-01-15", abs_amount: "1.00" })).rejects.toMatchObject({
      status: 404,
      code: "not_found",
    });
  });
});

describe("requests", () => {
  it("sends same-origin credentials and no CSRF headers on reads", async () => {
    fetchMock.mockResolvedValue(json({ transactions: [] }));
    await listTransactions({ excluded: "only" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/transactions?excluded=only");
    expect(init.credentials).toBe("same-origin");
    expect(init.headers["X-Requested-With"]).toBeUndefined();
  });

  it("PATCH sends only the given fields plus the CSRF headers", async () => {
    fetchMock.mockResolvedValue(json({ date: "2026-01-15" }));
    await patchTransaction({ date: "2026-01-15", abs_amount: "123.40" }, { note: "הערה" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/transactions/2026-01-15/123.40");
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body)).toEqual({ note: "הערה" });
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.headers["X-Requested-With"]).toBe("finance-app");
  });

  it("DELETE targets the override resource", async () => {
    fetchMock.mockResolvedValue(json({}));
    await resetTransaction({ date: "2026-01-15", abs_amount: "123.40" });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/transactions/2026-01-15/123.40/override");
    expect(fetchMock.mock.calls[0][1].method).toBe("DELETE");
  });
});

describe("buildPatch", () => {
  const base = { category: "מסעדות", note: null, excluded: false };

  it("sends goal_id only when the goal changes, and null to unassign", () => {
    const f = { category: "מסעדות", note: "", excluded: false };
    expect(buildPatch(base, { ...f, goal_id: 3 })).toEqual({ goal_id: 3 });
    expect(buildPatch({ ...base, goal_id: 3 }, { ...f, goal_id: 3 })).toEqual({});
    expect(buildPatch({ ...base, goal_id: 3 }, { ...f, goal_id: null })).toEqual({ goal_id: null });
    expect(buildPatch({ ...base, goal_id: 3 }, f)).toEqual({});
  });

  it("contains only the changed fields", () => {
    expect(buildPatch(base, { category: "מסעדות", note: "", excluded: false })).toEqual({});
    expect(buildPatch(base, { category: "קפה", note: "", excluded: false })).toEqual({ category: "קפה" });
    expect(buildPatch(base, { category: "מסעדות", note: " ארוחה ", excluded: true })).toEqual({
      note: "ארוחה",
      excluded: true,
    });
  });

  it("clears a field with null when the input is emptied", () => {
    expect(buildPatch({ category: "קפה", note: "x", excluded: true }, { category: "", note: "", excluded: true })).toEqual({
      category: null,
      note: null,
    });
  });

  it("sets a horizon and clears only a real override", () => {
    const h = { ...base, horizon: "current" as const, scraped_horizon: "current" as const };
    expect(buildPatch(h, { category: "מסעדות", note: "", excluded: false, horizon: "future" })).toEqual({ horizon: "future" });
    expect(buildPatch(h, { category: "מסעדות", note: "", excluded: false, horizon: "clear" })).toEqual({});
    expect(
      buildPatch({ ...h, horizon: "near" }, { category: "מסעדות", note: "", excluded: false, horizon: "clear" }),
    ).toEqual({ horizon: null });
  });
});
