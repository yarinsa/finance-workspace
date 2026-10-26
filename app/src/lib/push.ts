// Web Push in the browser: subscribe this installed app to the notifications the Mac sends
// (finance/push.py). The VAPID public key comes from the API; the subscription is stored by it.
import { request } from "./api";

/** Why the toggle is (not) usable. "off"/"on" are the working states. */
export type PushState = "unsupported" | "ios-install" | "denied" | "offline" | "off" | "on";

export interface PushEnv {
  userAgent: string;
  maxTouchPoints: number;
  standalone: boolean;
  hasServiceWorker: boolean;
  hasPushManager: boolean;
  hasNotification: boolean;
  permission: NotificationPermission | null;
}

export function isIos(env: Pick<PushEnv, "userAgent" | "maxTouchPoints">): boolean {
  return /iPad|iPhone|iPod/.test(env.userAgent) || (/Macintosh/.test(env.userAgent) && env.maxTouchPoints > 1);
}

/**
 * Decide what the notifications card shows. iOS only exposes Web Push to an app added to the
 * home screen, so a Safari tab there gets the "install first" hint rather than "unsupported".
 */
export function pushState(env: PushEnv, apiOnline: boolean | null, subscribed: boolean): PushState {
  if (isIos(env) && !env.standalone) return "ios-install";
  if (!env.hasServiceWorker || !env.hasPushManager || !env.hasNotification) return "unsupported";
  if (env.permission === "denied") return "denied";
  if (apiOnline === false) return "offline";
  return subscribed && env.permission === "granted" ? "on" : "off";
}

export function readPushEnv(): PushEnv {
  const nav = navigator as Navigator & { standalone?: boolean };
  return {
    userAgent: nav.userAgent,
    maxTouchPoints: nav.maxTouchPoints ?? 0,
    standalone: nav.standalone === true || matchMedia("(display-mode: standalone)").matches,
    hasServiceWorker: "serviceWorker" in navigator,
    hasPushManager: "PushManager" in globalThis,
    hasNotification: "Notification" in globalThis,
    permission: "Notification" in globalThis ? Notification.permission : null,
  };
}

/** VAPID keys travel as unpadded base64url; pushManager.subscribe wants the raw bytes. */
export function urlBase64ToBytes(b64: string): Uint8Array<ArrayBuffer> {
  const padded = (b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

async function registration(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  return (await navigator.serviceWorker.getRegistration()) ?? null;
}

/** The existing push subscription of this browser, if any. */
export async function currentSubscription(): Promise<PushSubscription | null> {
  try {
    return (await (await registration())?.pushManager.getSubscription()) ?? null;
  } catch {
    return null;
  }
}

/**
 * Turn notifications on. The permission prompt is only raised here, so call this from a tap.
 * Resolves "denied" if the user refuses; throws ApiOffline/ApiError when the API can't take the subscription.
 */
export async function enablePush(): Promise<"on" | "denied"> {
  const reg = await registration();
  if (!reg) throw new Error("service worker not registered");
  if ((await Notification.requestPermission()) !== "granted") return "denied";
  const { key } = await request<{ key: string }>("GET", "/push/key");
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToBytes(key) }));
  await request("POST", "/push/subscribe", sub.toJSON());
  return "on";
}

/** Turn notifications off: tell the API, then drop the browser's subscription. */
export async function disablePush(): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) return;
  await request("POST", "/push/unsubscribe", { endpoint: sub.endpoint });
  await sub.unsubscribe();
}
