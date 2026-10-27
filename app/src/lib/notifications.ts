// Pure model of the notifications inbox: the shape both the API (GraphQL `Notification`)
// and the static fallback (`cashflow.actions` + live sync alerts) are mapped onto, plus
// tab filtering, snooze targets and the global-id encoding. No React, no I/O (see ./inbox.ts).
import type { HomeAction } from "./data";

export type Category = "PROBLEM" | "WARNING" | "REMINDER" | "SUGGESTION" | "INFO";
export type Severity = HomeAction["severity"];

/** Per-subtype facts behind the small detail chip (GraphQL inline fragments / `subject`). */
export type Detail =
  | { kind: "cashflow"; date: string | null }
  | { kind: "budget"; categories: string[]; cycleStart: string | null }
  | { kind: "bill"; billName: string; dueDate: string | null }
  | { kind: "service"; services: string[] }
  | { kind: "sync"; sources: string[] }
  | { kind: "transaction" };

export interface Notification {
  id: string;
  type: string;
  category: Category;
  severity: Severity;
  title: string;
  detail: string | null;
  amount: number | null;
  cta: { label: string; to: string } | null;
  /** ISO timestamps; null when the source (static JSON) doesn't carry them. */
  createdAt: string | null;
  readAt: string | null;
  snoozedUntilAt: string | null;
  archivedAt: string | null;
  subject: Detail | null;
  /** Computed in the browser (sync alerts): its state lives in localStorage, never on the server. */
  live: boolean;
}

/** Per-id state kept in the browser for static items and live sync alerts. */
export interface LocalState {
  archived: string[];
  read: string[];
  /** id -> ISO time until which the item is hidden. */
  snoozed: Record<string, string>;
}

export const NO_LOCAL: LocalState = { archived: [], read: [], snoozed: {} };

/** Category for data published before the pipeline emitted one. */
export function categoryOf(a: Pick<HomeAction, "severity" | "category">): Category {
  if (a.category) return a.category;
  if (a.severity === "critical") return "PROBLEM";
  if (a.severity === "low") return "SUGGESTION";
  return "WARNING";
}

/** Global node id the API uses: base64url("<Type>:<id>") without padding (api/relay to_global_id). */
export function toGlobalId(id: string | number, type = "Notification"): string {
  const bytes = new TextEncoder().encode(`${type}:${id}`);
  let bin = "";
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

/** Inverse of `toGlobalId` for ids of the given type; null for anything else. */
export function fromGlobalId(globalId: string, type = "Notification"): string | null {
  try {
    const b64 = globalId.replaceAll("-", "+").replaceAll("_", "/");
    const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
    const text = new TextDecoder().decode(Uint8Array.from(bin, (c) => c.charCodeAt(0)));
    return text.startsWith(`${type}:`) ? text.slice(type.length + 1) : null;
  } catch {
    return null;
  }
}

const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);

/** The pipeline's `subject` object -> detail chip facts. Unknown kinds give null. */
export function detailFromSubject(subject: HomeAction["subject"]): Detail | null {
  if (!subject) return null;
  switch (subject.kind) {
    case "cashflow":
      return { kind: "cashflow", date: str(subject.date) };
    case "budget":
      return { kind: "budget", categories: strs(subject.categories ?? subject.budgetCategories), cycleStart: str(subject.cycleStart) };
    case "bill":
      return { kind: "bill", billName: str(subject.billName ?? subject.name) ?? "", dueDate: str(subject.dueDate) };
    case "service":
      return { kind: "service", services: strs(subject.services) };
    case "sync":
      return { kind: "sync", sources: strs(subject.sources) };
    case "transaction":
      return { kind: "transaction" };
    default:
      return null;
  }
}

/** A static action (published JSON or live sync alert) as a Notification, with the browser's own read/archive/snooze state. */
export function fromAction(a: HomeAction, local: LocalState = NO_LOCAL, live = false): Notification {
  return {
    id: a.id,
    type: a.type ?? "generic",
    category: live ? "PROBLEM" : categoryOf(a),
    severity: a.severity,
    title: a.title,
    detail: a.detail || null,
    amount: a.amount,
    cta: a.cta,
    createdAt: null,
    readAt: local.read.includes(a.id) ? "local" : null,
    snoozedUntilAt: local.snoozed[a.id] ?? null,
    archivedAt: local.archived.includes(a.id) ? "local" : null,
    subject: detailFromSubject(a.subject),
    live,
  };
}

/** Live sync alerts first (they block fresh numbers), then the rest, each group keeping its order. */
export function fromStatic(live: HomeAction[], published: HomeAction[] | undefined, local: LocalState): Notification[] {
  return [...live.map((a) => fromAction(a, local, true)), ...(published ?? []).map((a) => fromAction(a, local))];
}

/** Layer the browser's state over live sync alerts that sit on top of API items. */
export function mergeLive(live: HomeAction[], api: Notification[], local: LocalState): Notification[] {
  return [...live.map((a) => fromAction(a, local, true)), ...api];
}

/** True while a snooze is still running. */
export const isSnoozed = (n: Pick<Notification, "snoozedUntilAt">, now = Date.now()) =>
  n.snoozedUntilAt != null && new Date(n.snoozedUntilAt).getTime() > now;

export const isArchived = (n: Pick<Notification, "archivedAt">) => n.archivedAt != null;
export const isUnread = (n: Pick<Notification, "readAt">) => n.readAt == null;

