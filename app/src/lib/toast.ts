// A one-at-a-time confirmation ("השינוי נשמר."), outside React so the Relay network layer
// can raise it after any successful edit. `useToast` subscribes a component to it.
import { useSyncExternalStore } from "react";

export interface ToastMessage {
  id: number;
  text: string;
  /** Optional "בטל" (undo) for edits that can be reverted. */
  undo?: () => void;
}

const DURATION_MS = 4000;
let current: ToastMessage | null = null;
let timer: ReturnType<typeof setTimeout> | undefined;
let nextId = 1;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

/** Show `text` (replacing any toast already up) for a few seconds. */
export function showToast(text: string, undo?: () => void): void {
  clearTimeout(timer);
  current = { id: nextId++, text, undo };
  emit();
  timer = setTimeout(dismissToast, DURATION_MS);
}

export function dismissToast(): void {
  clearTimeout(timer);
  current = null;
  emit();
}

export function currentToast(): ToastMessage | null {
  return current;
}

export function useToast(): ToastMessage | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    currentToast,
  );
}

/** Mutations that are not an edit of the household's data (starting a sync) get no "saved" toast. */
export function isEditMutation(name: string): boolean {
  return !/sync/i.test(name);
}
