import { describe, expect, it } from "vitest";
import { mixHex } from "./color";

describe("mixHex", () => {
  it("blends terracotta toward the cream panel for a quiet chart tint", () => {
    expect(mixHex("#b4533c", "#fffdf8", 0)).toBe("#b4533c");
    expect(mixHex("#b4533c", "#fffdf8", 1)).toBe("#fffdf8");
    expect(mixHex("#000000", "#ffffff", 0.5)).toBe("#808080");
  });
});
