// Typed client for the ledger API (docs/ledger-api.md, "Contract"). The API lives
// behind the same CloudFront host as the app (`/api/*`), so every call is
// same-origin and the Cognito session cookie rides along automatically.

/** One ledger transaction as the API returns it (effective values + scraped baseline). */
export interface Row {
  /** ISO date, e.g. "2026-01-15". */
  date: string;
  /** Absolute amount as a 2-decimal string, e.g. "123.45". With `date`, the transaction's key. */
  abs_amount: string;
  /** Signed ₪: money out is negative. */
  amount: number;
  description: string;
  /** Effective category (override if present, else scraped). */
  category: string;
  scraped_category: string;
  note: string | null;
  excluded: boolean;
  /** True when a manual override exists for this transaction. */
  overridden: boolean;
  origin: string;
  sources: string[];
  /** Effective horizon bucket (override if present, else the rule's pick); null when unclassified. */
  horizon?: Horizon | null;
  /** What the horizon rules picked before any override. */
  scraped_horizon?: Horizon | null;
  /** Tag names on this transaction, sorted. */
  tags?: string[];
}

/** A tag in the `tags` table, with how many transactions carry it. */
export interface Tag {
  id: number;
  name: string;
  /** "#rrggbb", or null for the default chip colour. */
  color: string | null;
  count: number;
}

/** Whose money a transaction serves: current me, near-future me, or future (retirement) me. */
export type Horizon = "current" | "near" | "future";

/** The editable fields. `null` clears that field's override. */
export interface RowPatch {
  category?: string | null;
  note?: string | null;
  excluded?: boolean;
  horizon?: Horizon | null;
}

export interface Health {
  ok: boolean;
  db: boolean;
  temporal: boolean;
  /** True when the API runs with the dev auth bypass (FINANCE_API_DEV_USER). */
  dev?: boolean;
}

export type RebuildState = "idle" | "pending" | "running";

export interface RebuildStatus {
  state: RebuildState;
  last_published_at: string | null;
  last_error: string | null;
}

export interface OrphanedOverride {
  date: string;
  abs_amount: string;
  category: string | null;
  note: string | null;
  excluded: boolean;
}

export interface AuditEntry {
  at: string;
  actor: string;
  date: string;
  abs_amount: string;
  field: string;
  old: unknown;
  new: unknown;
}

export interface ListQuery {
  from?: string;
  to?: string;
  /** "include" returns hidden rows too, "only" returns just the hidden ones; default hides them. */
  excluded?: "include" | "only";
}

/** The API (or the home computer behind it) can't be reached: the UI falls back to read-only. */
export class ApiOffline extends Error {
  constructor(reason: string) {
    super(`ledger API offline: ${reason}`);
    this.name = "ApiOffline";
  }
}

/** The API answered with a structured error (`{"error": code, "message": …}`). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, code: string, message: string) {
    super(message || code);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** Gateway statuses that mean "the origin isn't there" (tunnel down, API stopped). */
const OFFLINE_STATUSES = new Set([502, 503, 504]);

/** The key the API addresses a transaction by: ISO date + absolute amount to 2 decimals. */
export interface LedgerKey {
  date: string;
  abs_amount: string;
}

/**
 * Compute a transaction's API key from a ledger row. Amount sign is ignored and the
 * magnitude is formatted exactly as the server stores it: ledgerKey({date, amount: -123.4})
 * is `{date, abs_amount: "123.40"}`.
 */
export function ledgerKey(row: { date: string; amount: number }): LedgerKey {
  return { date: row.date.slice(0, 10), abs_amount: Math.abs(row.amount).toFixed(2) };
}

/** Stable string form of a key, for Map lookups. */
export function keyId(key: LedgerKey): string {
  return `${key.date}/${key.abs_amount}`;
}

