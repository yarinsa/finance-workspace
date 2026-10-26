import { describe, expect, it } from "vitest";
import { pushState, urlBase64ToBytes, type PushEnv } from "./push";

const base: PushEnv = {
  userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X) Chrome/130",
  maxTouchPoints: 0,
  standalone: false,
  hasServiceWorker: true,
  hasPushManager: true,
  hasNotification: true,
  permission: "default",
};
const iphone = { ...base, userAgent: "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)", maxTouchPoints: 5 };

describe("pushState", () => {
  it("asks an iPhone in a Safari tab to add the app to the home screen first", () => {
    expect(pushState({ ...iphone, hasPushManager: false }, true, false)).toBe("ios-install");
  });
  it("lets the installed iPhone app subscribe", () => {
    expect(pushState({ ...iphone, standalone: true }, true, false)).toBe("off");
  });
  it("treats iPadOS posing as a Mac like an iPad", () => {
    const ipad = { ...base, userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", maxTouchPoints: 5 };
    expect(pushState(ipad, true, false)).toBe("ios-install");
  });
  it("is unsupported without PushManager on other platforms", () => {
    expect(pushState({ ...base, hasPushManager: false }, true, false)).toBe("unsupported");
  });
  it("shows denied before offline", () => {
    expect(pushState({ ...base, permission: "denied" }, false, false)).toBe("denied");
  });
  it("disables the toggle when the Mac/API is off", () => {
    expect(pushState(base, false, false)).toBe("offline");
  });
  it("is on only with both a subscription and the granted permission", () => {
    expect(pushState({ ...base, permission: "granted" }, true, true)).toBe("on");
    expect(pushState(base, true, true)).toBe("off");
  });
});

describe("urlBase64ToBytes", () => {
  it("decodes unpadded base64url", () => {
    expect([...urlBase64ToBytes("-_8")]).toEqual([251, 255]);
  });
});
