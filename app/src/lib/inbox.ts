import { useCallback, useMemo, useSyncExternalStore } from "react";
import { cashflow } from "@/lib/data";
import { graphqlRequest } from "@/lib/relay";
import { onNotificationEvent, syncActions, useSyncStatus } from "@/lib/syncStatus";
import {
  badgeCount,
  fromApiNode,
  fromStatic,
  mergeLive,
  tabCategories,
  toGlobalId,
  type ApiNode,
  type Category,
  type LocalState,
  type Notification,
  type TabKey,
} from "@/lib/notifications";

// Where the inbox comes from:
// - API reachable: `notifications` over GraphQL (server owns read/archive/snooze). Live sync
//   alerts are computed in the browser and layered on top; their state stays local.
// - API unreachable (Mac off, old backend, no network): the published `cashflow.actions`
//   with read/archive/snooze kept in localStorage. The archive key predates the API, so
//   old dismissals survive; on reconnect they are pushed up once, best-effort.

const STORAGE_KEY = "plangram.dismissed-actions";
const READ_KEY = "plangram.read-actions";
const SNOOZE_KEY = "plangram.snoozed-actions";
const EVENT = "plangram:inbox";
const REFETCH_DEBOUNCE_MS = 300;
const RETRY_OFFLINE_MS = 60_000;

// --- local state (static fallback + live alerts) -----------------------------------

function readJson<T>(key: string, fallback: T, valid: (v: unknown) => boolean): T {
  try {
    const raw = localStorage.getItem(key);
    const v = raw ? JSON.parse(raw) : fallback;
    return valid(v) ? (v as T) : fallback;
  } catch {
    return fallback;
  }
}

const isIdList = (v: unknown) => Array.isArray(v);
const isRecord = (v: unknown) => v != null && typeof v === "object" && !Array.isArray(v);

function readLocal(): LocalState {
  return {
    archived: readJson<string[]>(STORAGE_KEY, [], isIdList).filter((x) => typeof x === "string"),
    read: readJson<string[]>(READ_KEY, [], isIdList).filter((x) => typeof x === "string"),
    snoozed: readJson<Record<string, string>>(SNOOZE_KEY, {}, isRecord),
  };
}

let local: LocalState = readLocal();
const localListeners = new Set<() => void>();

function writeLocal(next: LocalState) {
  local = next;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next.archived));
    localStorage.setItem(READ_KEY, JSON.stringify(next.read));
    localStorage.setItem(SNOOZE_KEY, JSON.stringify(next.snoozed));
  } catch {
    /* storage unavailable: state lasts for this session only */
  }
  localListeners.forEach((l) => l());
  window.dispatchEvent(new Event(EVENT));
}

function subscribeLocal(l: () => void) {
  localListeners.add(l);
  const sync = () => {
    local = readLocal();
    l();
  };
  window.addEventListener("storage", sync);
  return () => {
    localListeners.delete(l);
    window.removeEventListener("storage", sync);
  };
}

const uniq = (ids: string[]) => [...new Set(ids)];

/** Edit the browser-held state of some ids. */
function patchLocal(ids: string[], patch: { read?: boolean; archived?: boolean; snoozedUntil?: string | null }) {
  const next: LocalState = { archived: local.archived, read: local.read, snoozed: { ...local.snoozed } };
  if (patch.read === true) next.read = uniq([...next.read, ...ids]);
  if (patch.read === false) next.read = next.read.filter((i) => !ids.includes(i));
  if (patch.archived === true) next.archived = uniq([...next.archived, ...ids]);
  if (patch.archived === false) next.archived = next.archived.filter((i) => !ids.includes(i));
  if (patch.snoozedUntil !== undefined) {
    for (const id of ids) {
      if (patch.snoozedUntil) next.snoozed[id] = patch.snoozedUntil;
      else delete next.snoozed[id];
    }
  }
  writeLocal(next);
}

// --- API store ----------------------------------------------------------------------

