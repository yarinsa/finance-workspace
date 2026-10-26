import { describe, expect, it } from "vitest";
import { AXIS_LOCK_PX, PULL_MAX, PULL_THRESHOLD, isArmed, lockAxis, pullOffset } from "./pullToRefresh";

describe("pull-to-refresh", () => {
  it("damps finger travel and caps the indicator", () => {
    expect(pullOffset(-30)).toBe(0);
    expect(pullOffset(100)).toBe(50);
    expect(pullOffset(1000)).toBe(PULL_MAX);
  });

  it("arms only after the resisted distance passes the threshold", () => {
    expect(isArmed(PULL_THRESHOLD * 2 - 2)).toBe(false);
    expect(isArmed(PULL_THRESHOLD * 2)).toBe(true);
  });

  it("stays undecided until the finger has moved", () => {
    expect(lockAxis(AXIS_LOCK_PX - 1, 3)).toBeUndefined();
  });

  it("leaves horizontal drags (SwipeableRow) alone and claims vertical ones", () => {
    expect(lockAxis(-40, 12)).toBe("horizontal");
    expect(lockAxis(6, 30)).toBe("vertical");
  });
});
