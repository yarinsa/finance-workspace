import { describe, expect, it } from "vitest";
import { buildCreateInput, buildUpdateInput, EMPTY_GOAL_FORM, isIsoDate, validateGoalForm, type GoalFormValues } from "@/lib/goalValidation";

const form = (over: Partial<GoalFormValues> = {}): GoalFormValues => ({
  ...EMPTY_GOAL_FORM,
  description: "חופשה",
  amount: "5000",
  ...over,
});

describe("validateGoalForm", () => {
  it("passes with valid inputs", () => {
    expect(validateGoalForm(form({ endDate: "2027-12-31" }))).toEqual({});
  });

  it("requires a non-blank description", () => {
    expect(validateGoalForm(form({ description: "" }))).toHaveProperty("description");
    expect(validateGoalForm(form({ description: "   " }))).toHaveProperty("description");
  });

  it("requires a positive amount", () => {
    expect(validateGoalForm(form({ amount: "" }))).toHaveProperty("amount");
    expect(validateGoalForm(form({ amount: "abc" }))).toHaveProperty("amount");
    expect(validateGoalForm(form({ amount: "0" }))).toHaveProperty("amount");
    expect(validateGoalForm(form({ amount: "-100" }))).toHaveProperty("amount");
    expect(validateGoalForm(form({ amount: "0.01" }))).toEqual({});
  });

  it("rejects dates that are not real ISO days", () => {
    expect(validateGoalForm(form({ endDate: "not-a-date" }))).toHaveProperty("endDate");
    expect(validateGoalForm(form({ endDate: "2027-02-30" }))).toHaveProperty("endDate");
    expect(validateGoalForm(form({ startDate: "2027-1-1" }))).toHaveProperty("startDate");
    expect(isIsoDate("2028-02-29")).toBe(true);
  });

  it("rejects an end date before the start date", () => {
    expect(validateGoalForm(form({ startDate: "2027-06-01", endDate: "2027-01-01" }))).toHaveProperty("endDate");
  });

  it("needs integer repetitions >= 1 when repeating", () => {
    expect(validateGoalForm(form({ interval: "MONTHLY", repetitions: "0" }))).toHaveProperty("repetitions");
    expect(validateGoalForm(form({ interval: "MONTHLY", repetitions: "1.5" }))).toHaveProperty("repetitions");
    expect(validateGoalForm(form({ interval: "MONTHLY", repetitions: "12" }))).toEqual({});
    // not repeating: the repetitions field is hidden and ignored
    expect(validateGoalForm(form({ repetitions: "0" }))).toEqual({});
  });

  it("rejects a negative rise", () => {
    expect(validateGoalForm(form({ rise: "-1" }))).toHaveProperty("rise");
    expect(validateGoalForm(form({ rise: "0" }))).toEqual({});
  });
});

describe("buildCreateInput", () => {
  it("sends only what has a value, with enum values", () => {
    expect(buildCreateInput(form({ endDate: "2027-12-31", interval: "YEARLY", repetitions: "3", rise: "100", horizon: "near" }))).toEqual({
      description: "חופשה",
      amount: "5000.00",
      endDate: "2027-12-31",
      interval: "YEARLY",
      repetitions: 3,
      rise: "100.00",
      horizon: "NEAR",
    });
    expect(buildCreateInput(form())).toEqual({ description: "חופשה", amount: "5000.00" });
  });
});

describe("buildUpdateInput", () => {
  const initial = form({ endDate: "2027-12-31", startDate: "2026-01-01", interval: "MONTHLY", repetitions: "6", rise: "50", horizon: "near" });

  it("sends nothing when nothing changed", () => {
    expect(buildUpdateInput({ ...initial }, initial)).toEqual({});
  });

  it("sends null for every cleared field and omits the untouched ones", () => {
    const cleared = { ...initial, endDate: "", startDate: "", interval: "" as const, rise: "", horizon: null };
    expect(buildUpdateInput(cleared, initial)).toEqual({
      endDate: null,
      startDate: null,
      interval: null,
      repetitions: 1,
      rise: null,
      horizon: null,
    });
  });

  it("sends only the changed value", () => {
    expect(buildUpdateInput({ ...initial, amount: "6000", description: " חופשה בחו״ל " }, { ...initial })).toEqual({
      description: "חופשה בחו״ל",
      amount: "6000.00",
    });
    expect(buildUpdateInput({ ...initial, endDate: "2028-01-01" }, initial)).toEqual({ endDate: "2028-01-01" });
  });
});
