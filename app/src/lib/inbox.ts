import { useEffect, useState } from "react";
import { cashflow, type HomeAction } from "@/lib/data";
import { syncActions, useSyncStatus } from "@/lib/syncStatus";

const STORAGE_KEY = "plangram.dismissed-actions";
const EVENT = "plangram:inbox";

function readDismissed(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    const v = raw ? JSON.parse(raw) : [];
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

/** Archived inbox item ids, persisted locally and shared by every subscriber (badge + list). */
export function useDismissed(): [string[], (ids: string[]) => void] {
  const [ids, setIds] = useState<string[]>(readDismissed);
  useEffect(() => {
    const sync = () => setIds(readDismissed());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  const update = (next: string[]) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      /* storage unavailable: archiving lasts for this session only */
    }
    setIds(next);
    window.dispatchEvent(new Event(EVENT));
  };
  return [ids, update];
}

/**
 * Inbox items: live sync alerts (login needed, failed) first — they block fresh
 * numbers — then the pipeline's actions. Undefined when neither exists.
 */
export function useInboxActions(): HomeAction[] | undefined {
  const live = syncActions(useSyncStatus());
  return cashflow.actions || live.length ? [...live, ...(cashflow.actions ?? [])] : undefined;
}

/** Number of unarchived inbox items, for the badge. */
export function useInboxCount(): number {
  const actions = useInboxActions() ?? [];
  const [dismissed] = useDismissed();
  return actions.filter((a) => !dismissed.includes(a.id)).length;
}
