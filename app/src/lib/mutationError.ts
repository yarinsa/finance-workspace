import { ApiOffline } from "./api";

/**
 * Message for a failed Relay mutation/query. The Relay network layer (relay.ts) throws
 * `ApiOffline` when the home computer is unreachable and passes it through to `onError`
 * unchanged, so `instanceof` works there; `markOffline` flips the shared online flag.
 */
export function failureMessage(e: Error, markOffline: () => void, fallback: string): string {
  if (e instanceof ApiOffline) {
    markOffline();
    return "אין חיבור למחשב הביתי";
  }
  return e.message || fallback;
}
