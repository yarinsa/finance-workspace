import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MASTER_TENANT_ID, activeTenantId, clearTenant, currentTenant, dataUrl, switchTenant, tenantHeaders, tenantQuery,
} from "./tenant";

const A = "aaaaaaaa-0000-4000-8000-00000000000a";

function fakeStorage() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), removeItem: (k: string) => void m.delete(k) };
}

beforeEach(() => vi.stubGlobal("localStorage", fakeStorage()));
afterEach(() => vi.unstubAllGlobals());

describe("tenant choice", () => {
  it("sends nothing and reads the original paths until a tenant is chosen", () => {
    expect(activeTenantId()).toBeNull();
    expect(tenantHeaders()).toEqual({});
    expect(dataUrl("cashflow")).toBe("/data/cashflow.json");
    expect(tenantQuery()).toBe("");
  });

  it("another tenant: header, prefixed data path, query for the stream", () => {
    switchTenant(A, () => {});
    expect(tenantHeaders()).toEqual({ "X-Tenant-Id": A });
    expect(dataUrl("snapshot")).toBe(`/data/t/${A}/snapshot.json`);
    expect(tenantQuery()).toBe(`tenant=${A}`);
  });

  it("the master tenant keeps /data/<name>.json but still sends the header", () => {
    switchTenant(MASTER_TENANT_ID, () => {});
    expect(dataUrl("goals")).toBe("/data/goals.json");
    expect(tenantHeaders()).toEqual({ "X-Tenant-Id": MASTER_TENANT_ID });
  });

  it("switching reloads, so nothing of the old tenant stays in memory", () => {
    const reload = vi.fn();
    switchTenant(A, reload);
    expect(reload).toHaveBeenCalledOnce();
  });

  it("refuses anything that is not a uuid (it becomes a path and a header)", () => {
    expect(() => switchTenant("../../etc", () => {})).toThrow();
    localStorage.setItem("plangram_tenant", "../x");
    expect(activeTenantId()).toBeNull();
    expect(dataUrl("cashflow")).toBe("/data/cashflow.json");
  });

  it("a stale choice falls back to the first membership", () => {
    switchTenant(A, () => {});
    const me = { email: "x@y.z", platform_admin: false, tenants: [{ id: MASTER_TENANT_ID, slug: "default", name: "Default", role: "owner" as const }] };
    expect(currentTenant(me)?.id).toBe(MASTER_TENANT_ID);
    clearTenant();
    expect(activeTenantId()).toBeNull();
  });
});
