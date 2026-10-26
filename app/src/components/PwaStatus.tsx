import { useEffect, useState } from "react";
import { ArrowDown, Loader2, RefreshCw, WifiOff } from "lucide-react";
import { dataMeta, reloadData, useDataVersion } from "@/lib/data";
import { useAppStatus } from "@/lib/appStatus";
import { applyPwaUpdate } from "@/lib/pwa";
import { useAppBadge, useResumeRefresh } from "@/hooks/useAppLifecycle";
import { usePullToRefresh } from "@/hooks/usePullToRefresh";
import { PULL_THRESHOLD } from "@/lib/pullToRefresh";

function useOnline(): boolean {
  const [online, setOnline] = useState(navigator.onLine);
  useEffect(() => {
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
    };
  }, []);
  return online;
}

const clock = (ms: number) => new Date(ms).toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });

/**
 * App-shell chrome for the installed PWA, mounted once under the providers: the offline /
 * expired-session banners, the "new version" toast and the pull-to-refresh indicator, plus the
 * lifecycle hooks (resume refresh, icon badge). Renders nothing in the normal online state.
 */
export function PwaStatus() {
  useDataVersion(); // dataMeta changes with every reload
  useResumeRefresh();
  useAppBadge();
  const online = useOnline();
  const { sessionExpired, updateReady } = useAppStatus();
  const pull = usePullToRefresh(reloadData);

  const offline = !online || dataMeta.fromCache;
  return (
    <>
      {pull.offset > 0 && (
        <div
          aria-hidden
          className="pointer-events-none fixed inset-x-0 z-50 flex justify-center"
          style={{ top: "calc(env(safe-area-inset-top) + 4px)", transform: `translateY(${pull.offset - 40}px)` }}
        >
          <span className="grid size-9 place-items-center rounded-full border bg-background text-brand shadow-lg">
            {pull.refreshing ? (
              <Loader2 className="size-5 animate-spin" />
            ) : (
              <ArrowDown
                className="size-5 transition-transform"
                style={{ transform: `rotate(${pull.armed ? 180 : (pull.offset / PULL_THRESHOLD) * 90}deg)` }}
              />
            )}
          </span>
        </div>
      )}
      {sessionExpired ? (
        <div className="flex items-center justify-center gap-3 bg-bad/15 px-4 py-1.5 text-xs font-semibold" role="alert">
          החיבור פג — התחבר מחדש
          <button
            type="button"
            className="rounded-full bg-brand px-3 py-1"
            style={{ color: "var(--lg-on-accent)" }}
            onClick={() => location.assign("/?login=1")}
          >
            התחבר
          </button>
        </div>
      ) : (
        offline && (
          <div className="flex items-center justify-center gap-2 bg-warn/20 px-4 py-1 text-xs font-semibold" role="status">
            <WifiOff className="size-3.5" />
            לא מקוון · נתונים מ-{clock(dataMeta.cachedAt ?? dataMeta.fetchedAt)}
          </div>
        )
      )}
      {updateReady && (
        <div
          className="fixed inset-x-4 z-50 flex items-center justify-between gap-3 rounded-2xl border bg-background px-4 py-3 text-sm shadow-lg md:inset-x-auto md:start-4 md:w-80"
          style={{ bottom: "calc(env(safe-area-inset-bottom) + 96px)" }}
          role="status"
        >
          <span className="font-semibold">גרסה חדשה זמינה</span>
          <button
            type="button"
            className="inline-flex items-center gap-1.5 rounded-full bg-brand px-3 py-1.5 font-semibold"
            style={{ color: "var(--lg-on-accent)" }}
            onClick={applyPwaUpdate}
          >
            <RefreshCw className="size-3.5" />
            רענן
          </button>
        </div>
      )}
    </>
  );
}