/**
 * Perform one API call and map every failure mode onto a typed error:
 * - network failure, 502/503/504, or a non-JSON body (CloudFront falls back to
 *   index.html when the API origin is missing) -> `ApiOffline`
 * - 401 -> the Cognito session expired; reload so the edge redirects to login
 * - any other non-2xx -> `ApiError` carrying the API's error code and message
 *
 * Writes carry the CSRF headers the API requires (JSON content type plus
 * `X-Requested-With`). `body` is sent as-is, so callers decide which fields exist.
 */
export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method, credentials: "same-origin", headers, cache: "no-store" };
  if (method !== "GET") {
    headers["Content-Type"] = "application/json";
    headers["X-Requested-With"] = "finance-app";
    if (body !== undefined) init.body = JSON.stringify(body);
  }

  let res: Response;
  try {
    res = await fetch(`/api${path}`, init);
  } catch (err) {
    throw new ApiOffline(err instanceof Error ? err.message : "network error");
  }

  if (res.status === 401) {
    globalThis.location.reload();
    throw new ApiError(401, "unauthenticated", "session expired");
  }
  if (OFFLINE_STATUSES.has(res.status)) throw new ApiOffline(`HTTP ${res.status}`);

  if (!res.headers.get("content-type")?.includes("json")) throw new ApiOffline("non-JSON response");
  let data: unknown;
  try {
    data = await res.json();
  } catch {
    throw new ApiOffline("unreadable response");
  }

  if (!res.ok) {
    const e = (data ?? {}) as { error?: string; message?: string };
    throw new ApiError(res.status, e.error ?? `http_${res.status}`, e.message ?? "");
  }
  return data as T;
}

const txPath = (key: LedgerKey) => `/transactions/${encodeURIComponent(key.date)}/${encodeURIComponent(key.abs_amount)}`;

export const getHealth = () => request<Health>("GET", "/health");

export async function listTransactions(q: ListQuery = {}): Promise<Row[]> {
  const params = new URLSearchParams();
  if (q.from) params.set("from", q.from);
  if (q.to) params.set("to", q.to);
  if (q.excluded) params.set("excluded", q.excluded);
  const qs = params.toString();
  return (await request<{ transactions: Row[] }>("GET", `/transactions${qs ? `?${qs}` : ""}`)).transactions;
}

export const getTransaction = (key: LedgerKey) => request<Row>("GET", txPath(key));

/** PATCH only the fields present in `patch`; `null` clears that field's override. */
export const patchTransaction = (key: LedgerKey, patch: RowPatch) => request<Row>("PATCH", txPath(key), patch);

/** Drop the override entirely: the row goes back to its scraped values. */
export const resetTransaction = (key: LedgerKey) => request<Row>("DELETE", `${txPath(key)}/override`);

export async function getCategories(): Promise<string[]> {
  return (await request<{ categories: string[] }>("GET", "/categories")).categories;
}

export async function getTags(): Promise<Tag[]> {
  return (await request<{ tags: Tag[] }>("GET", "/tags")).tags;
}

/** Replace the full set of tags on a transaction; unknown names become new tags. */
export const putTags = (key: LedgerKey, tags: string[]) => request<Row>("PUT", `${txPath(key)}/tags`, { tags });

/** Rename and/or recolour a tag (`color: null` clears it). 409 when the name is taken. */
export const patchTag = (id: number, patch: { name?: string; color?: string | null }) =>
  request<Omit<Tag, "count">>("PATCH", `/tags/${id}`, patch);

/** Delete a tag and remove it from every transaction. */
export const deleteTag = (id: number) => request<{ deleted: number }>("DELETE", `/tags/${id}`);

export async function getOrphanedOverrides(): Promise<OrphanedOverride[]> {
  return (await request<{ overrides: OrphanedOverride[] }>("GET", "/overrides/orphaned")).overrides;
}

export async function getAudit(limit = 50): Promise<AuditEntry[]> {
  return (await request<{ entries: AuditEntry[] }>("GET", `/audit?limit=${limit}`)).entries;
}

export const getRebuild = () => request<RebuildStatus>("GET", "/rebuild");
