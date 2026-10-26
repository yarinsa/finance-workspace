import { describe, expect, it } from "vitest";
import { resolveSwipe } from "./swipe";

const base = { velocity: 0, width: 390, canLeft: true, canRight: true };

describe("resolveSwipe", () => {
  it("closes below the reveal threshold", () => {
    expect(resolveSwipe({ ...base, offset: -40 })).toBe("close");
    expect(resolveSwipe({ ...base, offset: 40 })).toBe("close");
  });
  it("opens past the reveal threshold in both directions", () => {
    expect(resolveSwipe({ ...base, offset: -90 })).toBe("open-left");
    expect(resolveSwipe({ ...base, offset: 90 })).toBe("open-right");
  });
  it("commits on a full swipe", () => {
    expect(resolveSwipe({ ...base, offset: -230 })).toBe("commit-left");
    expect(resolveSwipe({ ...base, offset: 230 })).toBe("commit-right");
  });
  it("commits on a fast flick past the reveal threshold only", () => {
    expect(resolveSwipe({ ...base, offset: -80, velocity: -1200 })).toBe("commit-left");
    expect(resolveSwipe({ ...base, offset: 80, velocity: 1200 })).toBe("commit-right");
    expect(resolveSwipe({ ...base, offset: -30, velocity: -1200 })).toBe("close");
    expect(resolveSwipe({ ...base, offset: -80, velocity: 1200 })).toBe("open-left");
  });
  it("closes a disabled direction, e.g. an income row with no offset action", () => {
    expect(resolveSwipe({ ...base, canRight: false, offset: 230 })).toBe("close");
    expect(resolveSwipe({ ...base, canRight: false, offset: 90, velocity: 2000 })).toBe("close");
    expect(resolveSwipe({ ...base, canRight: false, offset: -90 })).toBe("open-left");
    expect(resolveSwipe({ ...base, canLeft: false, offset: -230 })).toBe("close");
  });
});
