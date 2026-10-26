// Pure math for the pull-to-refresh gesture (hooks/usePullToRefresh.ts). iOS standalone
// apps have no native pull-to-refresh, so the app draws its own.

/** Resisted pull distance (px) at which releasing triggers a refresh. */
export const PULL_THRESHOLD = 64;
/** Largest distance the indicator travels. */
export const PULL_MAX = 110;
/** Finger travel is damped so the pull feels elastic. */
const RESISTANCE = 0.5;
/** Movement (px) before the gesture picks an axis. */
export const AXIS_LOCK_PX = 8;

/** Indicator offset for a raw downward finger travel of `dy` px. */
export function pullOffset(dy: number): number {
  return Math.min(PULL_MAX, Math.max(0, dy) * RESISTANCE);
}

/** Whether releasing at this finger travel starts a refresh. */
export function isArmed(dy: number): boolean {
  return pullOffset(dy) >= PULL_THRESHOLD;
}

/**
 * Which way the gesture is going once it has moved far enough. Horizontal gestures belong to
 * `SwipeableRow` (and carousels), so the pull must stay out of them: the decision is made once,
 * on the first movement past the lock distance, and held for the rest of the touch.
 */
export function lockAxis(dx: number, dy: number): "horizontal" | "vertical" | undefined {
  if (Math.max(Math.abs(dx), Math.abs(dy)) < AXIS_LOCK_PX) return undefined;
  return Math.abs(dx) > Math.abs(dy) ? "horizontal" : "vertical";
}

/** True when the app runs from the home screen (iOS `navigator.standalone` or the display-mode query). */
export function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}
