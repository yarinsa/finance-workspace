/** Distance (px) a drag must pass to reveal the action button. */
export const REVEAL_THRESHOLD = 72;
/** Resting offset (px) of an opened row; also the width of the action button. */
export const ACTION_WIDTH = 88;
/** Fraction of the row width past which a swipe commits the action. */
export const COMMIT_RATIO = 0.55;
/** Flick speed (px/s) that commits once the reveal threshold is passed. */
export const FLICK_VELOCITY = 800;

export type SwipeOutcome = "close" | "open-left" | "open-right" | "commit-left" | "commit-right";

export interface SwipeInput {
  /** Drag distance in px; negative = finger moved left (physical, not RTL-mirrored). */
  offset: number;
  /** Release velocity in px/s, same sign convention. */
  velocity: number;
  /** Row width in px. */
  width: number;
  canLeft: boolean;
  canRight: boolean;
}

/** Decides what a released horizontal drag does. Left = negative offset, right = positive; a disabled direction always closes. */
export function resolveSwipe({ offset, velocity, width, canLeft, canRight }: SwipeInput): SwipeOutcome {
  const left = offset < 0;
  if (left ? !canLeft : !canRight) return "close";
  const dist = Math.abs(offset);
  const speed = left ? -velocity : velocity;
  const dir = left ? "left" : "right";
  if (dist >= width * COMMIT_RATIO) return `commit-${dir}`;
  if (dist >= REVEAL_THRESHOLD) return speed > FLICK_VELOCITY ? `commit-${dir}` : `open-${dir}`;
  return "close";
}
