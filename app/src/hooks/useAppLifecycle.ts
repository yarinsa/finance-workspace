import { useEffect } from "react";
import { dataMeta, reloadData } from "@/lib/data";
import { shouldRefreshOnResume } from "@/lib/dataFetch";
import { checkForPwaUpdate } from "@/lib/pwa";
import { useInboxCount } from "@/lib/inbox";

/**
 * Native-feeling "refresh on foreground": when the app becomes visible again, or the network
 * returns, re-fetch the digested data if the last fetch is more than two minutes old
 * (`shouldRefreshOnResume`), and look for a new service worker. Failures are silent here:
 * `reloadData` records an expired session itself, and the offline banner covers the rest.
 */
export function useResumeRefresh(): void {
  useEffect(() => {
    const resume = () => {
      if (document.visibilityState !== "visible") return;
      checkForPwaUpdate();
      // Data served from the offline cache is refreshed as soon as the network is back, whatever its age.
      if (dataMeta.fromCache || shouldRefreshOnResume(dataMeta.fetchedAt, Date.now())) void reloadData().catch(() => undefined);
    };
    document.addEventListener("visibilitychange", resume);
    window.addEventListener("online", resume);
    return () => {
      document.removeEventListener("visibilitychange", resume);
      window.removeEventListener("online", resume);
    };
  }, []);
}

/** Mirror the open-inbox count on the home-screen icon where the Badging API exists (cleared at 0). */
export function useAppBadge(): void {
  const count = useInboxCount();
  useEffect(() => {
    const nav = navigator as Navigator & { setAppBadge?: (n: number) => Promise<void>; clearAppBadge?: () => Promise<void> };
    const done = count > 0 ? nav.setAppBadge?.(count) : nav.clearAppBadge?.();
    done?.catch(() => undefined);
  }, [count]);
}