type ApiStatus = "loading" | "online" | "offline";
interface ApiState {
  status: ApiStatus;
  items: Notification[];
}

const FIELDS = `
  __typename id type category severity title detail amount cta { label to }
  createdAt readAt snoozedUntilAt archivedAt
  ... on CashflowNotification { date }
  ... on BudgetNotification { budgetCategories cycleStart }
  ... on BillNotification { billName dueDate }
  ... on ServiceNotification { services }
  ... on SyncNotification { sources }`;

const LIST_QUERY = `query InboxNotifications($filter: NotificationFilter) {
  notifications(first: 200, filter: $filter) { edges { node { ${FIELDS} } } }
}`;

const UPDATE_MUTATION = `mutation InboxUpdateNotification($input: UpdateNotificationInput!) {
  updateNotification(input: $input) { notification { id } }
}`;
const ARCHIVE_MUTATION = `mutation InboxArchiveNotification($input: NotificationIdInput!) {
  archiveNotification(input: $input) { notification { id } }
}`;
const UNARCHIVE_MUTATION = `mutation InboxUnarchiveNotification($input: NotificationIdInput!) {
  unarchiveNotification(input: $input) { notification { id } }
}`;
const MARK_ALL_MUTATION = `mutation InboxMarkAllRead($input: BulkNotificationInput!) {
  markAllNotificationsRead(input: $input) { count }
}`;

let state: ApiState = { status: "loading", items: [] };
const apiListeners = new Set<() => void>();
let debounce: ReturnType<typeof setTimeout> | undefined;
let retry: ReturnType<typeof setTimeout> | undefined;
let pushedLocal = false;
let stopApi: (() => void) | undefined;

function setState(next: ApiState) {
  state = next;
  apiListeners.forEach((l) => l());
}

async function refetch() {
  try {
    const data = await graphqlRequest<{ notifications: { edges: { node: ApiNode }[] } }>(LIST_QUERY, {
      filter: { includeArchived: true },
    });
    setState({ status: "online", items: data.notifications.edges.map((e) => fromApiNode(e.node)) });
    clearTimeout(retry);
    void pushLocalArchives();
  } catch {
    // Offline, signed out, or a backend without notifications: serve the static fallback.
    setState({ status: "offline", items: [] });
    clearTimeout(retry);
    if (apiListeners.size) retry = setTimeout(() => void refetch(), RETRY_OFFLINE_MS);
  }
}

/** Items archived while offline are archived on the server once it is reachable (once per page load). */
async function pushLocalArchives() {
  if (pushedLocal) return;
  pushedLocal = true;
  const open = new Set(state.items.filter((n) => !n.archivedAt).map((n) => n.id));
  const ids = local.archived.filter((id) => open.has(id));
  if (!ids.length) return;
  await Promise.allSettled(ids.map((id) => graphqlRequest(ARCHIVE_MUTATION, { input: { id: toGlobalId(id) } })));
  void refetch();
}

function scheduleRefetch() {
  clearTimeout(debounce);
  debounce = setTimeout(() => void refetch(), REFETCH_DEBOUNCE_MS);
}

function subscribeApi(l: () => void) {
  apiListeners.add(l);
  if (apiListeners.size === 1) {
    void refetch();
    const unEvent = onNotificationEvent(scheduleRefetch);
    const onVisible = () => !document.hidden && scheduleRefetch();
    window.addEventListener("focus", scheduleRefetch);
    document.addEventListener("visibilitychange", onVisible);
    stopApi = () => {
      unEvent();
      window.removeEventListener("focus", scheduleRefetch);
      document.removeEventListener("visibilitychange", onVisible);
      clearTimeout(debounce);
      clearTimeout(retry);
    };
  }
  return () => {
    apiListeners.delete(l);
    if (!apiListeners.size) {
      stopApi?.();
      stopApi = undefined;
    }
  };
}

