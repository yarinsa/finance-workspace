// The tenant the app is acting in (docs/tenancy.md).
//
// A user with one tenant never needs this: no header is sent, data comes from /data/<name>.json,
// and the API picks their only tenant. A user with several chooses one; it is remembered in
// localStorage and sent as `X-Tenant-Id` on every /api call (the live stream names it in the query
// string, since EventSource cannot set headers). Another tenant's published files live under
// /data/t/<id>/, which the edge serves only to that tenant's members. The master tenant keeps the
// old /data/ paths.
//
// Switching reloads the page. Everything the app holds in memory (the data modules, the Relay
// store, the inbox and sync streams) belongs to one tenant, so a reload is the one way to be sure
// none of it leaks across; the service worker caches by URL and the URLs differ per tenant.

/** The tenant that holds the household's original data; its files keep the un-prefixed paths. */
export const MASTER_TENANT_ID = "00000000-0000-4000-8000-000000000001";
const KEY = "plangram_tenant";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export interface MyTenant {
  id: string;
  slug: string;
  name: string;
  role: "owner" | "admin" | "member";
}

export interface Me {
  email: string;
  platform_admin: boolean;
  tenants: MyTenant[];
}

function storage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null; // storage blocked (private mode): act as the user's only tenant
  }
}

/** The remembered tenant id, or null (use the API's default). Anything not a uuid is ignored. */
export function activeTenantId(): string | null {
  const v = storage()?.getItem(KEY) ?? null;
  return v && UUID.test(v) ? v : null;
}

/** Headers to add to every /api request. */
export function tenantHeaders(): Record<string, string> {
  const id = activeTenantId();
  return id ? { "X-Tenant-Id": id } : {};
}

/** `/data/<name>.json` for the master tenant (or no choice), `/data/t/<id>/<name>.json` for another. */
export function dataUrl(name: string): string {
  const id = activeTenantId();
  return id && id !== MASTER_TENANT_ID ? `/data/t/${id}/${name}.json` : `/data/${name}.json`;
}

/** `?tenant=<id>` for URLs that cannot carry a header (EventSource), else "". */
export function tenantQuery(): string {
  const id = activeTenantId();
  return id ? `tenant=${id}` : "";
}

/** Remember `id` and reload: no data, store or stream of the previous tenant survives. */
export function switchTenant(id: string, reload: () => void = () => location.reload()): void {
  if (!UUID.test(id)) throw new Error("not a tenant id");
  storage()?.setItem(KEY, id);
  reload();
}

/** Forget a choice that no longer matches a membership (removed from the tenant, or it is suspended). */
export function clearTenant(): void {
  storage()?.removeItem(KEY);
}

/** The tenant to show as current among `me.tenants`: the remembered one if still a member, else the first. */
export function currentTenant(me: Me): MyTenant | null {
  return me.tenants.find((t) => t.id === activeTenantId()) ?? me.tenants[0] ?? null;
}
