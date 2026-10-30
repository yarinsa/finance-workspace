import { describe, expect, it } from "vitest";
import { toGlobalId } from "./notifications";
import { groupCommand, tenantUuid } from "./tenantAdmin";

const A = "aaaaaaaa-0000-4000-8000-00000000000a";

describe("tenant admin helpers", () => {
  it("reads the uuid out of a Tenant global id", () => {
    expect(tenantUuid(toGlobalId(A, "Tenant"))).toBe(A);
  });

  it("builds the Cognito group command for a member", () => {
    expect(groupCommand({ id: toGlobalId(A, "Tenant") }, "new@example.com")).toBe(
      `infra/tenant-groups.sh add ${A} new@example.com`,
    );
  });
});
