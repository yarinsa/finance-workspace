// Tiny external store for app-shell status that several places write and one banner reads:
// "session expired" (data fetch), "new version waiting" (service worker).
import { useSyncExternalStore } from "react";

export interface AppStatus {
  /** The auth cookie lapsed: data fetches get a redirect/HTML instead of JSON, or the API a 401. */
  sessionExpired: boolean;
  /** A new service worker is installed and waiting for the user to accept it. */
  updateReady: boolean;
}

let state: AppStatus = { sessionExpired: false, updateReady: false };
const listeners = new Set<() => void>();

export function setAppStatus(patch: Partial<AppStatus>): void {
  const next = { ...state, ...patch };
  if (next.sessionExpired === state.sessionExpired && next.updateReady === state.updateReady) return;
  state = next;
  listeners.forEach((l) => l());
}

export function getAppStatus(): AppStatus {
  return state;
}

/** Subscribe a component to the shell status. */
export function useAppStatus(): AppStatus {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => void listeners.delete(cb);
    },
    () => state,
  );
}