/** Optimistically edit API items; the next refetch (SSE or a failed mutation) reconciles. */
function patchItems(ids: string[], patch: Partial<Pick<Notification, "readAt" | "archivedAt" | "snoozedUntilAt">>) {
  setState({ ...state, items: state.items.map((n) => (ids.includes(n.id) ? { ...n, ...patch } : n)) });
}

async function mutate(query: string, input: Record<string, unknown>) {
  try {
    await graphqlRequest(query, { input });
  } catch {
    void refetch();
  }
}

// --- the hook ----------------------------------------------------------------------

export interface Inbox {
  /** Every item, archived and snoozed included; use `openItems` / `isArchived` to split. */
  items: Notification[];
  /** False until we know whether the API answers. */
  ready: boolean;
  /** Server-backed (true) or the static fallback (false). */
  online: boolean;
  markRead: (n: Notification, read?: boolean) => void;
  archive: (n: Notification) => void;
  unarchive: (n: Notification) => void;
  snooze: (n: Notification, until: string) => void;
  /** Mark everything in `tab` read (`items` = what the tab shows, for the live / offline ones). */
  markAllRead: (tab: TabKey, items: Notification[]) => void;
}

/** The inbox: API items when reachable, else the static fallback, plus live sync alerts. */
export function useInbox(): Inbox {
  const syncDoc = useSyncStatus();
  const api = useSyncExternalStore(subscribeApi, () => state);
  const loc = useSyncExternalStore(subscribeLocal, () => local);

  const items = useMemo(() => {
    const live = syncActions(syncDoc);
    return api.status === "online" ? mergeLive(live, api.items, loc) : fromStatic(live, cashflow.actions, loc);
  }, [syncDoc, api, loc]);

  const online = api.status === "online";
  const isLocal = useCallback((n: Notification) => n.live || !online, [online]);

  const markRead = useCallback(
    (n: Notification, read = true) => {
      if (isLocal(n)) return patchLocal([n.id], { read });
      patchItems([n.id], { readAt: read ? new Date().toISOString() : null });
      void mutate(UPDATE_MUTATION, { id: toGlobalId(n.id), read });
    },
    [isLocal],
  );
  const archive = useCallback(
    (n: Notification) => {
      if (isLocal(n)) return patchLocal([n.id], { archived: true });
      patchItems([n.id], { archivedAt: new Date().toISOString() });
      void mutate(ARCHIVE_MUTATION, { id: toGlobalId(n.id) });
    },
    [isLocal],
  );
  const unarchive = useCallback(
    (n: Notification) => {
      if (isLocal(n)) return patchLocal([n.id], { archived: false });
      patchItems([n.id], { archivedAt: null });
      void mutate(UNARCHIVE_MUTATION, { id: toGlobalId(n.id) });
    },
    [isLocal],
  );
  const snooze = useCallback(
    (n: Notification, until: string) => {
      if (isLocal(n)) return patchLocal([n.id], { snoozedUntil: until });
      patchItems([n.id], { snoozedUntilAt: until });
      void mutate(UPDATE_MUTATION, { id: toGlobalId(n.id), snoozedUntilAt: until });
    },
    [isLocal],
  );
  const markAllRead = useCallback(
    (tab: TabKey, shown: Notification[]) => {
      const localIds = shown.filter(isLocal).map((n) => n.id);
      if (localIds.length) patchLocal(localIds, { read: true });
      if (!online) return;
      const now = new Date().toISOString();
      patchItems(
        shown.filter((n) => !n.live).map((n) => n.id),
        { readAt: now },
      );
      const category: Category[] | undefined = tabCategories(tab);
      void mutate(MARK_ALL_MUTATION, category ? { category } : {});
    },
    [isLocal, online],
  );

  return { items, ready: api.status !== "loading", online, markRead, archive, unarchive, snooze, markAllRead };
}

/** Unread PROBLEM + WARNING items, for the badge. */
export function useInboxCount(): number {
  return badgeCount(useInbox().items);
}