/** Items shown in the main list: not archived, not snoozed. */
export function openItems(list: Notification[], now = Date.now()): Notification[] {
  return list.filter((n) => !isArchived(n) && !isSnoozed(n, now));
}

export type TabKey = "all" | "problems" | "warnings" | "reminders" | "suggestions";

export const TABS: { key: TabKey; label: string; category: Category | null }[] = [
  { key: "all", label: "הכל", category: null },
  { key: "problems", label: "בעיות", category: "PROBLEM" },
  { key: "warnings", label: "אזהרות", category: "WARNING" },
  { key: "reminders", label: "תזכורות", category: "REMINDER" },
  { key: "suggestions", label: "הצעות", category: "SUGGESTION" },
];

/** `?tab=` value -> tab; anything unknown is "all". */
export function parseTab(v: string | null): TabKey {
  return TABS.find((t) => t.key === v)?.key ?? "all";
}

/** Items of one tab ("all" includes INFO, which has no tab of its own). */
export function inTab(list: Notification[], tab: TabKey): Notification[] {
  const category = TABS.find((t) => t.key === tab)?.category;
  return category ? list.filter((n) => n.category === category) : list;
}

/** Category filter for the bulk mutations of a tab (undefined = everything). */
export function tabCategories(tab: TabKey): Category[] | undefined {
  const category = TABS.find((t) => t.key === tab)?.category;
  return category ? [category] : undefined;
}

/** Badge: unread, open PROBLEM + WARNING items only. */
export function badgeCount(list: Notification[], now = Date.now()): number {
  return openItems(list, now).filter((n) => isUnread(n) && (n.category === "PROBLEM" || n.category === "WARNING")).length;
}

/** Snooze choices of the sheet: tomorrow 08:00, a week, payday (falls back to a week). */
export type SnoozeChoice = "tomorrow" | "week" | "payday";

export function snoozeUntil(choice: SnoozeChoice, now: Date, payday?: string | null): string {
  const at = new Date(now);
  at.setHours(8, 0, 0, 0);
  if (choice === "tomorrow") {
    at.setDate(at.getDate() + 1);
  } else if (choice === "payday" && payday) {
    const p = new Date(`${payday.slice(0, 10)}T08:00:00`);
    if (!Number.isNaN(p.getTime()) && p.getTime() > now.getTime()) return p.toISOString();
    at.setDate(at.getDate() + 7);
  } else {
    at.setDate(at.getDate() + 7);
  }
  return at.toISOString();
}

// --- API (GraphQL) mapping --------------------------------------------------------

/** Fields every `Notification` selects, plus the per-subtype fragments (see inbox.ts QUERY). */
export interface ApiNode {
  __typename?: string;
  id: string;
  type: string;
  category: Category;
  severity: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  title: string;
  detail: string | null;
  amount: string | null;
  cta: { label: string; to: string } | null;
  createdAt: string;
  readAt: string | null;
  snoozedUntilAt: string | null;
  archivedAt: string | null;
  date?: string | null;
  budgetCategories?: string[];
  cycleStart?: string | null;
  billName?: string;
  dueDate?: string | null;
  services?: string[];
  sources?: string[];
}

/**
 * The node's id is the Relay global id; the client id is the pipeline's action id so that
 * locally archived items and API items line up.
 */
export function fromApiNode(n: ApiNode): Notification {
  const detail = ((): Detail | null => {
    switch (n.__typename) {
      case "CashflowNotification":
        return { kind: "cashflow", date: n.date ?? null };
      case "BudgetNotification":
        return { kind: "budget", categories: n.budgetCategories ?? [], cycleStart: n.cycleStart ?? null };
      case "BillNotification":
        return { kind: "bill", billName: n.billName ?? "", dueDate: n.dueDate ?? null };
      case "ServiceNotification":
        return { kind: "service", services: n.services ?? [] };
      case "SyncNotification":
        return { kind: "sync", sources: n.sources ?? [] };
      case "TransactionNotification":
        return { kind: "transaction" };
      default:
        return null;
    }
  })();
  const amount = n.amount == null ? null : Number(n.amount);
  return {
    id: fromGlobalId(n.id) ?? n.id,
    type: n.type,
    category: n.category,
    severity: n.severity.toLowerCase() as Severity,
    title: n.title,
    detail: n.detail,
    amount: amount != null && Number.isFinite(amount) ? amount : null,
    cta: n.cta,
    createdAt: n.createdAt,
    readAt: n.readAt,
    snoozedUntilAt: n.snoozedUntilAt,
    archivedAt: n.archivedAt,
    subject: detail,
    live: false,
  };
}

const SHORT_DATE = new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "numeric" });
const shortDate = (iso: string | null) => (iso ? SHORT_DATE.format(new Date(iso.slice(0, 10) + "T12:00:00")) : "");

/** Text of the small per-subtype chip under a row; null when there is nothing to add. */
export function detailChip(n: Pick<Notification, "subject">): string | null {
  const s = n.subject;
  if (!s) return null;
  switch (s.kind) {
    case "sync":
      return s.sources.length ? s.sources.join(" · ") : null;
    case "bill":
      return [s.billName, shortDate(s.dueDate)].filter(Boolean).join(" · ") || null;
    case "budget":
      return s.categories.length ? s.categories.join(" · ") : null;
    case "service":
      return s.services.length ? s.services.join(" · ") : null;
    case "cashflow":
      return s.date ? shortDate(s.date) : null;
    default:
      return null;
  }
}
