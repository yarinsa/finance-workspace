import { useSyncExternalStore } from "react";
import type { SnapshotAsset } from "./data";

/**
 * The apartment's value as just saved, before the rebuild publishes it in snapshot.json.
 * Stamped with the data version it was recorded against (like goalsOverlay): once data has
 * been reloaded past that version, the published snapshot is the truth again.
 */
export interface PropertyOverlay {
  version: number;
  property: Pick<SnapshotAsset, "label" | "value" | "valued_at">;
}

let overlay: PropertyOverlay | null = null;
const listeners = new Set<() => void>();

export function recordProperty(next: PropertyOverlay): void {
  overlay = next;
  for (const l of listeners) l();
}

export function usePropertyOverlay(): PropertyOverlay | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => overlay,
  );
}

export type ShownProperty = Pick<SnapshotAsset, "label" | "value" | "valued_at"> & { pending: boolean };

/** What the property card shows: the fresh save while the published data is still the old version. */
export function shownProperty(
  published: Pick<SnapshotAsset, "label" | "value" | "valued_at"> | null,
  o: PropertyOverlay | null,
  dataVersion: number,
): ShownProperty | null {
  if (o && o.version === dataVersion) return { ...o.property, pending: true };
  return published ? { ...published, pending: false } : null;
}
