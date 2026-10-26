/// <reference lib="webworker" />
// Service worker (vite-plugin-pwa, injectManifest). Goals: instant launch and read-only
// offline. Hashed assets are precached; pages and /data/*.json go to the network first.
// It never intercepts /api/*, /_callback or /_passkey (see lib/swRoutes.ts).
import { cleanupOutdatedCaches, matchPrecache, precacheAndRoute } from "workbox-precaching";
import { DATA_TIMEOUT_MS, classifyRequest, isCacheableData } from "./lib/swRoutes";

declare const self: ServiceWorkerGlobalScope;

/** Digested financial JSON; wiped on logout and on any 401. */
const DATA_CACHE = "plangram-data-v1";

cleanupOutdatedCaches();
// workbox maps "/" to the precached index.html by default (directoryIndex), which would serve the
// shell cache-first. Point it at a name that is never precached so "/" stays a normal
// navigation for the network-first handler below (the option's type has no "off").
precacheAndRoute(self.__WB_MANIFEST, { directoryIndex: "__no-directory-index__" });

self.addEventListener("message", (event) => {
  // workbox-window's `updateSW()` asks the waiting worker to take over.
  if (event.data?.type === "SKIP_WAITING") void self.skipWaiting();
  if (event.data?.type === "CLEAR_DATA") event.waitUntil(caches.delete(DATA_CACHE));
});

/** Stamp the response with when it was cached, so the UI can say how old the offline data is. */
async function stamp(res: Response): Promise<Response> {
  const headers = new Headers(res.headers);
  headers.set("x-sw-cached-at", String(Date.now()));
  return new Response(await res.blob(), { status: res.status, statusText: res.statusText, headers });
}

function fromCache(res: Response): Response {
  const headers = new Headers(res.headers);
  headers.set("x-sw-from-cache", "1");
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers });
}

async function data(event: FetchEvent): Promise<Response> {
  const cache = await caches.open(DATA_CACHE);
  const key = new URL(event.request.url).pathname; // ignore ?query so one file = one entry
  const network = fetch(event.request).then(async (res) => {
    if (res.status === 401) await caches.delete(DATA_CACHE);
    else if (
      isCacheableData({
        status: res.status,
        redirected: res.redirected,
        type: res.type,
        contentType: res.headers.get("content-type"),
      })
    ) {
      await cache.put(key, await stamp(res.clone()));
    }
    return res;
  });
  // Let a slow response still refresh the cache after we gave up waiting for it.
  event.waitUntil(network.catch(() => undefined));

  const timeout = new Promise<"timeout">((r) => setTimeout(() => r("timeout"), DATA_TIMEOUT_MS));
  try {
    const first = await Promise.race([network, timeout]);
    if (first !== "timeout") return first;
  } catch {
    /* network error: fall through to the cache */
  }
  const hit = await cache.match(key);
  return hit ? fromCache(hit) : network;
}

async function navigation(event: FetchEvent): Promise<Response> {
  try {
    // Redirects (an expired session bouncing to Cognito) come back as-is: never cached, never replaced.
    return await fetch(event.request);
  } catch {
    // Only a network error falls back to the shell; the SPA then boots from cached data.
    return (await matchPrecache("/index.html")) ?? Response.error();
  }
}

self.addEventListener("fetch", (event) => {
  const kind = classifyRequest({
    url: event.request.url,
    method: event.request.method,
    mode: event.request.mode,
    origin: self.location.origin,
  });
  if (kind === "logout") event.waitUntil(caches.delete(DATA_CACHE)); // no respondWith: the request goes through
  else if (kind === "data") event.respondWith(data(event));
  else if (kind === "navigation") event.respondWith(navigation(event));
});
