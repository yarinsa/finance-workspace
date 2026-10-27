import { afterEach, describe, expect, it, vi } from "vitest";
import { currentToast, dismissToast, isEditMutation, showToast } from "./toast";

describe("toast", () => {
  afterEach(() => {
    dismissToast();
    vi.useRealTimers();
  });

  it("a saved edit confirms itself, a started sync does not", () => {
    expect(isEditMutation("TransactionEditSheetUpdateMutation")).toBe(true);
    expect(isEditMutation("GoalEditorSheetGoalCreateMutation")).toBe(true);
    expect(isEditMutation("SyncsRetryMutation")).toBe(false);
  });

  it("shows one message at a time and goes away by itself", () => {
    vi.useFakeTimers();
    showToast("השינוי נשמר.");
    showToast("היעד נשמר.");
    expect(currentToast()?.text).toBe("היעד נשמר.");
    vi.advanceTimersByTime(3900);
    expect(currentToast()).not.toBeNull();
    vi.advanceTimersByTime(200);
    expect(currentToast()).toBeNull();
  });
});
