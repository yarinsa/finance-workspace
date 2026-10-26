import { registerSW } from "virtual:pwa-register";
import { setAppStatus } from "./appStatus";

let applyUpdate: ((reload?: boolean) => Promise<void>) | undefined;
let registration: ServiceWorkerRegistration | undefined;

/** Register the service worker (production only; it is not served by the dev server). */
export function initPwa(): void {
  if (!("serviceWorker" in navigator) || import.meta.env.DEV) return;
  applyUpdate = registerSW({
    // registerType "prompt": a new worker waits until the user taps the toast.
    onNeedRefresh: () => setAppStatus({ updateReady: true }),
    onRegisteredSW: (_url, reg) => void (registration = reg),
  });
}

/** Activate the waiting worker and reload into the new version. */
export function applyPwaUpdate(): void {
  void applyUpdate?.(true);
}

/**
 * Ask the browser to look for a new worker. iOS standalone rarely does this by itself, so it
 * is called whenever the app returns to the foreground.
 */
export function checkForPwaUpdate(): void {
  void registration?.update().catch(() => undefined);
}
