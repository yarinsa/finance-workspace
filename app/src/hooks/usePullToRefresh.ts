import { useEffect, useRef, useState } from "react";
import { AXIS_LOCK_PX, PULL_THRESHOLD, isArmed, isStandalone, lockAxis, pullOffset } from "@/lib/pullToRefresh";

export interface PullState {
  /** Indicator travel in px (0 when idle). */
  offset: number;
  armed: boolean;
  refreshing: boolean;
}

/**
 * Pull-to-refresh for the installed app (iOS standalone has no native one). Only active in
 * standalone display mode, only when the page is scrolled to the very top, and only for a
 * vertical drag: the gesture picks its axis on first movement (`lockAxis`) so horizontal
 * `SwipeableRow` drags are never touched. Touches that start inside an open sheet/dialog are
 * ignored. `onRefresh` should resolve when the data has been reloaded.
 */
export function usePullToRefresh(onRefresh: () => Promise<unknown>): PullState {
  const [state, setState] = useState<PullState>({ offset: 0, armed: false, refreshing: false });
  const refresh = useRef(onRefresh);
  refresh.current = onRefresh;

  useEffect(() => {
    if (!isStandalone()) return;
    let startX = 0;
    let startY = 0;
    let axis: ReturnType<typeof lockAxis>;
    let pulling = false;
    let busy = false;
    let tracking = false;
    let armed = false;

    const atTop = () => (document.scrollingElement?.scrollTop ?? 0) <= 0;

    const onStart = (e: TouchEvent) => {
      tracking = false;
      if (busy || e.touches.length !== 1 || !atTop()) return;
      if ((e.target as Element | null)?.closest('[role="dialog"], [data-no-ptr]')) return;
      startX = e.touches[0].clientX;
      startY = e.touches[0].clientY;
      axis = undefined;
      pulling = false;
      armed = false;
      tracking = true;
    };

    const onMove = (e: TouchEvent) => {
      if (!tracking) return;
      const dx = e.touches[0].clientX - startX;
      const dy = e.touches[0].clientY - startY;
      axis ??= lockAxis(dx, dy);
      if (axis === undefined) return;
      // Horizontal, upward, or the page started scrolling: this touch is not ours.
      if (axis === "horizontal" || dy < 0 || !atTop()) {
        if (pulling) setState({ offset: 0, armed: false, refreshing: false });
        tracking = pulling = false;
        return;
      }
      pulling = true;
      e.preventDefault(); // keep iOS from rubber-banding while we draw our own
      armed = isArmed(dy - AXIS_LOCK_PX);
      setState({ offset: pullOffset(dy - AXIS_LOCK_PX), armed, refreshing: false });
    };

    const onEnd = async () => {
      if (!pulling) return;
      tracking = pulling = false;
      if (!armed) return setState({ offset: 0, armed: false, refreshing: false });
      busy = true;
      setState({ offset: PULL_THRESHOLD, armed: true, refreshing: true });
      try {
        await refresh.current();
      } catch {
        /* the offline / expired-session banner explains why nothing changed */
      } finally {
        busy = false;
        setState({ offset: 0, armed: false, refreshing: false });
      }
    };

    const onCancel = () => {
      if (pulling) setState({ offset: 0, armed: false, refreshing: false });
      tracking = pulling = false;
    };

    document.addEventListener("touchstart", onStart, { passive: true });
    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("touchend", onEnd, { passive: true });
    document.addEventListener("touchcancel", onCancel, { passive: true });
    return () => {
      document.removeEventListener("touchstart", onStart);
      document.removeEventListener("touchmove", onMove);
      document.removeEventListener("touchend", onEnd);
      document.removeEventListener("touchcancel", onCancel);
    };
  }, []);

  return state;
}
