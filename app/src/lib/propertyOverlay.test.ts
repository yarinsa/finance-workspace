import { describe, expect, it } from "vitest";
import { shownProperty } from "./propertyOverlay";

const SAVED = { version: 3, property: { label: "אורט ישראל, בת ים", value: 2_200_000, valued_at: "2026-10-27" } };

describe("property card after a save", () => {
  it("shows the saved value at once instead of 'הוספה' while the rebuild publishes", () => {
    expect(shownProperty(null, SAVED, 3)).toMatchObject({ value: 2_200_000, pending: true });
  });

  it("goes back to the published snapshot once data was reloaded", () => {
    const published = { label: "אורט ישראל, בת ים", value: 2_200_000, valued_at: "2026-10-27" };
    expect(shownProperty(published, SAVED, 4)).toMatchObject({ value: 2_200_000, pending: false });
    expect(shownProperty(null, null, 4)).toBeNull();
  });
});
